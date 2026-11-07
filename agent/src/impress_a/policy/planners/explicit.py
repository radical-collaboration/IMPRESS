"""Model D's Planner half: deterministic Objective -> Task, and the scientific control.

Three things it does that `ThresholdPolicy` structurally could not, and which are the reason
the Planner exists as a role:

**It selects Tasks by output type, not by a hardcoded chain position.** An objective finds its
producer through `ToolkitView.reporting(metric)`, and that producer's required input ports find
*their* producers through `ArtifactType.unifies_with` - the same unification rule gate 1 and the
composer use, so a Planner, a validator and a composer agree about what satisfies what. The
chain that comes out is the subset of the campaign's enabled tools that the ready objectives
actually need, ordered by the campaign's own declaration.

**It attributes every Task to the objectives it serves - at lineage granularity, which is a
property of the engine and not a shortcut.** `_absorb` produces exactly one `DesignNode` per
replica lineage, with that lineage's whole chain merged into one candidate's properties, and
the front ranks candidates. So a lineage's tasks are not severally responsible for separate
objectives: they jointly produce one design that is judged on all of them, and
`rfd3_design` - which reports no campaign objective at all - is indispensable to every one.
Attributing a tail task narrowly to the objective whose metric it happens to report was the
first version here, and it was wrong in a way that only a refinement exposed: planning the
minimal chain for one objective is what made the child incomparable, below.

What the granularity costs is recorded rather than hidden: deleting one objective can no
longer orphan a single task, only a whole lineage once *every* objective the Stage serves is
DELETED. That is still decidable, which is the property `TaskMapping.objectives` being a list
exists for.

**It varies a real tool's parameters.** This is backlog H3, and `ThresholdPolicy` is the record
of what its absence looked like: `params={"mock_generate": {...}, "mock_design": {...}}`,
hardcoded to two mock tool ids, on every arm. Against the Delta chain those keys name tools
that are not in the graph, the composer dropped them without a word, and no real tool's
parameter has ever been varied by any reasoner. So the claim "the four models differ in
decision quality" had no parameter axis at all.

**How a parameter is chosen, and why from prose.** The only thing a spec says about what
raising a parameter buys is its `trades` sentence, and `ParamCard` carries it for exactly this.
Read across every shipped tool, that prose uses a small and consistent vocabulary:

    quality vs wall-clock | accuracy vs wall-clock | convergence vs cpu-hours
    coverage vs GPU-hours | sampling vs cpu-hours  | diversity vs recovery
    candidates per pass   | samples per call       | per-lineage draw

The first group is what a refinement wants: more of the same draw, computed harder. The second
is breadth, and breadth is deliberately NOT this planner's parameter axis - it comes from
`replicas` and from the internal sampling the specs already set to 8 where the adapter selects
from the ensemble. `rfd3_design`'s own spec says `num_designs` stays at 1 because its adapter
still keeps index 0, so a planner that escalated "coverage" would pay N times for one design.
The third group is identity, never tuned: a planner that moved `seed` would break the
independence of the lineages it is being credited for.

So: **exploring changes no parameter, refining escalates the quality knobs.** A rule-driven arm
has no business inventing a parameter vector from no evidence, and it is the same explore/exploit
cascade `ThresholdPolicy` expressed - with the tool ids read from the Toolkit instead of being
written in this file.

**`replan` shrinks breadth and never the chain.** A budget rejection says "not right now",
not "measure less": truncating the tail is what took `boltz_predict` and the only producer of
two of four objectives off job 22675512's chain. Dropping a lineage removes a whole independent
chain and so cannot change what the Stage can measure.
"""
from __future__ import annotations

import math
from typing import Any

from ...core.decision import ValidationFailure
from ...core.spec import Deferral, Spec, SpecObjective, Stage, TaskMapping
from ...core.toolkit import ParamCard, TaskCard, ToolkitView
from ..explicit import SELF_CONSISTENCY
from ..planner import BasePlanner, PlanningContext

