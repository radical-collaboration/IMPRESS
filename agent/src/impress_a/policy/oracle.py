"""The deterministic stand-in control model B runs with no profile named.

`OraclePolicy` and its `decide(obs) -> Decision` contract were deleted in phase 11; what model
B is now is a Specifier half and a Planner half (`policy/specifiers/oracle.py`,
`policy/planners/oracle.py`), each making one structured call per signal through
`policy/reasoning.ask`. This is the model they talk to when no `--model-profile` names a live
endpoint, and it implements the same `NodeReasoner` protocol the live client does - so a test
exercises the whole decision path with no network and no key.

What was deleted with the policy, and is worth recording because the deletions are the point:
`DECISION_SCHEMA`, which asked for a kind, a stage list, a replica count, a params dict, a node
to branch from and a reason in ONE object - so one call answered "what should the campaign be
trying to achieve" and "which tool should run next" and no transcript could say which half a
model was good at. It is `SPEC_SCHEMA` and `STAGE_SCHEMA` now. And `LangChainOracle`, which was
built nowhere, brace-sliced JSON out of the reply despite a docstring claiming structured
output, and had none of the pinned model id, sampling, backoff or status handling Part B doc 02
sections 3 and 7 require. `policy/llm.py` is the live client that does.

`propose()` went with it. It was the `DecisionModel` surface `OraclePolicy` called, and keeping
an unused method for symmetry is how a reader comes to believe there are two ways in.
"""
from __future__ import annotations

import json
from typing import Any


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
    backlog X1's defect reached by another route. They are gone entirely rather than made
    configurable: stopping is not a model's call. The Listener asks when the Spec completes
    and the executor decides, because budget, stagnation and repeated failure are facts about
    state a reasoner cannot see.

    It also implements `reasoning.NodeReasoner`, like the live client, so both halves run the
    same bounded corrective retry against it and a test can exercise the whole decision path
    with no network and no key.
    """

    model_id = "rehearsal"

    def __init__(self, stages: list[str] | None = None) -> None:
        self.stages = list(stages) if stages else []
        self.calls: list[str] = []
        # NO STOPPING CONDITION, and that is the second thing this replaces. It carried
        # `max_cycles=4` and `target_front=3` as literals, so a four-hour arm would have
        # stopped itself in about fifteen minutes whatever the campaign declared - backlog
        # X1's defect, reached by another route. Stopping is not a model's call here: the
        # Listener asks when the Spec completes and the executor decides, so a stand-in has
        # nothing to carry.

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
