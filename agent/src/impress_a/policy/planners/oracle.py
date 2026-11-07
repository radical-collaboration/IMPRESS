"""Model B's Planner half: one structured call per planning round.

The other half of `DECISION_SCHEMA`. This one answers in the engine's vocabulary - tools,
breadth, parameters - and never in the Spec's: it does not get to decide what the campaign is
for, which is what makes the two halves separately attributable.

**It chooses, it does not invent.** The reply names tools from the campaign's enabled chain and
parameters the Toolkit declares, each checked against its own `ParamCard` range before the
Stage is built. A model naming a tool the campaign never enabled is the mock-chain-on-a-GPU
failure in its most direct form, and a parameter outside its declared range is a gate-3
rejection one round trip later - so both are rejected inside the bounded retry, where the model
is told what the options were.

**The chain's wiring is `ThresholdPlanner`'s.** Which port an artifact arrives on is
correctness, not strategy, and a model re-deciding it would be measured on whether it wired a
graph rather than on how it steered a campaign.

**`on_rejected` does not truncate.** The shipped oracle answered a budget rejection by dropping
the last stage, which took `boltz_predict` - the only producer of two of four objectives - off
job 22675512's chain, and the admitted graph recorded `rejected: null`. Breadth shrinks instead,
through the same mechanics as model D.
"""
from __future__ import annotations

from typing import Any

from ...core.decision import ValidationFailure
from ...core.spec import Spec, Stage
from .. import reasoning
from ..planner import BasePlanner, PlanningContext
from ._knobs import kind_of, tunable
from .explicit import ThresholdPlanner

#: What one Stage decision looks like.
STAGE_SCHEMA = {
    "stages": "ordered list of tool ids to run, from the chain given below",
    "replicas": "int, how many independent lineages to draw this cycle",
    "params": "dict of tool_id -> {parameter: value}; only declared parameters, in range",
    "rationale": "one sentence explaining the choice",
}
#: WHICH design a cycle refines is deliberately NOT asked here. It is `SpecObjective.
#: parent_node` - a Spec-level decision the Specifier half makes and the Reviewer checks
#: coverage against - and `ThresholdPlanner` reads it off the ready objectives. Asking both
#: halves would have them deciding the same thing, which is exactly what splitting
#: `DECISION_SCHEMA` was for: the two schemas share `rationale` and nothing else, and a test
#: asserts that.


