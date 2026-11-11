"""The Goal: what the caller asked for, fixed at call time.

Everything else in the control plane is derived and mutable. The Goal is not: it is the one
statement of intent that outlives every Spec revision, so a campaign that has re-specified
itself five times can still be asked what it was for.

Until now `goal` was a bare string on `CampaignSpec` that no reasoner parsed - carried into
`ExperimentIntent.goal` and `TaskGraph.intent_goal` verbatim, rendered into one model's prompt,
and read by nothing that decided anything. The objectives sat beside it as a flat
caller-supplied list with no relation to it. This type is where that relation becomes
expressible: the Specifier's job is `Goal -> Spec`, and a `Spec` is the mapping of this Goal
onto the outputs the Toolkit can actually produce.

`core` imports nothing internal except `core`, so this holds only plain data and the two
`core` types a goal genuinely needs: `Objective` for what it is optimising, and `ArtifactRef`
for the files it points at.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .artifacts import ArtifactRef
from .pareto import Objective


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Goal(BaseModel):
    """The caller's config: what to achieve, with what, and inside what limits.

    Deliberately *not* a copy of `CampaignSpec`. The spec also carries how the campaign is
    driven - backend, concurrency, stagnation, cycle bounds - and none of that is the Goal. A
    Specifier handed this object can see what success means and what it may spend, and nothing
    about the loop it lives in, which is what keeps `Goal -> Spec` a statement about the
    science rather than about the engine.
    """

    #: The caller's own words. Prose, not a schema: a reasoner may read it, and a deterministic
    #: Specifier ignores it. Kept because it is the only record of intent a later reader has
    #: that is not already an objective.
    text: str

    #: What the campaign is optimising, declared against property NAMES (decision 0012). These
    #: are the ranking objectives: directions rank, min/max prune. A `SpecObjective` generated
    #: by a Specifier refers to these by name - it never invents a new source for one.
    objectives: list[Objective] = Field(default_factory=list)

    #: Input files the Goal refers to - a target structure, a ligand, a contig spec. Typed, so
    #: validation gate 1 can satisfy a graph's root input ports from them by declared type
    #: instead of waving them through, and so a Planner can see what it has to start from.
    reference_data: dict[str, ArtifactRef] = Field(default_factory=dict)

    #: Spendable limits, by budget dimension. The same keys `BudgetLedger.limits` uses.
    budget: dict[str, float] = Field(default_factory=dict)

    #: Wall-clock limit in seconds, when the caller set one. `None` means unbounded here and
    #: bounded only by the allocation - which is the usual case on HPC, where SLURM's `--time`
    #: is the real backstop and this field would only duplicate it less reliably.
    walltime_s: float | None = None

    declared_at: datetime = Field(default_factory=_now)

    def objective(self, name: str) -> Objective | None:
        return next((o for o in self.objectives if o.name == name), None)

    @property
    def objective_names(self) -> list[str]:
        return [o.name for o in self.objectives]
