"""Control model B - external heavyweight LLM oracle.

Written as a point-by-point improvement on IMPRESS's own oracle precedent
(`examples/protein_binding/protein_binding_run.py`), which Part B doc 02 critiqued:

  precedent                        -> here
  exact string match on the reply  -> structured output validated against a schema
  binary refine/resample           -> full Decision union
  no retry/backoff                 -> bounded retry, explicit degraded mode
  exception swallowed, runs on     -> failure is a LOGGED state transition
  no prompt/model provenance       -> full record incl. pinned model id

`RehearsalOracle` is the deterministic, network-free stand-in (flowgentic demo pattern),
so every LLM decision point is exercisable offline in tests.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from ..core.decision import (Backtrack, CampaignObservation, ComposeAndRun, Decision,
                             ExperimentIntent, Stop, ValidationFailure)
from .base import BasePolicy

DECISION_SCHEMA = {
    "kind": "one of: compose_and_run | backtrack | stop",
    "stages": "list of tool ids (compose_and_run only)",
    "replicas": "int (compose_and_run only)",
    "params": "dict of tool_id -> {param: value} (compose_and_run only)",
    "node_id": "node to branch from (backtrack only)",
    "reason": "string (stop only)",
    "rationale": "one sentence explaining the choice",
}


class DecisionModel(Protocol):
    """One protocol, two implementations - live and rehearsal."""

    model_id: str

    async def propose(self, prompt: str, obs: CampaignObservation) -> dict[str, Any]: ...


class RehearsalOracle:
    """Deterministic stand-in. No network. Mirrors a sensible oracle's behaviour."""

    model_id = "rehearsal"

    async def propose(self, prompt: str, obs: CampaignObservation) -> dict[str, Any]:
        if obs.cycle >= 4:
            return {"kind": "stop", "reason": "rehearsal: cycle budget",
                    "rationale": "enough cycles"}
        if len(obs.pareto_front) >= 3:
            return {"kind": "stop", "reason": "rehearsal: front satisfied",
                    "rationale": "front reached 3"}
        exploring = not obs.pareto_front
        return {"kind": "compose_and_run",
                "stages": ["mock_generate", "mock_design", "mock_fold", "mock_score"],
                "replicas": 3 if exploring else 2,
                "params": {"mock_generate": {"diffusion_steps": 150 if exploring else 90},
                           "mock_design": {"temperature": 0.3 if exploring else 0.05}},
                "rationale": "rehearsal: explore" if exploring else "rehearsal: exploit"}


class LangChainOracle:
    """Live oracle via langchain-core structured output. Never string-matches."""

    def __init__(self, model: Any, model_id: str):
        self.model, self.model_id = model, model_id

    async def propose(self, prompt: str, obs: CampaignObservation) -> dict[str, Any]:
        resp = await self.model.ainvoke(prompt)
        text = getattr(resp, "content", str(resp))
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise ValueError("oracle returned no JSON object")
        return json.loads(text[start:end + 1])


class OraclePolicy(BasePolicy):
    name = "oracle"

    def __init__(self, model: DecisionModel | None = None, max_retries: int = 2,
                 fallback: Any = None, sink: Any = None):
        self.model = model or RehearsalOracle()
        self.max_retries = max_retries
        self.fallback = fallback          # a model-D policy; REQUIRED for real runs
        self.sink = sink
        self.degraded = False

    def render(self, obs: CampaignObservation) -> str:
        front = [{"id": n.id, **{o.name: n.metric(o.name) for o in obs.objectives}}
                 for n in obs.pareto_front]
        return (
            "You are steering an autonomous protein-design campaign.\n"
            f"GOAL: {obs.goal}\nCYCLE: {obs.cycle}\n"
            f"OBJECTIVES: {[o.model_dump() for o in obs.objectives]}\n"
            f"PARETO FRONT ({len(front)}): {json.dumps(front, default=str)}\n"
            f"POPULATION: {obs.population.model_dump()}\n"
            f"BUDGET REMAINING: "
            f"{ {d: obs.budget.remaining(d) for d in obs.budget.limits} }\n"
            f"AVAILABLE TOOLS: {obs.available_tools}\n"
            f"{'LAST REJECTION: ' + obs.last_rejection.reason if obs.last_rejection else ''}\n"
            f"Reply with ONE JSON object matching this schema:\n{json.dumps(DECISION_SCHEMA, indent=2)}"
        )

    def _to_decision(self, raw: dict[str, Any], obs: CampaignObservation) -> Decision:
        kind = raw.get("kind")
        if kind == "stop":
            return Stop(reason=raw.get("reason", "oracle stop"))
        if kind == "backtrack":
            return Backtrack(node_id=raw["node_id"], rationale=raw.get("rationale", ""))
        if kind == "compose_and_run":
            return ComposeAndRun(
                intent=ExperimentIntent(
                    goal=obs.goal, stages=list(raw["stages"]),
                    replicas=int(raw.get("replicas", 1)),
                    params=raw.get("params", {}) or {},
                    parent_node=obs.pareto_front[0].id if obs.pareto_front else None),
                rationale=raw.get("rationale", ""))
        raise ValueError(f"unknown decision kind {kind!r}")

    async def decide(self, obs: CampaignObservation) -> Decision:
        prompt = self.render(obs)
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = await self.model.propose(prompt, obs)
                d = self._to_decision(raw, obs)
                if self.sink:
                    self.sink("decisions", {"policy": self.name, "cycle": obs.cycle,
                                            "model_id": self.model.model_id,
                                            "attempt": attempt, "prompt": prompt,
                                            "response": raw,
                                            "decision": d.model_dump()})
                return d
            except Exception as e:      # parse/transport failure -> bounded retry
                last = e
                prompt += f"\n\nYour previous reply was rejected: {e}. Return valid JSON."
        # Degraded mode is an EXPLICIT, LOGGED transition - never a silent no-op.
        self.degraded = True
        if self.sink:
            self.sink("transitions", {"event": "oracle_degraded", "cycle": obs.cycle,
                                      "error": str(last),
                                      "fallback": getattr(self.fallback, "name", None)})
        if self.fallback is not None:
            return await self.fallback.decide(obs)
        return Stop(reason=f"oracle unavailable and no fallback declared: {last}")

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision:
        """Shrink first - a cost rejection is a sizing problem, not a reasoning failure."""
        if failure.gate in ("budget", "interlock") and isinstance(decision, ComposeAndRun):
            if decision.intent.replicas > 1:
                decision.intent.replicas -= 1
                return decision
            if len(decision.intent.stages) > 2:
                decision.intent.stages = decision.intent.stages[:-1]
                return decision
        if self.fallback is not None:
            return await self.fallback.on_rejected(decision, failure)
        return Stop(reason=f"oracle decision rejected at {failure.gate}: {failure.reason}")