class OraclePlanner(BasePlanner):
    """One `STAGE_SCHEMA` call per planning round, with a declared fallback."""

    name = "oracle-plan"

    def __init__(self, stages: list[str] | None = None, oracle: Any = None,
                 fallback: Any = None, sink: Any = None, max_lineages: int = 4) -> None:
        self.oracle = oracle
        self._mechanics = ThresholdPlanner(stages=stages)
        #: Mandatory for a real run (Part A risk R7). Model D's planner, so a campaign whose
        #: endpoint is down keeps planning rather than holding an allocation idle.
        self.fallback = fallback or self._mechanics
        self.sink = sink
        self.max_lineages = max(1, max_lineages)
        self.degraded = False

    @property
    def stages(self) -> list[str]:
        return self._mechanics.stages

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        if self.oracle is None:
            return await self.fallback.plan(spec, ctx)
        view = ctx.observation.toolkit
        enabled = [t for t in self._mechanics.stages if view and t in view]
        try:
            raw = await reasoning.ask(
                self.oracle, "stage", self._prompt(spec, ctx, enabled), STAGE_SCHEMA,
                required=("stages", "replicas"),
                validate=self._validator(enabled, ctx), sink=self.sink, cycle=ctx.cycle)
        except reasoning.NodeRefused as refused:
            self.degraded = True
            reasoning.degraded(self.sink, "stage", ctx.cycle, str(refused),
                               getattr(self.fallback, "name", "?"))
            return await self.fallback.plan(spec, ctx)
        return await self._to_stage(raw, spec, ctx)

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """Shrink breadth on contention; give up on anything structural.

        Through model D's mechanics rather than by asking the model again. A rejection at
        `budget` or `interlock` is a property of the moment, not of the reasoning, and
        spending a round trip to be told to ask for less is spending a decision to learn
        arithmetic. Everything else ends the attempt, which `_deploy` bounds anyway.
        """
        return await self._mechanics.replan(stage, rejection, spec, ctx)

    def _validator(self, enabled: list[str], ctx: PlanningContext) -> Any:
        """Every reference checked against the live state, inside the bounded retry."""
        view = ctx.observation.toolkit
        limit = self.max_lineages

        def check(raw: dict[str, Any]) -> None:
            stages = raw.get("stages")
            if not isinstance(stages, list) or not stages:
                raise ValueError("stages must be a non-empty list of tool ids")
            if bad := [t for t in stages if t not in enabled]:
                raise ValueError(f"tool(s) {bad} are not in this campaign's chain {enabled}")
            replicas = int(raw["replicas"])
            if replicas < 1:
                raise ValueError(f"replicas must be at least 1, got {replicas}")
            if replicas > limit:
                raise ValueError(f"replicas must be at most {limit}, got {replicas}")
            if "parent_node" in raw:
                raise ValueError(
                    "parent_node is not the Planner's to choose: which design a cycle "
                    "refines is a Spec objective, and this half reads it from there")
            for tool, params in (raw.get("params") or {}).items():
                if tool not in stages:
                    raise ValueError(f"params names {tool!r}, which is not in this stage")
                card = view.tools[tool] if view else None
                for name, value in (params or {}).items():
                    param = (card.parameters if card else {}).get(name)
                    if param is None:
                        raise ValueError(
                            f"{tool} declares no parameter {name!r}; it declares "
                            f"{sorted(card.parameters) if card else []}")
                    if name in (card.frozen if card else {}):
                        raise ValueError(
                            f"{tool}.{name} is frozen: {card.frozen[name]}")
                    if param.min is not None and float(value) < float(param.min):
                        raise ValueError(f"{tool}.{name}={value} is below {param.min}")
                    if param.max is not None and float(value) > float(param.max):
                        raise ValueError(f"{tool}.{name}={value} is above {param.max}")

        return check

    async def _to_stage(self, raw: dict[str, Any], spec: Spec,
                        ctx: PlanningContext) -> Stage | None:
        """The reply as a Stage, wired by model D's mechanics."""
        # Per call, never assigned back: a reply naming a subset must not narrow the
        # campaign's chain for the cycles that follow, including the ones its own fallback
        # plans. See `ThresholdPlanner.plan`.
        stage = await self._mechanics.plan(
            spec, ctx, chain=list(raw["stages"]),
            lineages=max(1, min(self.max_lineages, int(raw["replicas"]))))
        if stage is None:
            return None
        params = raw.get("params") or {}
        for task in stage.tasks:
            if extra := params.get(task.tool):
                task.params = {**task.params, **extra}
        # `stage.parent_node` is whatever the mechanics read off the Spec's ready objectives.
        # Not overridden from the reply: a Planner that chose a different design to refine
        # would be answering the Specifier's question, and the Reviewer checks coverage
        # against the applied Spec rather than against the Stage's claim about it.
        stage.rationale = f"{self.name}: {raw.get('rationale', '')}"
        return stage

    def _prompt(self, spec: Spec, ctx: PlanningContext, enabled: list[str]) -> str:
        """What the model is given: the chain, and each tool's own declared parameters.

        The parameter detail is the part `obs.available_tools` could not carry - it was bare
        ids, so a model could not see a range, could not know which parameters were frozen,
        and either guessed or hardcoded, which is backlog H3. Narrowed to the enabled chain,
        because telling a real campaign the mock toolkit is available is how an arm ends up
        executing mocks on a GPU allocation.
        """
        obs = ctx.observation
        view = obs.toolkit
        tools = {}
        for tool in enabled:
            card = view.tools[tool] if view else None
            if card is None:
                continue
            tools[tool] = {
                "outputs": sorted(card.outputs),
                "metrics": list(card.metrics),
                "parameters": {
                    name: {"type": p.type, "default": p.default, "min": p.min, "max": p.max,
                           "trades": p.trades, "kind": kind_of(p)}
                    for name, p in card.parameters.items()
                    if tunable(p, card.frozen, name)},
            }
        return (
            "You are the Planner of an autonomous protein-design campaign. Choose which tools "
            "to run, how wide to draw, and with what parameters. Do NOT decide what the "
            "campaign is for - another role does that.\n"
            f"GOAL: {obs.goal}\nCYCLE: {ctx.cycle}\n"
            f"READY OBJECTIVES: {[o.statement for o in spec.ready()]}\n"
            f"REFINING: {[o.parent_node for o in spec.ready() if o.parent_node]}\n"
            f"CHAIN (use these ids, in this order): {enabled}\n"
            f"TOOLS: {tools}\n"
            f"MAX REPLICAS: {self.max_lineages}\n"
            f"IN FLIGHT: {len(ctx.in_flight)}\n"
            f"BUDGET REMAINING: {({d: obs.budget.remaining(d) for d in obs.budget.limits})}\n"
            + (f"LAST REJECTION: {ctx.last_rejection.gate}: {ctx.last_rejection.reason}\n"
               if ctx.last_rejection else "")
            + "A parameter's `kind` says what raising it buys: quality computes the same draw "
              "harder, diversity changes the draw at the same cost, breadth costs more per "
              "draw. Leave a parameter out to keep its default."
        )


__all__ = ["STAGE_SCHEMA", "OraclePlanner"]
