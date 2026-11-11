"""The Reviewer: does this candidate Stage address the Spec, and can it be afforded?

Three layers, in this order, because the cheap deterministic ones should refuse before the
expensive one runs:

1. **Coverage.** Every objective the Spec says is ready appears in the Stage as a Task or as a
   Deferral, and every RUN task serves at least one live objective.
2. **The five gates plus the forced dry-run**, unchanged, from `compose/validate.py`.
3. **Budget**, including the interlock's provisional cap.

Layer 1 is backlog **A8**, which has been a `log.warning` since it was written. On job 22675512
a budget correction truncated `boltz_predict` off the chain, taking with it the only producer
of two of that campaign's four objectives; nothing refused it, the run was unwinnable from the
moment it was admitted, and the admitted graph recorded `rejected: null`. A warning in a log
nobody reads during an allocation is not a gate.

**The coverage check reads the executor's applied Spec, never the Stage's own claim about what
is open.** Not trusting that claim is the Reviewer's entire purpose: a Planner that could
assert a smaller Spec could widen its own coverage to whatever it had chosen to do. This is
also why the Spec has a single writer on the execution side of the boundary, so that in phase 7
a remote Planner cannot smuggle a Spec revision in with a Stage.
"""
from __future__ import annotations

from ..compose.graph import TaskGraph
from ..compose.validate import Validator
from ..core.budget import BudgetLedger
from ..core.decision import ValidationFailure
from ..core.spec import ObjectiveStatus, Spec, Stage


class StageReviewer:
    """Coverage, then the gates, then budget."""

    def __init__(self, validator: Validator, budget: BudgetLedger):
        self.validator = validator
        self.budget = budget

    # -- layer 1: coverage ---------------------------------------------------
    def coverage(self, stage: Stage, spec: Spec) -> ValidationFailure | None:
        """Every ready objective answered, and no task working for a dead one.

        Deliberately checked against `spec.ready()` rather than `spec.open_objectives()`: a
        blocked objective is one the Planner *cannot* plan yet, and demanding a Task for it
        would force exactly the invention this gate exists to prevent. A Deferral is an
        answer.
        """
        ready = {o.id for o in spec.ready()}
        answered = stage.covered
        missing = sorted(ready - answered)
        if missing:
            statements = [spec.objectives[m].statement or m for m in missing[:3]]
            return ValidationFailure(
                gate="coverage",
                reason=(f"{len(missing)} ready objective(s) neither planned nor deferred: "
                        + "; ".join(statements)),
                detail={"missing": missing,
                        "hint": "map a Task to each, or defer it with what it waits on"})

        for task in stage.runs:
            if not task.objectives:
                return ValidationFailure(
                    gate="coverage", node=task.task_id,
                    reason=f"task {task.task_id!r} serves no objective",
                    detail={"tool": task.tool})
            live = [oid for oid in task.objectives
                    if (o := spec.objectives.get(oid)) is not None
                    and o.status is not ObjectiveStatus.DELETED]
            if not live:
                return ValidationFailure(
                    gate="coverage", node=task.task_id,
                    reason=(f"task {task.task_id!r} serves only deleted objectives - it "
                            f"belongs in `cancels`, not in `tasks`"),
                    detail={"objectives": list(task.objectives)})

        unknown = sorted({oid for t in stage.runs for oid in t.objectives}
                         - set(spec.objectives))
        if unknown:
            return ValidationFailure(
                gate="coverage",
                reason=f"task(s) reference objectives not in the applied Spec: {unknown}",
                detail={"unknown": unknown,
                        "hint": "the Spec's only writer is the executor; publish the "
                                "revision before planning against it"})
        return None

    # -- layer 3: budget -----------------------------------------------------
    def affordable(self, graph: TaskGraph) -> ValidationFailure | None:
        """Estimate against what is AVAILABLE - remaining less everything in flight.

        Gate 5 already does this, so this layer exists for the Stage-level commitment that
        gate 5 cannot see. Marked `transient`, because contention is a property of the moment
        rather than of the graph: without that distinction a policy answers contention by
        mutilating its intent, which reads as the policy quietly degrading.
        """
        est = self.validator.estimate(graph)
        if blown := self.budget.would_exceed(est):
            return ValidationFailure(
                gate="budget", transient=True,
                reason=f"stage estimate exceeds available budget in {blown}",
                detail={"estimate": est,
                        "available": {d: self.budget.available(d) for d in blown}})
        return None

    # -- all three -----------------------------------------------------------
    async def review(self, stage: Stage, graph: TaskGraph,
                     spec: Spec) -> ValidationFailure | None:
        """The verdict. `None` means approved.

        Order matters: coverage is a pure set comparison, the gates are deterministic
        properties of the graph, and only the dry-run instantiates task agents. Refusing in
        that order means a Stage that was never going to be admitted costs almost nothing to
        refuse.
        """
        if (f := self.coverage(stage, spec)) is not None:
            return f
        if (f := self.validator.validate(graph)) is not None:
            return f
        if (f := self.affordable(graph)) is not None:
            return f
        return await self.validator.dry_run(graph)
