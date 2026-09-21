"""Control model A - the explicit four-node agentic loop, on LangGraph.

The four nodes from the specification, mapped onto the manager's cycle:

  1. Interpret data -> hypothesize      -> decide(), part 1   [this graph]
  2. Parameterize a workflow            -> decide(), part 2   [this graph]
  3. Run the workflow                   -> the MANAGER owns this, not the policy
  4. Analyze the workflow               -> interpret()        [this graph]

Node 3 belongs to the manager. Stating that plainly is what stops the policy reaching
into execution - the separation that lets policies be swapped (Part B doc 02).

LangGraph is used for the loop and state, per the Phase 4 decision. Each node is a
bounded, separately-testable step with a declared input and output, so a campaign's
reasoning is auditable node by node.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..core.decision import (CampaignObservation, ComposeAndRun, Decision,
                             ExperimentIntent, Stop, ValidationFailure)
from .base import BasePolicy

SELF_CONSISTENCY = ["mock_generate", "mock_design", "mock_fold", "mock_score"]


def _last(a: Any, b: Any) -> Any:
    return b


class AgenticState(TypedDict, total=False):
    obs: Annotated[Any, _last]
    hypothesis: Annotated[str, _last]
    strategy: Annotated[str, _last]        # "explore" | "exploit" | "stop"
    intent: Annotated[Any, _last]
    rationale: Annotated[str, _last]


class FourNodePolicy(BasePolicy):
    """Node 1 and 2 compiled as a LangGraph; node 4 is `interpret`."""

    name = "four_node"

    def __init__(self, stages: list[str] | None = None, max_cycles: int = 6,
                 target_front: int = 3, reasoner: Any = None, sink: Any = None):
        self.stages = stages or SELF_CONSISTENCY
        self.max_cycles, self.target_front = max_cycles, target_front
        self.reasoner = reasoner      # optional LLM; None = deterministic rehearsal
        self.sink = sink
        self.notes: list[str] = []
        self.graph = self._build()

    # -- node 1 -------------------------------------------------------------
    def _hypothesize(self, state: AgenticState) -> AgenticState:
        obs: CampaignObservation = state["obs"]
        if obs.cycle >= self.max_cycles:
            return {"strategy": "stop", "hypothesis": f"cycle budget {self.max_cycles} spent"}
        if len(obs.pareto_front) >= self.target_front:
            return {"strategy": "stop", "hypothesis": "front target reached"}
        if obs.budget.exhausted():
            return {"strategy": "stop", "hypothesis": f"budget exhausted {obs.budget.exhausted()}"}
        if not obs.pareto_front:
            return {"strategy": "explore",
                    "hypothesis": "front empty: designability is limiting, sample harder"}
        if obs.population.suspect > obs.population.live:
            return {"strategy": "explore",
                    "hypothesis": "most candidates suspect: current region is unreliable"}
        return {"strategy": "exploit",
                "hypothesis": f"front has {len(obs.pareto_front)}: refine around the best"}

    # -- node 2 -------------------------------------------------------------
    def _parameterize(self, state: AgenticState) -> AgenticState:
        obs: CampaignObservation = state["obs"]
        strat = state.get("strategy", "explore")
        if strat == "stop":
            return {"intent": None, "rationale": state.get("hypothesis", "")}
        exploring = strat == "explore"
        intent = ExperimentIntent(
            goal=obs.goal, stages=self.stages,
            replicas=3 if exploring else 2,
            params={"mock_generate": {"diffusion_steps": 170 if exploring else 90},
                    "mock_design": {"temperature": 0.35 if exploring else 0.05}},
            parent_node=obs.pareto_front[0].id if obs.pareto_front else None)
        return {"intent": intent,
                "rationale": f"{strat}: {state.get('hypothesis','')}"}

    def _build(self):
        g = StateGraph(AgenticState)
        g.add_node("hypothesize", self._hypothesize)
        g.add_node("parameterize", self._parameterize)
        g.add_edge(START, "hypothesize")
        g.add_edge("hypothesize", "parameterize")
        g.add_edge("parameterize", END)
        return g.compile()

    # -- ControlPolicy ------------------------------------------------------
    async def decide(self, obs: CampaignObservation) -> Decision:
        state = await self.graph.ainvoke({"obs": obs})
        if self.sink:
            self.sink("decisions", {"policy": self.name, "cycle": obs.cycle,
                                    "hypothesis": state.get("hypothesis"),
                                    "strategy": state.get("strategy")})
        if state.get("intent") is None:
            return Stop(reason=state.get("hypothesis", "four-node policy stop"))
        return ComposeAndRun(intent=state["intent"], rationale=state.get("rationale", ""))

    # -- node 4 -------------------------------------------------------------
    async def interpret(self, results, obs: CampaignObservation) -> str | None:
        if results is None:
            return None
        gates_ok = results.all_gates_passed
        note = (f"cycle {obs.cycle}: {len(results.per_task)} tasks, "
                f"{'clean' if gates_ok else 'QC issues'}; "
                f"metrics {sorted(results.merged_metrics())}")
        self.notes.append(note)
        return note

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision:
        if failure.gate in ("budget", "interlock") and isinstance(decision, ComposeAndRun) \
                and decision.intent.replicas > 1:
            decision.intent.replicas -= 1
            return decision
        return Stop(reason=f"four-node: rejected at {failure.gate}: {failure.reason}")