#: `trades` words meaning "raising this computes the same draw harder". The refinement axis.
QUALITY_TERMS = ("quality", "accuracy", "convergence")

#: `trades` words meaning "raising this draws more". Deliberately not tuned here: breadth is
#: `replicas` plus the internal sampling the specs already declare, and an adapter that keeps
#: index 0 turns a raise into an N-times bill for one design (`rfd3_design`'s own comment).
BREADTH_TERMS = ("coverage", "sampling", "samples", "candidates", "diversity", "passes")

#: How many escalation steps span a parameter's declared headroom. Four, so a refinement
#: campaign reaches the declared maximum in four refinements rather than in one jump - the
#: declared max is a limit, not a target, and arriving there immediately would leave the
#: planner with nothing to escalate and no record of which step helped.
ESCALATION_STEPS = 4


class ThresholdPlanner(BasePlanner):
    """Type-driven task selection, deferral for the unproducible, breadth from `replicas`."""

    name = "threshold-plan"

    def __init__(self, stages: list[str] | None = None, base_replicas: int = 2,
                 escalation_steps: int = ESCALATION_STEPS) -> None:
        #: The campaign's enabled tools, in the campaign's order. A Planner may use a SUBSET -
        #: whatever the ready objectives need - but never a tool the campaign did not enable,
        #: which is the mock-chain-on-a-GPU failure in another form.
        #:
        #: Falling back to the mock chain when a campaign names none is deliberate, and the
        #: alternative is worse than it looks: "every tool in the ToolkitView" would hand a
        #: campaign the whole registry, which holds `mock_noodle` - a tool that completes
        #: successfully, reports a confident `designability` and produces no secondary
        #: structure - beside the real toolkits. A chain nobody declared should be the harmless
        #: one, so this matches `ThresholdPolicy`'s own default rather than inventing a wider
        #: one, and `cli._check_ligand_smiles` plus phase 10's gate 6 are what catch a real
        #: campaign that forgot to declare its stages.
        self.stages = list(stages or SELF_CONSISTENCY)
        self.base_replicas = max(1, base_replicas)
        self.escalation_steps = max(1, escalation_steps)
        #: How many refinement Stages this planner has emitted. The escalation index.
        self.refinements = 0

    # -- planning ------------------------------------------------------------
    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        ready = spec.ready()
        if not ready:
            return None
        view = ctx.observation.toolkit
        if view is None or not view.tools:
            return None

        enabled = [t for t in self.stages if t in view]
        if not enabled:
            return None
        ranked = [o.name for o in ctx.observation.objectives]
        chain, wiring, deferrals = self._resolve(ready, ranked, enabled, view)
        if not chain:
            # Nothing is producible. A Stage of pure deferrals has no runnable task, so say
            # so by planning nothing rather than by submitting a Stage the executor must
            # refuse - the Specifier's `failed()` is what closes objectives like these.
            return None

        parent = next((o.parent_node for o in ready if o.parent_node), None)
        refining = parent is not None
        if refining:
            self.refinements += 1

        served = sorted(o.id for o in ready)
        tasks: list[TaskMapping] = []
        for lineage in range(self.base_replicas):
            ids = {tool: f"l{lineage}_s{i}_{tool}" for i, tool in enumerate(chain)}
            for tool in chain:
                tasks.append(TaskMapping(
                    task_id=ids[tool],
                    objectives=list(served),
                    tool=tool,
                    params=self._params(view.tools[tool], refining),
                    inputs={port: f"{ids[src]}.{out}"
                            for port, (src, out) in wiring.get(tool, {}).items()},
                    lineage=lineage))

        return Stage(
            spec_generation=spec.generation,
            tasks=tasks,
            deferrals=deferrals,
            cancels=list(ctx.orphans),
            parent_node=parent,
            rationale=(f"{self.name}: refine {parent} (escalation {self.refinements})"
                       if refining else
                       f"{self.name}: explore {len(ready)} ready objective(s) "
                       f"over {self.base_replicas} lineage(s)"))

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """Shrink breadth on contention; give up on anything structural.

        `budget` and `interlock` are the two gates whose verdict depends on what *other* work
        is consuming - the interlock's provisional cap is 10% of the budget and one instance in
        flight - so both are answerable by asking for less at once. Everything else is a
        property of the graph, and a rule-driven planner that reshaped a graph a gate called
        wrong would be guessing.
        """
        if rejection.gate not in ("budget", "interlock"):
            return None
        if stage.lineages <= 1:
            return None
        drop = max(t.lineage for t in stage.runs)
        kept = [t for t in stage.tasks if t.lineage != drop]
        return stage.model_copy(update={
            "tasks": kept, "attempt": stage.attempt + 1,
            "id": stage.id, "status": stage.status,
            "rationale": (f"{stage.rationale}; dropped lineage {drop} after "
                          f"{rejection.gate}: {rejection.reason[:80]}")})

    # -- type-driven selection -----------------------------------------------
    def _resolve(self, ready: list[SpecObjective], ranked: list[str], enabled: list[str],
                 view: ToolkitView
                 ) -> tuple[list[str], dict[str, dict[str, tuple[str, str]]], list[Deferral]]:
        """Which tools this Stage needs, how they wire together, and what cannot be planned.

        The chain covers two things, and the second one is not optional. The ready Spec
        objectives are what the Stage is *for*. `ranked` - the campaign's declared objectives -
        is what the node it produces will be *judged on*, and a node missing one of those
        cannot be feasible, so it can never reach the front whatever the science did. The
        executor refuses such a graph outright (backlog A8), and it is right to: planning the
        minimal chain for one refinement objective produced a child measured on `iptm` alone,
        incomparable with every design already on the front, and the refinement was therefore
        unwinnable from the moment it was planned - the same defect as job 22675512's truncated
        chain, reached by the opposite route.

        Returns the chain in the campaign's declared order, `tool -> {port: (src, out_port)}`,
        and one `Deferral` per ready objective no enabled tool can measure. A *campaign*
        objective with no producer gets no Deferral: it is not a Spec objective, so there is
        nothing to defer, and saying so is the Specifier's `unproducible` and the executor's
        refusal.
        """
        order = {tool: i for i, tool in enumerate(enabled)}
        need: set[str] = set()
        wiring: dict[str, dict[str, tuple[str, str]]] = {}
        deferrals: list[Deferral] = []
        planned: set[str] = set()

        for obj in ready:
            for metric in obj.targets:
                tool = self._producer_of(metric, enabled, view)
                if tool is None:
                    deferrals.append(Deferral(
                        objective=obj.id,
                        reason=(f"no enabled task reports {metric!r}; the campaign's "
                                f"{len(enabled)} enabled tool(s) cannot measure it"),
                        waiting_on=[f"a tool reporting {metric}"]))
                    continue
                planned.add(obj.id)
                self._require(tool, enabled, view, order, need, wiring)

        if need:
            for metric in ranked:
                if (tool := self._producer_of(metric, enabled, view)) is not None:
                    self._require(tool, enabled, view, order, need, wiring)

        chain = sorted(need, key=lambda t: order[t])
        # An objective planned on one target is not deferred for another.
        deferrals = [d for d in deferrals if d.objective not in planned]
        return chain, wiring, deferrals

    @staticmethod
    def _producer_of(metric: str, enabled: list[str], view: ToolkitView) -> str | None:
        """The earliest enabled tool declaring `metric`.

        Earliest rather than best: a metric reported by two tools in one chain is reported
        twice, and ADR 0012's one-property-two-sources rule means the later measurement
        supersedes the earlier by name - so choosing the earlier producer never loses the
        later one, while choosing the later could drop the chain that feeds it.
        """
        reporting = {card.id for card in view.reporting(metric)}
        return next((t for t in enabled if t in reporting), None)

    def _require(self, tool: str, enabled: list[str], view: ToolkitView,
                 order: dict[str, int], need: set[str],
                 wiring: dict[str, dict[str, tuple[str, str]]]) -> None:
        """Add `tool` and, recursively, a producer for each of its required input ports."""
        if tool in need:
            return
        need.add(tool)
        card = view.tools[tool]
        ports = wiring.setdefault(tool, {})
        for port in card.inputs.values():
            if not port.required:
                continue
            src = self._source_for(port.type, tool, enabled, view, order)
            if src is None:
                # A root port with no producer in the enabled set. Left unwired on purpose:
                # gate 1 decides whether `Goal.reference_data` satisfies it, and inventing a
                # producer here would be the Planner overruling the validator.
                continue
            src_tool, out_port = src
            ports[port.name] = (src_tool, out_port)
            self._require(src_tool, enabled, view, order, need, wiring)

    @staticmethod
    def _source_for(want: Any, consumer: str, enabled: list[str], view: ToolkitView,
                    order: dict[str, int]) -> tuple[str, str] | None:
        """The nearest enabled tool BEFORE `consumer` whose output satisfies `want`.

        Nearest-preceding, which is the rule `Composer.compose` already applies to a linear
        chain, so a Stage this planner wires explicitly and a chain the composer wires by
        position describe the same graph. Restricting to tools declared earlier is what keeps
        the result acyclic without a topological pass: the campaign's declared order is the
        only ordering either side has.
        """
        limit = order[consumer]
        for tool in sorted((t for t in enabled if order[t] < limit),
                           key=lambda t: -order[t]):
            card = view.tools[tool]
            match = next((name for name, port in card.outputs.items()
                          if port.type.unifies_with(want)), None)
            if match:
                return tool, match
        return None

    # -- the parameter axis (H3) ---------------------------------------------
    def _params(self, card: TaskCard, refining: bool) -> dict[str, Any]:
        """What this planner asks of one tool.

        Empty while exploring, which is not an omission: the campaign's own `params` and the
        spec's declared defaults are the right values for a first draw, and a rule-driven arm
        inventing a parameter vector from no evidence would be noise attributed to a decision.
        """
        if not refining:
            return {}
        out: dict[str, Any] = {}
        for name, param in card.parameters.items():
            if name in card.frozen:
                continue
            value = self._escalate(param)
            if value is not None:
                out[name] = value
        return out

    def _escalate(self, param: ParamCard) -> Any:
        """One step up a quality knob, or None if this parameter is not one.

        `None` for: a frozen name (handled by the caller), a breadth or identity parameter, a
        non-numeric one, a parameter with no declared maximum or no default to move from, and
        one already at its maximum. Each of those is a parameter a raise would either corrupt
        or waste, and saying nothing about it leaves the declared value in force.
        """
        trades = (param.trades or "").lower()
        if not any(term in trades for term in QUALITY_TERMS):
            return None
        if any(term in trades for term in BREADTH_TERMS):
            # A sentence naming both - "sampling vs quality" - is ambiguous, and a planner
            # resolving an ambiguity in a spec by guessing is how a GPU bill doubles.
            return None
        if param.type not in ("int", "float") or param.max is None or param.default is None:
            return None
        try:
            base = float(param.default)
        except (TypeError, ValueError):
            return None
        headroom = float(param.max) - base
        if headroom <= 0:
            return None
        step = headroom / self.escalation_steps
        value = min(float(param.max), base + step * self.refinements)
        if param.type == "int":
            value = int(min(float(param.max), math.ceil(value)))
            return value if value > int(base) else None
        return value if value > base else None


__all__ = ["BREADTH_TERMS", "ESCALATION_STEPS", "QUALITY_TERMS", "ThresholdPlanner"]
