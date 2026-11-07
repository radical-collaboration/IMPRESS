"""Model A's Specifier half: nodes 1 and 4 of the four-node loop.

The specification's four nodes (`planning/phase1-partB-architecture/02-control-models.md`
section 2) are:

  1. interpret data -> hypothesize     <- here
  2. parameterize a workflow           <- `policy/planners/agentic.py`
  3. run the workflow                  <- the executor; never a policy's
  4. analyze the workflow              <- here, as the revision the analysis implies

Backlog H1 recorded that `FourNodePolicy._build()` registered **two** nodes while its own
module docstring described four, and that `self.reasoner` was stored and never read. The split
into halves is what makes four honest: two nodes per half, each a bounded step with a declared
input and output, and the model seam actually called through `policy/reasoning.ask`.

**Why node 4 lives with the Specifier.** "Analyze the workflow" is not a report - it is the
step that decides what the campaign should now be trying to achieve, which is the Specifier's
question by definition. The old `interpret()` appended a sentence to a list nobody read; here
the analysis becomes a `SpecRevision`, which is a thing the executor applies and provenance
records.

**Where A differs from D, stated rather than discovered.** `tests/.../test_campaign.py` has
model A passing only a termination test, and the four-arm design pre-registers A ~ D as its
one positive control for an uncontrolled variable - so the differences have to be few and
named:

* A **retires** an objective no enabled Task can produce, by DELETING it. D names it and
  leaves it OPEN, so D's Spec can never complete while such an objective exists. Both are
  defensible; they are not the same campaign. On the real six-stage chain every declared
  objective is producible, so this branch does not fire in the experiment.
* A respecifies off **population health** as well as the front: a majority of suspect
  candidates means the region is unreliable, which is a reason to keep exploring rather than
  to refine the best of a bad set. D looks only at whether the front is empty.

The refinement objective itself is built by `ThresholdSpecifier`, by composition. Two
implementations of "bind the threshold to new evidence" would be two places for the bug that
one already fixed - a refinement objective satisfied by its own parent's measurement - and the
mechanics of writing a revision are not what distinguishes a control model.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ...core.goal import Goal
from ...core.spec import ObjectiveStatus, Spec, SpecRevision
from .. import reasoning
from ..specifier import BaseSpecifier, SpecEvidence
from .explicit import ThresholdSpecifier

#: Node 1's declared output. Prose values: the schema is handed to the client as well, which
#: can use it as a schema, and inlined in the prompt for one that cannot.
HYPOTHESIS_SCHEMA = {
    "strategy": "one of: explore | exploit | retire",
    "hypothesis": "one sentence naming what is limiting the campaign right now",
}

STRATEGIES = ("explore", "exploit", "retire")


def _one_of_the_strategies(raw: dict[str, Any]) -> None:
    """Node 1's domain check, run inside the bounded retry so a model is told the options."""
    strategy = str(raw.get("strategy", "")).strip().lower()
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy {strategy!r} is not one of {STRATEGIES}")


def _last(a: Any, b: Any) -> Any:
    return b


class SpecState(TypedDict, total=False):
    spec: Annotated[Any, _last]
    evidence: Annotated[Any, _last]
    strategy: Annotated[str, _last]
    hypothesis: Annotated[str, _last]
    revision: Annotated[Any, _last]


