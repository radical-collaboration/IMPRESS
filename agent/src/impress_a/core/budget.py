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

from pydantic import BaseModel, Field


class BudgetLedger(BaseModel):
    limits: dict[str, float] = Field(default_factory=dict)
    spent: dict[str, float] = Field(default_factory=dict)
    #: hold_id -> estimated cost, for work admitted but not yet settled.
    holds: dict[str, dict[str, float]] = Field(default_factory=dict)

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

    def exhausted(self) -> list[str]:
        """Dimensions with nothing left. Deliberately ignores reservations: a campaign
        with everything in flight is busy, not exhausted, and must not terminate."""
        return [d for d in self.limits if self.remaining(d) <= 0]

    def fraction_used(self, dim: str) -> float:
        lim = self.limits.get(dim)
        if not lim:
            return 0.0
        return self.spent.get(dim, 0.0) / lim
