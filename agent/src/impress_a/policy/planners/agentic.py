"""Model A's Planner half: node 2 of the four-node loop, split into two bounded steps.

  1. interpret data -> hypothesize     <- `policy/specifiers/agentic.py`
  2. parameterize a workflow           <- here, as `select_tasks -> parameterize`
  3. run the workflow                  <- the executor; never a policy's
  4. analyze the workflow              <- `policy/specifiers/agentic.py`

Node 2 is two questions, not one - *which* Tasks and *with what* - and the old
`_parameterize` answered both in six lines with the tool ids written into them:
`params={"mock_generate": ..., "mock_design": ...}` on every campaign, including a real
six-stage one where those keys name nothing in the graph. That is backlog H3, and splitting
the node is what makes the second question a step with its own input, output and test.

**What is shared with model D, and why that is not a confound.** Chain resolution and typed
port wiring come from `ThresholdPlanner`, by composition. Those are *correctness*: which tool
produces the artifact another consumes, and which port it arrives on. Two implementations would
be two things to keep in step, and the one that already exists was wrong once - it planned the
minimal chain for one objective and produced a child nobody could compare. The four-arm
experiment's one-variable claim is about decisions, not about whether a graph is wired
correctly; an arm that wired it differently would be a different engine, not a different
reasoner.

**What is model A's own.** Breadth and the parameter vector, both from the strategy node 1
chose:

| | explore | exploit |
|---|---|---|
| lineages | 3 | 2 |
| quality knobs | 83% of range | 39% of range |
| diversity knobs | 35% of range | 5% of range |

Those are the numbers `FourNodePolicy` hardcoded - `diffusion_steps` 170 vs 90 on a 20-200
range, `temperature` 0.35 vs 0.05 on 0-1 - expressed against each tool's own declared range
instead, so they mean the same thing on a chain nobody wrote them for. Breadth knobs and `seed`
are left alone for the reasons in `_knobs.py`.

That makes A **distinguishable from D rather than different in kind**: it sets quality from the
strategy where D escalates it stepwise from the default, it draws its exploring cycles *harder*
than its exploiting ones, and it moves diversity at all, which D never does. The experiment
pre-registers A ~ D as its only positive control for an uncontrolled variable, so each
difference is named here and nowhere else.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ...core.decision import ValidationFailure
from ...core.spec import Spec, Stage
from ...core.toolkit import TaskCard
from .. import reasoning
from ..planner import BasePlanner, PlanningContext
from ._knobs import at_fraction, kind_of, tunable
from .explicit import ThresholdPlanner

#: Node 2a's declared output.
SELECTION_SCHEMA = {
    "strategy": "one of: explore | exploit",
    "lineages": "int, how many independent chains to draw this cycle",
    "rationale": "one sentence",
}

#: strategy -> (lineages, quality fraction, diversity fraction).
#:
#: Not invented: these are `FourNodePolicy`'s own shipped numbers converted to fractions of a
#: declared range, which is the only form in which they survive a chain they were not written
#: for. `diffusion_steps` 170 on rfd3's 20-200 range is 0.83; 90 is 0.39. `temperature` 0.35
#: on 0-1 is 0.35; 0.05 is 0.05. Replicas 3 and 2 are unchanged.
#:
#: Note what that preserves, deliberately: model A computes the EXPLORING draw harder than the
#: exploiting one - "front empty: sample harder" - where D escalates quality upward on each
#: refinement. One of those is wrong, and which is exactly the kind of thing the four-arm
#: comparison exists to measure, so A keeps its own rule rather than being quietly corrected
#: into D.
PROFILES = {"explore": (3, 0.83, 0.35), "exploit": (2, 0.39, 0.05)}


def _a_strategy_and_a_count(raw: dict[str, Any]) -> None:
    """Node 2a's domain check, run inside the bounded retry so a model is told the options."""
    strategy = str(raw.get("strategy", "")).strip().lower()
    if strategy not in PROFILES:
        raise ValueError(f"strategy {strategy!r} is not one of {sorted(PROFILES)}")
    lineages = int(raw["lineages"])        # a non-numeric reply raises, which is a rejection
    if lineages < 1:
        raise ValueError(f"lineages must be at least 1, got {lineages}")