class AgenticSpecifier(BaseSpecifier):
    """`hypothesize -> analyze`, compiled as a LangGraph, with a real model seam."""

    name = "agentic-spec"

    #: Node names, in order. Read by `tests/test_reasoner_registry.py` together with the
    #: planner's, because "model A has four nodes" is a claim about the pair.
    NODES = ("hypothesize", "analyze")

    def __init__(self, reasoner: Any = None, sink: Any = None,
                 max_refinements: int = 1) -> None:
        #: None means the deterministic cascade below, which is what `--model A` runs until a
        #: client is attached. Not a silent default: `impress-a models` reports A's
        #: `llm_calls` as 0 for exactly this reason, and a campaign that *has* a reasoner and
        #: cannot reach it records a `reasoner_degraded` transition per node.
        self.reasoner = reasoner
        self.sink = sink
        self.notes: list[str] = []
        self._refine = ThresholdSpecifier(max_refinements=max_refinements)
        self.graph = self._build()

    # -- node 1: interpret data -> hypothesize -------------------------------
    async def _hypothesize(self, state: SpecState) -> SpecState:
        ev: SpecEvidence = state["evidence"]
        spec: Spec = state["spec"]
        if self.reasoner is not None:
            try:
                raw = await reasoning.ask(
                    self.reasoner, "hypothesize", self._prompt(spec, ev),
                    HYPOTHESIS_SCHEMA, required=("strategy", "hypothesis"),
                    validate=_one_of_the_strategies, sink=self.sink, cycle=ev.cycle)
                return {"strategy": str(raw["strategy"]).strip().lower(),
                        "hypothesis": str(raw["hypothesis"])}
            except reasoning.NodeRefused as refused:
                reasoning.degraded(self.sink, "hypothesize", ev.cycle, str(refused),
                                   "rule cascade")
        return self._hypothesize_by_rule(spec, ev)

    def _hypothesize_by_rule(self, spec: Spec, ev: SpecEvidence) -> SpecState:
        """The deterministic cascade, and the fallback when a model will not answer.

        Reads the observation only - no tool, no registry - so it holds for a mock campaign
        and a real one alike.
        """
        obs = ev.observation
        if self._refine.unproducible(spec, ev):
            return {"strategy": "retire",
                    "hypothesis": "the enabled Toolkit cannot measure every objective"}
        if not obs.pareto_front:
            return {"strategy": "explore",
                    "hypothesis": "front empty: designability is limiting, sample harder"}
        if obs.population.suspect > obs.population.live:
            return {"strategy": "explore",
                    "hypothesis": "most candidates suspect: this region is unreliable"}
        return {"strategy": "exploit",
                "hypothesis": f"front has {len(obs.pareto_front)}: refine around the best"}

    # -- node 4: analyze the workflow -> a revision --------------------------
    async def _analyze(self, state: SpecState) -> SpecState:
        ev: SpecEvidence = state["evidence"]
        spec: Spec = state["spec"]
        strategy = state.get("strategy", "explore")
        note = f"cycle {ev.cycle}: {strategy} - {state.get('hypothesis', '')}"
        self.notes.append(note)

        if strategy == "retire":
            dead = self._refine.unproducible(spec, ev)
            if dead:
                return {"revision": SpecRevision(
                    deleted=list(dead),
                    rationale=f"{self.name}: retired {len(dead)} unproducible objective(s)")}
            return {"revision": SpecRevision()}
        if strategy == "exploit":
            return {"revision": await self._refine.revise(spec, ev)}
        # Explore: keep drawing against the Spec as it stands. Adding objectives from the
        # absence of evidence is inventing work, which is the one thing a Specifier must not
        # do - every objective it writes becomes something the Reviewer demands be covered.
        return {"revision": SpecRevision()}

    def _prompt(self, spec: Spec, ev: SpecEvidence) -> str:
        """What node 1 is given. Bounded on purpose - the front and the counts, not the tree.

        `toolkit.ids` rather than every card: this node chooses a *strategy*, and the tool
        detail belongs to the planner half that chooses tasks. Narrowed to the enabled set
        either way, because telling a real campaign that the mock toolkit is available is how
        an arm ends up executing mocks on a GPU allocation.
        """
        obs = ev.observation
        front = [{"id": n.id, **{o.name: n.metric(o.name) for o in obs.objectives}}
                 for n in obs.pareto_front]
        done = sum(1 for o in spec.objectives.values()
                   if o.status is ObjectiveStatus.SATISFIED)
        return (
            "You are the Specifier of an autonomous protein-design campaign. Decide what the "
            "campaign should now be trying to achieve - not which tool to run.\n"
            f"GOAL: {obs.goal}\nCYCLE: {obs.cycle}\n"
            f"OPEN OBJECTIVES: {[o.statement for o in spec.open_objectives()]}\n"
            f"SATISFIED: {done}\n"
            f"PARETO FRONT ({len(front)}): {front}\n"
            f"POPULATION: {obs.population.model_dump()}\n"
            f"MEASURABLE HERE: {sorted(obs.toolkit.ids) if obs.toolkit else []}\n"
            "explore = keep drawing; exploit = refine the best design; "
            "retire = an objective cannot be measured here at all."
        )

    def _build(self):
        g = StateGraph(SpecState)
        g.add_node("hypothesize", self._hypothesize)
        g.add_node("analyze", self._analyze)
        g.add_edge(START, "hypothesize")
        g.add_edge("hypothesize", "analyze")
        g.add_edge("analyze", END)
        return g.compile()

    # -- Specifier -----------------------------------------------------------
    async def initial_spec(self, goal: Goal) -> Spec:
        """Delegated, deliberately.

        `Goal -> Spec` for the declared objectives is a transcription, not a judgement: one
        objective per declared metric, bounded ones getting a threshold rule and unbounded
        ones a measurement rule. A model asked to do it could only get it wrong, and the
        four-arm comparison needs every arm to start from the same objectives - an arm whose
        Specifier emits a different set is void for the primary endpoint.
        """
        return await self._refine.initial_spec(goal)

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        state = await self.graph.ainvoke({"spec": spec, "evidence": ev})
        if self.sink:
            self.sink("decisions", {"policy": self.name, "cycle": ev.cycle,
                                    "strategy": state.get("strategy"),
                                    "hypothesis": state.get("hypothesis")})
        return state.get("revision") or SpecRevision()


__all__ = ["HYPOTHESIS_SCHEMA", "STRATEGIES", "AgenticSpecifier"]
