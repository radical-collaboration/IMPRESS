"""The Planner contract: `Objective -> Task`, emitted as a candidate Stage.

The other half of the old `decide`. A Planner answers "which Task addresses this objective, with
what parameters" - and nothing about what the objectives should be, which is the Specifier's.

Four rules:

**Every open objective gets a Task or a `Deferral`.** Not a subset. An objective whose inputs
do not exist yet is deferred, with what it is waiting on; one that is simply inconvenient is
not. The Reviewer refuses a Stage that silently drops an objective, which is the gate backlog
A8 has been missing - on job 22675512 a budget correction truncated the only producer of two of
four objectives off the chain, the run was unwinnable from that moment, and the admitted graph
recorded `rejected: null`.

**Cancellation is a Planner duty, and it is decidable.** A pending Task is an orphan only when
*every* objective mapped to it is DELETED - which is why `TaskMapping.objectives` is a list.
With a single objective per task the question could not be asked.

**`replan` is handed a reason, not a refusal.** A rejection carries the gate and the reason, and
`ValidationFailure.transient` distinguishes "this graph is wrong" (gates 1-4, deterministic
properties of the graph) from "right now is a bad moment" (budget contention). Without that
distinction a policy answers contention by mutilating its intent - dropping replicas, truncating
stages - in response to what *other* runs are consuming, which reads as the policy quietly
degrading.

**It may import `core` only**, for the reason in `specifier.py`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.decision import CampaignObservation, ValidationFailure
from ..core.goal import Goal
from ..core.spec import Spec, Stage


class PlanningContext:
    """What a Planner may look at when choosing Tasks.

    Holds the live `Spec` separately from the evidence because the two have different
    authorities: the Spec is applied state owned by the executor, while the observation is a
    snapshot. A Planner that conflated them could plan against objectives it had itself
    imagined.
    """

    __slots__ = ("goal", "observation", "in_flight", "attempt", "last_rejection")

    @property
    def orphans(self) -> list[str]:
        """Task ids whose every objective is now DELETED - cancellable work.

        Read off the observation rather than passed separately, because that is what crosses
        the process boundary in phase 7. Deciding to cancel is the Planner's; computing the
        fact needs both the task registry and the applied Spec, which only the executor sees.
        """
        return list(self.observation.orphan_tasks)

    def __init__(self, goal: Goal, observation: CampaignObservation,
                 in_flight: list[str] | None = None, attempt: int = 0,
                 last_rejection: ValidationFailure | None = None) -> None:
        self.goal = goal
        self.observation = observation
        #: Task ids currently in flight, so a Planner can avoid re-planning work it is already
        #: waiting on - and can find the pending Tasks whose objectives have since been DELETED.
        self.in_flight = in_flight or []
        self.attempt = attempt
        self.last_rejection = last_rejection

    @property
    def cycle(self) -> int:
        return self.observation.cycle

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (f"PlanningContext(cycle={self.cycle}, in_flight={len(self.in_flight)}, "
                f"attempt={self.attempt})")


@runtime_checkable
class Planner(Protocol):
    """Spec in, candidate Stage out."""

    name: str

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage:
        """Map ready objectives onto Tasks; defer the blocked ones; cancel the orphans."""
        ...

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """Answer a rejection. `None` means "I have no better Stage" and ends the campaign.

        Bounded by the caller, and independently by the executor, because a reasoner driving
        itself is under no obligation to honour anyone's retry budget.
        """
        ...


class BasePlanner:
    """Convenience base. `replan` gives up, loudly, rather than looping.

    Deliberately not "shrink and retry": the two shipped policies both truncated the *tail* of
    their stage list on a budget rejection, which is a cost heuristic that knows nothing about
    what the graph can then measure. A subclass that wants to shrink should shrink breadth,
    which cannot change what is producible.
    """

    name = "base"

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage:
        raise NotImplementedError

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        return None
