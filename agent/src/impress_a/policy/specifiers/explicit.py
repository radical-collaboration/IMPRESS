"""Model D's Specifier half: deterministic, and the scientific control.

Maps the Goal onto the Toolkit's output space by asking, for each declared objective, which
Task reports that metric and what that Task emits. That is the whole of `Goal -> Spec` for a
rule-driven arm, and it is reproducible end to end - which is what makes D the baseline the
other three must justify their cost against.

Two things it does that the placeholder `LegacySpecifier` cannot, and that are the point of
the Specifier existing at all:

**It refuses to specify what the Toolkit cannot produce.** An objective no enabled Task
reports is recorded with `unproducible` in its statement and left OPEN rather than quietly
dropped, so the Reviewer's coverage gate sees it and the campaign says what it could not do.
On job 22675512 the opposite happened: a budget correction removed the only producer of two of
four objectives, nothing noticed, and the admitted graph recorded `rejected: null`.

**It expresses exploitation as a Spec change, not a parameter tweak.** When the front is
non-empty, `revise` adds one refinement objective carrying `parent_node` - the design to
improve on. That keeps ADR 0004's non-destructive backtracking reachable from the Spec (an
objective may name any earlier node, so re-specifying never costs the population), and it is
the mechanism phase 8 makes executable by feeding a parent's artifacts into a child chain. The
legacy cascade raised `diffusion_steps` instead, which asks for the same draw again, harder.

Satisfaction stays inherited and rule-driven, but a refinement objective needs its threshold
**bound to new evidence** or it satisfies itself. `DataRegistry.satisfies` counts hits against
everything realized so far, and the parent's own measurement is by definition already on the
record when the objective is created - so a default `n=1` rule is met the instant the objective
exists. That also defeats the open-refinement cap, because an objective satisfied immediately
leaves the open set and the next signal adds another: the Spec grows every cycle. Hence
`n = hits + 1` at creation, which is what "one MORE design over the threshold" has to mean.
"""
from __future__ import annotations

from ...core.goal import Goal
from ...core.spec import (
    Aim,
    SatisfactionRule,
    Spec,
    SpecObjective,
    SpecRevision,
)
from ..specifier import BaseSpecifier, SpecEvidence

#: At most one open refinement objective at a time. A Specifier that adds one per signal would
#: grow the Spec without bound and the campaign would never complete - the same class of defect
#: as a stagnation counter that can only rise.
MAX_OPEN_REFINEMENTS = 1


