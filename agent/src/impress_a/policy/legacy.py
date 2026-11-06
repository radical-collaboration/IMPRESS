"""The strangler adapter: any `ControlPolicy` as a Specifier/Planner pair.

This file exists so the role pipeline can be proven behaviour-identical before any
responsibility actually moves. `test_roles_pipeline_reproduces_the_legacy_campaign`, in
`tests/test_campaign.py`, runs the same policy down both paths and compares the tree, the front
and the stop reason; a refactor without that test is a rewrite.

It is scaffolding, and phase 11 deletes it along with `ControlPolicy` itself.

**The overflow is named, not duck-typed.** `decide` returns a four-member union - ComposeAndRun,
Backtrack, RequestHuman, Stop - and the two role interfaces are deliberately narrower, because
in the target design stopping is the Listener's or the executor's, and branching from an earlier
node is a `SpecObjective.parent_node`, not a verb. The three non-planning members therefore have
nowhere to go in the new contracts, so they land on explicit attributes here and
`runtime/roles.py` reads them by name. `control/plane.py` duck-typed for `steer` once and the
cost was that nobody could tell which objects answered it; an attribute a named importer reads
is traceable.
"""
from __future__ import annotations

from typing import Any

from ..core.decision import (
    Backtrack,
    ComposeAndRun,
    ExperimentIntent,
    RequestHuman,
    Stop,
    ValidationFailure,
)
from ..core.goal import Goal
from ..core.spec import (
    Aim,
    ObjectiveStatus,
    SatisfactionRule,
    Spec,
    SpecObjective,
    SpecRevision,
    Stage,
    TaskMapping,
)
from .planner import BasePlanner, PlanningContext
from .specifier import BaseSpecifier


class LegacySpecifier(BaseSpecifier):
    """One Aim, one objective per declared ranking objective.

    The satisfaction rule is lifted straight from the objective's own `min`/`max`, so an
    objective the caller left unbounded - `total_score` with a direction and no bound, which is
    the common case - gets a rule that can never hold. That is correct rather than awkward: an
    unbounded objective has no satisfaction condition, so the Spec does not complete and the
    campaign stops for the reasons it always did. It is also what makes parity testable at all.
    """

    name = "legacy-spec"

    def __init__(self, inner_name: str = "?") -> None:
        self.inner_name = inner_name

    async def initial_spec(self, goal: Goal) -> Spec:
        aim = Aim(statement=goal.text or "the caller's goal")
        objectives = [
            SpecObjective(
                aim=aim.id,
                statement=f"{o.direction.value} {o.name}",
                targets=[o.name],
                satisfied_when=SatisfactionRule(kind="metric_in_range", metric=o.name,
                                                min=o.min, max=o.max),
            )
            for o in goal.objectives
        ]
        spec = Spec()
        spec.apply(SpecRevision(new_aims=[aim], new_objectives=objectives,
                                rationale=f"legacy adapter over {self.inner_name}"))
        return spec


class LegacyPlanner(BasePlanner):
    """Calls `decide` and renders a `ComposeAndRun` as a Stage.

    The rendering mirrors what `Composer.compose` does with an intent - one task per
    (replica, position) with the same id shape - so that `runtime/roles.py` can turn the Stage
    back into the intent the executor already accepts. That round trip is what keeps phase 1
    from touching `compose/` or `exec/` at all, and `test_a_stage_round_trips_through_an_intent`
    pins it.
    """

    name = "legacy-plan"

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = f"legacy-plan({getattr(inner, 'name', '?')})"
        #: Overflow from the four-member Decision union. Read by name in `runtime/roles.py`.
        self.pending_stop: str | None = None
        self.pending_backtrack: tuple[str, str] | None = None
        self.pending_human: tuple[str, dict] | None = None

    def _render(self, intent: ExperimentIntent, spec: Spec) -> Stage:
        open_ids = [o.id for o in spec.ready()]
        tasks: list[TaskMapping] = []
        for lineage in range(max(1, intent.replicas)):
            for i, tool in enumerate(intent.stages):
                tasks.append(TaskMapping(
                    task_id=f"r{lineage}_s{i}_{tool}",
                    # Every task serves every open objective: the legacy policy made one
                    # decision for the whole chain, so attributing a subset would be an
                    # invention. Phase 3's planner maps them one to one.
                    objectives=list(open_ids),
                    tool=tool,
                    params=dict(intent.params.get(tool, {})),
                    lineage=lineage))
        return Stage(spec_generation=spec.generation, tasks=tasks,
                     rationale=f"legacy: {intent.goal[:60]}")

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        decision = await self.inner.decide(ctx.observation)
        if isinstance(decision, ComposeAndRun):
            return self._render(decision.intent, spec)
        if isinstance(decision, Stop):
            self.pending_stop = decision.reason
        elif isinstance(decision, Backtrack):
            self.pending_backtrack = (decision.node_id, decision.rationale)
        elif isinstance(decision, RequestHuman):
            self.pending_human = (decision.question, dict(decision.context))
        return None

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """Hand the rejection to the wrapped policy's own `on_rejected`, unchanged.

        Including its tail-truncation heuristic, which phase 10 removes. Reproducing the
        legacy behaviour is the whole job of this file - fixing it here would make the parity
        test pass against something that never ran.
        """
        intent = ExperimentIntent(goal=ctx.goal.text,
                                  stages=[t.tool for t in stage.tasks if t.lineage == 0],
                                  params={t.tool: t.params for t in stage.tasks},
                                  replicas=stage.lineages)
        answer = await self.inner.on_rejected(ComposeAndRun(intent=intent), rejection)
        if isinstance(answer, ComposeAndRun):
            out = self._render(answer.intent, spec)
            out.attempt = stage.attempt + 1
            return out
        if isinstance(answer, Stop):
            self.pending_stop = answer.reason
        return None

    async def after_collect(self, outcome: Any, obs: Any) -> None:
        """`interpret`, which belongs to whoever collects the outcome.

        The executor used to call this on its own reference to the policy, which worked only
        while the two shared a process: drive a reasoner through a remote session and the
        executor's policy is a placeholder, so the hook never fired and a policy that
        accumulates across runs silently stopped accumulating.
        """
        if hasattr(self.inner, "interpret"):
            await self.inner.interpret(outcome, obs)


class DecideAsRoles:
    """A `ControlPolicy` presented as the two halves. Scaffolding; deleted in phase 11."""

    def __init__(self, policy: Any) -> None:
        self.policy = policy
        self.name = f"roles({getattr(policy, 'name', '?')})"
        self.specifier = LegacySpecifier(getattr(policy, "name", "?"))
        self.planner = LegacyPlanner(policy)


def all_open_deleted(spec: Spec, reason: str) -> SpecRevision:
    """A revision that closes every open objective - the Spec-level way to say "stop".

    Used by `runtime/roles.py` when a wrapped policy stops: marking the objectives DELETED
    makes `spec.complete()` true, so termination flows through the designed path rather than a
    special case. The reason is still passed to `session.stop` verbatim, because a campaign's
    recorded reason is the one a reader will ask about.
    """
    return SpecRevision(deleted=[o.id for o in spec.open_objectives()],
                        status_changes={}, rationale=reason) if spec.open_objectives() else \
        SpecRevision(rationale=reason)


__all__ = ["DecideAsRoles", "LegacyPlanner", "LegacySpecifier", "all_open_deleted",
           "ObjectiveStatus"]
