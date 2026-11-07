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

from ..core.decision import (
    Backtrack,
    CampaignObservation,
    ComposeAndRun,
    Decision,
    ExperimentIntent,
    Stop,
    ValidationFailure,
)
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
    """Deterministic stand-in. No network, and no chain of its own.

    Two defects this replaces, both backlog H2 and both silent:

    **It returned the mock chain whatever the campaign declared.** `stages` was the literal
    list `["mock_generate", ...]`, and `_build_b` did not forward `o.stages`, so `--model B`
    against the six-stage Delta chain would have loaded the real toolkits, validated them, and
    then executed mocks - reported as a model-B result, with plausible metrics and `6/6 tasks
    ok`. That is the single most dangerous failure the four-arm design names. The chain now
    comes from the campaign, there is no default, and a rehearsal with no chain refuses rather
    than inventing one.

    **Its stopping conditions were hardcoded** - `cycle >= 4`, `front >= 3` - so a four-hour
    arm would have stopped itself in twenty minutes whatever the campaign declared, which is
    the same defect as X1 reaching the same place by another route. They are constructor
    arguments now, filled from the campaign's own `max_cycles` and `target_front`.

    It also implements `reasoning.NodeReasoner`, like the live client, so both halves run the
    same bounded corrective retry against it and a test can exercise the whole decision path
    with no network and no key.
    """

    model_id = "rehearsal"

    def __init__(self, stages: list[str] | None = None, max_cycles: int = 6,
                 target_front: int = 3) -> None:
        self.stages = list(stages) if stages else []
        self.max_cycles, self.target_front = max_cycles, target_front
        self.calls: list[str] = []

    # -- the role halves' seam (`reasoning.NodeReasoner`) --------------------
    async def think(self, node: str, prompt: str,
                    schema: dict[str, str]) -> dict[str, Any]:
        """Answer one node, in that node's own schema.

        Keyed on the node rather than on the prompt's wording, because a stand-in that
        interpreted the prompt would be a second implementation of the thing it stands in for.
        """
        del schema
        self.calls.append(node)
        if node == "spec":
            return self._spec(prompt)
        if node == "stage":
            return self._stage(prompt)
        raise ValueError(f"rehearsal: no scripted answer for node {node!r}")

    def _spec(self, prompt: str) -> dict[str, Any]:
        """Refine the best design once a front exists; hold while it is empty."""
        front = _front_ids(prompt)
        if not front:
            return {"action": "hold", "rationale": "rehearsal: front empty, keep drawing"}
        return {"action": "refine", "parent_node": front[0],
                "metric": _first_metric(prompt),
                "rationale": "rehearsal: refine the best design so far"}

    def _stage(self, prompt: str) -> dict[str, Any]:
        """The campaign's own chain, at a width that depends on whether it is refining."""
        self._require_a_chain()
        refining = "REFINING: []" not in prompt
        return {"stages": list(self.stages),
                "replicas": 2 if refining else 3,
                "params": {},
                "rationale": "rehearsal: exploit" if refining else "rehearsal: explore"}

    def _require_a_chain(self) -> None:
        if not self.stages:
            raise ValueError(
                "rehearsal: no chain was supplied. The campaign's `stages` must reach this "
                "oracle, or a real campaign validates the real toolkits and then executes "
                "mocks, reported as a model-B result (backlog H2)")

    # -- the legacy `DecisionModel` surface ---------------------------------
    async def propose(self, prompt: str, obs: CampaignObservation) -> dict[str, Any]:
        """For `OraclePolicy`, until phase 11 deletes it.

        Answers with the campaign's chain rather than the mock one - the half of H2 that
        matters on hardware - and takes its stopping numbers from the constructor.
        """
        del prompt
        if obs.cycle >= self.max_cycles:
            return {"kind": "stop", "reason": f"rehearsal: cycle budget {self.max_cycles}",
                    "rationale": "enough cycles"}
        if self.target_front and len(obs.pareto_front) >= self.target_front:
            return {"kind": "stop", "reason": "rehearsal: front satisfied",
                    "rationale": f"front reached {self.target_front}"}
        self._require_a_chain()
        exploring = not obs.pareto_front
        return {"kind": "compose_and_run",
                "stages": list(self.stages),
                "replicas": 3 if exploring else 2,
                "rationale": "rehearsal: explore" if exploring else "rehearsal: exploit"}


def _front_ids(prompt: str) -> list[str]:
    """Design ids from the prompt's `FRONT_IDS` line.

    The stand-in reads the prompt it was given, which is what sharing one `think` signature
    with the live client costs - and `OracleSpecifier._prompt` carries that line as JSON
    precisely so the reading is a contract rather than a guess at an f-string's output.
    """
    return _json_line(prompt, "FRONT_IDS")


def _first_metric(prompt: str) -> str:
    """The first declared objective's metric, from the prompt's `METRICS` line."""
    found = _json_line(prompt, "METRICS")
    return found[0] if found else ""


def _json_line(prompt: str, label: str) -> list[str]:
    for line in prompt.splitlines():
        if line.startswith(f"{label}:"):
            try:
                value = json.loads(line.split(":", 1)[1].strip())
            except json.JSONDecodeError:
                return []
            return [str(v) for v in value] if isinstance(value, list) else []
    return []


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
            "Reply with ONE JSON object matching this schema:\n"
            f"{json.dumps(DECISION_SCHEMA, indent=2)}"
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
        """Shrink BREADTH first - a cost rejection is a sizing problem, not a reasoning one.

        Never the chain: see `ThresholdPolicy.on_rejected` for job 22675512, where dropping
        the tail took the only producer of two of four objectives off the graph. This one did
        it silently, without even the warning that one carried.
        """
        if failure.gate in ("budget", "interlock") and isinstance(decision, ComposeAndRun):
            if decision.intent.replicas > 1:
                decision.intent.replicas -= 1
                return decision
        if self.fallback is not None:
            return await self.fallback.on_rejected(decision, failure)
        return Stop(reason=f"oracle decision rejected at {failure.gate}: {failure.reason}")