def _last(a: Any, b: Any) -> Any:
    return b


class PlanState(TypedDict, total=False):
    spec: Annotated[Any, _last]
    ctx: Annotated[Any, _last]
    strategy: Annotated[str, _last]
    lineages: Annotated[int, _last]
    rationale: Annotated[str, _last]
    stage: Annotated[Any, _last]


class AgenticPlanner(BasePlanner):
    """`select_tasks -> parameterize`, compiled as a LangGraph, with a real model seam."""

    name = "agentic-plan"

    #: Node names, in order. With `AgenticSpecifier.NODES` this is the four the specification
    #: asks for and the module docstring described while two were registered (backlog H1).
    NODES = ("select_tasks", "parameterize")

    def __init__(self, stages: list[str] | None = None, reasoner: Any = None,
                 sink: Any = None, max_lineages: int = 4) -> None:
        self.reasoner = reasoner
        self.sink = sink
        #: A planner's own ceiling on breadth, beside the campaign's `replicas` cap. The cap
        #: is the campaign's call and binds in the executor; this stops a model's own number
        #: being the thing that asks for sixty lineages.
        self.max_lineages = max(1, max_lineages)
        self._mechanics = ThresholdPlanner(stages=stages)
        self.graph = self._build()

    @property
    def stages(self) -> list[str]:
        """The campaign's chain. Read by `test_the_campaigns_chain_reaches_the_policy`."""
        return self._mechanics.stages

    # -- node 2a: which Tasks, and how many lineages -------------------------
    async def _select_tasks(self, state: PlanState) -> PlanState:
        spec: Spec = state["spec"]
        ctx: PlanningContext = state["ctx"]
        if self.reasoner is not None:
            try:
                raw = await reasoning.ask(
                    self.reasoner, "select_tasks", self._prompt(spec, ctx),
                    SELECTION_SCHEMA, required=("strategy", "lineages"),
                    validate=_a_strategy_and_a_count, sink=self.sink, cycle=ctx.cycle)
                return {"strategy": str(raw["strategy"]).strip().lower(),
                        "lineages": max(1, min(self.max_lineages, int(raw["lineages"]))),
                        "rationale": str(raw.get("rationale", ""))}
            except reasoning.NodeRefused as refused:
                reasoning.degraded(self.sink, "select_tasks", ctx.cycle, str(refused),
                                   "rule cascade")
        return self._select_by_rule(spec, ctx)

    def _select_by_rule(self, spec: Spec, ctx: PlanningContext) -> PlanState:
        """Refine when the Spec says to, explore otherwise.

        Reads the Spec rather than the front, which is the difference the role split buys: a
        refinement objective carries the node to improve on, so "is this an exploit cycle" is
        a question about what was specified rather than a guess from the population.
        """
        refining = any(o.parent_node for o in spec.ready())
        strategy = "exploit" if refining else "explore"
        lineages = min(self.max_lineages, PROFILES[strategy][0])
        return {"strategy": strategy, "lineages": lineages,
                "rationale": (f"{strategy}: "
                              + ("the Spec names a design to refine" if refining
                                 else "no refinement objective is open"))}

    # -- node 2b: with what parameters ---------------------------------------
    async def _parameterize(self, state: PlanState) -> PlanState:
        spec: Spec = state["spec"]
        ctx: PlanningContext = state["ctx"]
        strategy = state.get("strategy", "explore")
        lineages = int(state.get("lineages") or PROFILES[strategy][0])

        stage = await self._mechanics.plan(spec, ctx, lineages=lineages)
        if stage is None:
            return {"stage": None}

        _, quality, diversity = PROFILES[strategy]
        view = ctx.observation.toolkit
        for task in stage.tasks:
            card = view.tools.get(task.tool) if view else None
            if card is None:
                continue
            # The planner's own values, merged UNDER anything already asked for: the
            # mechanics' refinement escalation is a decision too, and a second node
            # overwriting the first silently would make the first untestable.
            task.params = {**self._knobs(card, quality, diversity), **task.params}
        stage.rationale = (f"{self.name}: {strategy} over {lineages} lineage(s)"
                           f" - {state.get('rationale', '')}")
        return {"stage": stage}

    @staticmethod
    def _knobs(card: TaskCard, quality: float, diversity: float) -> dict[str, Any]:
        """Each tunable parameter set to a fraction of its OWN declared range.

        A fraction rather than a value is the whole point: `FourNodePolicy` asked for
        `diffusion_steps: 170`, which is 83% of the way up rfd3's range, exactly 170 on a tool
        that happens to accept it, and a gate-3 rejection on one that does not.
        """
        out: dict[str, Any] = {}
        for name, param in card.parameters.items():
            if not tunable(param, card.frozen, name):
                continue
            kind = kind_of(param)
            fraction = quality if kind == "quality" else (
                diversity if kind == "diversity" else None)
            if fraction is None:
                continue
            value = at_fraction(param, fraction)
            if value is not None:
                out[name] = value
        return out

    def _prompt(self, spec: Spec, ctx: PlanningContext) -> str:
        """What node 2a is given: the Spec's open objectives and what the Toolkit offers.

        The tool list is the campaign's enabled chain, never the whole registry - a real
        campaign told the mock toolkit was available is how an arm executes mocks on a GPU
        allocation, which the four-arm design names as one of its two dangerous failures.
        """
        obs = ctx.observation
        return (
            "You are the Planner of an autonomous protein-design campaign. Choose how wide to "
            "draw this cycle; the chain itself is fixed by what the objectives need.\n"
            f"GOAL: {obs.goal}\nCYCLE: {ctx.cycle}\n"
            f"READY OBJECTIVES: {[o.statement for o in spec.ready()]}\n"
            f"REFINING: {[o.parent_node for o in spec.ready() if o.parent_node]}\n"
            f"CHAIN: {self.stages}\n"
            f"IN FLIGHT: {len(ctx.in_flight)}\n"
            f"BUDGET REMAINING: {({d: obs.budget.remaining(d) for d in obs.budget.limits})}\n"
            f"MAX LINEAGES: {self.max_lineages}\n"
            + (f"LAST REJECTION: {ctx.last_rejection.gate}: {ctx.last_rejection.reason}\n"
               if ctx.last_rejection else "")
        )

    def _build(self):
        g = StateGraph(PlanState)
        g.add_node("select_tasks", self._select_tasks)
        g.add_node("parameterize", self._parameterize)
        g.add_edge(START, "select_tasks")
        g.add_edge("select_tasks", "parameterize")
        g.add_edge("parameterize", END)
        return g.compile()

    # -- Planner -------------------------------------------------------------
    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        state = await self.graph.ainvoke({"spec": spec, "ctx": ctx})
        if self.sink:
            self.sink("decisions", {"policy": self.name, "cycle": ctx.cycle,
                                    "strategy": state.get("strategy"),
                                    "lineages": state.get("lineages"),
                                    "rationale": state.get("rationale")})
        return state.get("stage")

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """Shrink breadth on contention, through the same mechanics as D.

        Not a difference worth having: a rejection answered by truncating the chain is what
        took the only producer of two of four objectives off job 22675512, and an arm that
        did it would be measured on a graph that could not win rather than on its reasoning.
        """
        return await self._mechanics.replan(stage, rejection, spec, ctx)


__all__ = ["PROFILES", "SELECTION_SCHEMA", "AgenticPlanner"]