class ThresholdSpecifier(BaseSpecifier):
    """One Aim for the Goal, one objective per declared metric, refinements as data arrives."""

    name = "threshold-spec"

    def __init__(self, max_refinements: int = MAX_OPEN_REFINEMENTS) -> None:
        self.max_refinements = max_refinements
        self._refinement_aim: str | None = None

    async def initial_spec(self, goal: Goal) -> Spec:
        aim = Aim(statement=goal.text or "satisfy every declared objective")
        objectives: list[SpecObjective] = []
        # How many designs over the bar the caller asked for. 0 - the default for every
        # campaign that declares nothing - keeps the old "one is enough", so no existing
        # campaign moves.
        wanted = max(1, goal.target_front)
        for obj in goal.objectives:
            bounded = obj.min is not None or obj.max is not None
            objectives.append(SpecObjective(
                aim=aim.id,
                statement=f"{obj.direction.value} {obj.name}"
                          + ("" if bounded else " (ranks; no threshold to meet)")
                          + (f" x{wanted}" if bounded and wanted > 1 else ""),
                targets=[obj.name],
                # A bounded objective is met when `n` designs clear the threshold. An
                # unbounded one has no finish line - it ranks - so what the campaign owes it
                # is a MEASUREMENT, without which the front cannot order anything by it.
                #
                # `n` IS WHERE THE GOAL'S COUNT LANDS, and it only applies to the bounded
                # ones. A campaign declaring `target_front: 10` was asking for ten designs
                # meeting every threshold, and got a Spec satisfied by the FIRST design that
                # cleared each one - so arm C of the first four-arm smoke ran 24 tasks and
                # stopped at cycle 0, correctly, on "every spec objective satisfied"
                # (backlog G11). Raising it on an unbounded objective would be meaningless:
                # ten readings of a number nobody has to beat say nothing more than one, and
                # `tests/test_campaign.py` rules on exactly that.
                #
                # What `n` counts is READINGS, not distinct designs:
                # `DataRegistry.satisfies` is `len(metrics(metric)) >= n`, one row per
                # (task, metric) per ingested outcome. The experiment's endpoint is distinct
                # T2 designs after sequence clustering, which is a different and smaller
                # number. At one scoring task per lineage the two track closely enough to
                # stop on, but this rule is a stopping condition and not a score - the
                # harness is what scores.
                satisfied_when=SatisfactionRule(
                    kind="metric_in_range" if bounded else "metric_present",
                    metric=obj.name, min=obj.min, max=obj.max,
                    n=wanted if bounded else 1),
            ))
        spec = Spec()
        spec.apply(SpecRevision(new_aims=[aim], new_objectives=objectives,
                                rationale=f"{self.name}: {len(objectives)} declared objectives"))
        return spec

    def unproducible(self, spec: Spec, ev: SpecEvidence) -> list[str]:
        """Objective ids whose metric no enabled Task reports.

        Answered from the `ToolkitView` on the observation, so it is the enabled set rather
        than the whole registry - a campaign that narrowed its stages has narrowed what it can
        produce, and saying otherwise would be the mock-chain-on-a-GPU failure in another form.
        """
        view = ev.observation.toolkit
        if view is None:
            return []
        out = []
        for obj in spec.open_objectives():
            if obj.targets and not any(view.reporting(t) for t in obj.targets):
                out.append(obj.id)
        return out

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        front = ev.observation.pareto_front
        if not front:
            # Nothing to refine. The Planner keeps drawing; adding objectives here would be
            # inventing work from the absence of evidence.
            return SpecRevision()

        open_refinements = [o for o in spec.open_objectives() if o.parent_node is not None]
        if len(open_refinements) >= self.max_refinements:
            return SpecRevision()

        best = front[0]
        target = self._weakest(best, ev)
        if target is None:
            return SpecRevision()
        goal_obj = next((o for o in ev.observation.objectives if o.name == target), None)
        if goal_obj is None:
            return SpecRevision()

        # Bind the threshold to NEW evidence. Satisfaction counts hits against everything
        # realized so far, and the parent's own measurement is already among them, so a
        # default rule would be satisfied the moment this objective is created - and the
        # open-refinement cap would then never bind, because a satisfied objective is not an
        # open one. `hits + 1` is what "one more design over the threshold" means.
        rule = SatisfactionRule(kind="metric_in_range", metric=target,
                                min=goal_obj.min, max=goal_obj.max)
        bound = rule.as_objective()
        hits = sum(1 for d in ev.data.metrics(target)
                   if bound is not None and bound.satisfied_by(d.value))
        rule = rule.model_copy(update={"n": hits + 1})

        aim = None
        if self._refinement_aim is None or self._refinement_aim not in spec.aims:
            aim = Aim(statement="refine the best design so far")
            self._refinement_aim = aim.id
        return SpecRevision(
            new_aims=[aim] if aim is not None else [],
            new_objectives=[SpecObjective(
                aim=self._refinement_aim or "",
                statement=f"improve {target} on {best.id}",
                targets=[target],
                parent_node=best.id,
                satisfied_when=rule,
            )],
            rationale=f"{self.name}: refine {best.id} on {target}")

    @staticmethod
    def _weakest(node, ev: SpecEvidence) -> str | None:
        """The bounded objective this node clears by the smallest margin.

        Margin rather than raw value, so objectives on different scales are comparable, and
        bounded only: an unbounded objective has no margin to be close to.
        """
        worst, worst_margin = None, None
        for obj in ev.observation.objectives:
            value = node.metric(obj.name)
            if value is None:
                continue
            if obj.max is not None:
                margin = obj.max - value
            elif obj.min is not None:
                margin = value - obj.min
            else:
                continue
            scale = abs(obj.max if obj.max is not None else obj.min) or 1.0
            normalised = margin / scale
            if worst_margin is None or normalised < worst_margin:
                worst, worst_margin = obj.name, normalised
        return worst

    async def failed(self, spec: Spec, ev: SpecEvidence) -> list[str]:
        """Objectives that no number of further draws could satisfy.

        Only the unproducible ones: no enabled Task reports the metric, so drawing again
        cannot help. Everything else is a matter of more draws, and calling that failure would
        end campaigns that are merely unlucky - which at the one-in-three acceptance rate this
        project has measured would be most of them.
        """
        return self.unproducible(spec, ev)
