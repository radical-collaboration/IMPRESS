"""Multi-dimensional budget ledger.

Several independent dimensions, any of which can terminate a campaign. Cost is also a
declared objective, so the policy is pushed toward cheap experiments rather than merely
stopped at the wall.

Admission RESERVES and completion SETTLES. Without that, gate 5 checks an estimate
against a budget that is only debited once a graph finishes, so any two submissions in
flight at once both validate against the same untouched remaining budget and the campaign
overspends. The reservation is what makes the gate mean anything under concurrency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Walltime(BaseModel):
    """Elapsed and remaining wall clock.

    A dimension the ledger could not express: `limits`/`spent` are consumables, and wall clock
    is not - it passes whether or not work is running. `None` for `limit_s` means unbounded
    here and bounded only by the allocation, which is the usual case on HPC where SLURM's
    `--time` is the real backstop and this field would only duplicate it less reliably.
    """

    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    limit_s: float | None = None

    @property
    def elapsed_s(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    @property
    def remaining_s(self) -> float:
        if self.limit_s is None:
            return float("inf")
        return self.limit_s - self.elapsed_s

    def would_exceed(self, projected_s: float) -> bool:
        return self.limit_s is not None and projected_s > self.remaining_s


class BurnRate(BaseModel):
    """Consumption per second, MEASURED over a window.

    For open-ended work, which is what the Toolkit's budget requirements are stated as. A rate
    derived from `spent / elapsed` is a measurement; one derived from `cost_model` would be the
    declared estimate wearing a different unit, and those figures sit 2.25x-69x above
    measurement on purpose because they feed gates that refuse graphs.
    """

    per_s: dict[str, float] = Field(default_factory=dict)
    measured_over_s: float = 0.0
    samples: int = 0

    def project(self, dim: str, horizon_s: float) -> float:
        return self.per_s.get(dim, 0.0) * horizon_s


class Commitment(BaseModel):
    """What one pending Stage has promised to spend.

    Distinct from a `holds` reservation, which is per RUN and per dimension. A commitment is
    per STAGE and carries the cap the Toolkit declared: the outline's "maximum allocation
    commitment" is the smaller of an optional workflow maximum and a per-stage hard limit,
    which is `min(goal.budget[d], card.max_commitment[d])`.
    """

    stage_id: str
    projected: dict[str, float] = Field(default_factory=dict)
    cap: dict[str, float] = Field(default_factory=dict)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def exceeds_cap(self) -> list[str]:
        return [d for d, v in self.projected.items()
                if d in self.cap and v > self.cap[d]]


class BudgetLedger(BaseModel):
    limits: dict[str, float] = Field(default_factory=dict)
    spent: dict[str, float] = Field(default_factory=dict)
    #: What the same work actually MEASURED, accumulated beside `spent` and never used to
    #: refuse anything. `spent` is declared cost, and deliberately so: it is what `reserve`
    #: and `settle` work in, and a budget that reserves pessimistically is a budget that does
    #: its job. That is also why it must not be the figure reported OUTSIDE the campaign - the
    #: declared figures sit multiples above measurement, so an enclosing campaign manager told
    #: `spent` is told the headroom as well as the cost, and its own learned-cost estimate
    #: converges on a number no run ever consumed (backlog G20). The input was already there:
    #: `ExecutionResults.cost_measured` is summed per run and was folded into nothing.
    spent_measured: dict[str, float] = Field(default_factory=dict)
    #: hold_id -> estimated cost, for work admitted but not yet settled.
    holds: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: Wall clock, when the campaign declared a limit. Separate from `limits` because wall
    #: clock is not a consumable: it passes whether or not work is running.
    walltime: Walltime | None = None
    #: stage_id -> what that pending Stage promised. Layered BESIDE `holds` rather than
    #: replacing it: `reserve`/`settle`/`release` are on every admission path, and rewriting
    #: them would make budget refusals untestable against recorded Delta behaviour.
    commitments: dict[str, Commitment] = Field(default_factory=dict)

    # -- what has been consumed ---------------------------------------------
    def remaining(self, dim: str) -> float:
        """Limit less what has actually been SPENT. Reservations are not spending."""
        if dim not in self.limits:
            return float("inf")
        return self.limits[dim] - self.spent.get(dim, 0.0)

    def reserved(self, dim: str) -> float:
        return sum(h.get(dim, 0.0) for h in self.holds.values())

    def available(self, dim: str) -> float:
        """What a NEW submission may claim: remaining less everything in flight."""
        return self.remaining(dim) - self.reserved(dim)

    def would_exceed(self, cost: dict[str, float]) -> list[str]:
        """Return the dimensions this cost would blow. Empty list = affordable."""
        return [d for d, c in cost.items() if c > self.available(d)]

    # -- reserve / settle ----------------------------------------------------
    def reserve(self, cost: dict[str, float], hold_id: str) -> list[str]:
        """Claim `cost` for in-flight work. Returns blown dimensions; [] on success.

        All-or-nothing, and synchronous with no awaits, so the check and the claim cannot
        be interleaved by another submission.
        """
        if blown := self.would_exceed(cost):
            return blown
        self.holds[hold_id] = dict(cost)
        return []

    def settle(self, hold_id: str, actual: dict[str, float]) -> None:
        """Work finished: drop the reservation and charge what it really cost."""
        self.holds.pop(hold_id, None)
        self.charge(actual)

    def release(self, hold_id: str) -> None:
        """Work never ran: drop the reservation, charge nothing.

        Every failure path after a successful reserve must reach this. A leaked hold is
        silent - it shrinks `available` forever, and the campaign simply stops admitting
        work with no error to explain why.
        """
        self.holds.pop(hold_id, None)

    def charge(self, cost: dict[str, float]) -> None:
        for d, c in cost.items():
            self.spent[d] = self.spent.get(d, 0.0) + c

    def charge_measured(self, cost: dict[str, float]) -> None:
        """Accumulate what was measured. Refuses nothing, bounds nothing, gates nothing.

        Kept strictly beside `charge` rather than folded into it, because the moment a
        measured figure could move `remaining()` it would start deciding admissions - and a
        measurement arrives only after the work it describes is already paid for, so an
        admission gate reading it would be refusing tomorrow's work on yesterday's luck.
        """
        for d, c in cost.items():
            self.spent_measured[d] = self.spent_measured.get(d, 0.0) + c

    def exhausted(self) -> list[str]:
        """Dimensions with nothing left. Deliberately ignores reservations: a campaign
        with everything in flight is busy, not exhausted, and must not terminate."""
        return [d for d in self.limits if self.remaining(d) <= 0]

    # -- walltime, burn and commitments --------------------------------------
    def commit(self, c: Commitment) -> list[str]:
        """Record a Stage's commitment. Returns the dimensions that exceed its declared cap."""
        self.commitments[c.stage_id] = c
        return c.exceeds_cap()

    def release_commitment(self, stage_id: str) -> None:
        self.commitments.pop(stage_id, None)

    def committed(self, dim: str) -> float:
        """Projected spend across every pending Stage."""
        return sum(c.projected.get(dim, 0.0) for c in self.commitments.values())

    def burn_rate(self) -> BurnRate:
        """Measured consumption per second, from what has actually been SPENT.

        Zero until something settles, which is correct: a rate with no measurement behind it
        is a guess, and the one thing this must not be is the declared estimate in new units.
        """
        if self.walltime is None or self.walltime.elapsed_s <= 0:
            return BurnRate()
        elapsed = self.walltime.elapsed_s
        return BurnRate(per_s={d: v / elapsed for d, v in self.spent.items()},
                        measured_over_s=elapsed, samples=len(self.spent))

    def project(self, dim: str, horizon_s: float) -> float:
        """What the measured rate says `horizon_s` more seconds would cost."""
        return self.burn_rate().project(dim, horizon_s)

    def would_exceed_walltime(self, projected_s: float) -> bool:
        return self.walltime is not None and self.walltime.would_exceed(projected_s)

    def fraction_used(self, dim: str) -> float:
        lim = self.limits.get(dim)
        if not lim:
            return 0.0
        return self.spent.get(dim, 0.0) / lim
