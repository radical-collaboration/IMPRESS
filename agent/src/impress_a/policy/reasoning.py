"""The seam a control model calls a model through, and what happens when it will not answer.

Backlog H1 is that model A's `reasoner` argument was *stored and never read*: there was no
schema, no retry, no corrective feedback and no declared fallback, while
`planning/phase1-partB-architecture/02-control-models.md:59-61` specifies all four. So
`--model A` was a LangGraph-shaped rule cascade, and the slot for a model was decoration.

This is that slot made real, as one function rather than one per node, because the four
requirements are the same requirements everywhere:

**Bounded.** A fixed number of attempts, never "until it works". An allocation is being held
while this runs, and a model that keeps almost answering is more expensive than one that
refuses.

**Schema-checked, not string-matched.** The reply must be a JSON object carrying every required
key. This is the precedent Part B doc 02 criticised in
`examples/protein_binding/protein_binding_run.py`: an exact string match on the reply, so a
model that answered correctly in different words was treated as having failed.

**Corrected, not just retried.** The rejection is appended to the prompt, so the second attempt
is told what was wrong with the first. Retrying an identical prompt mostly reproduces the
identical failure.

**Refused loudly.** Exhausting the attempts raises `NodeRefused`. The caller then falls back to
its own deterministic rule and **records the transition**, because the failure mode that
matters here is the one the precedent had: the exception swallowed and the campaign continuing,
which makes a degraded arm indistinguishable from a working one. The four-arm experiment voids
an arm shown to have degraded, and that is only enforceable if degrading leaves a record.

A model is never asked to judge whether a result passed its gates. That is decision 0013's line
and it is not negotiable: an LLM may author a protocol, it does not score one.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)

#: Attempts per node, including the first. Two, not more: the second attempt carries the
#: correction, and a third has nothing new to add while costing another round trip.
ATTEMPTS = 2


class NodeRefused(RuntimeError):
    """Every attempt at one node failed. Carries the last reason, for the record."""

    def __init__(self, node: str, attempts: int, last: Exception | str) -> None:
        super().__init__(f"{node}: refused after {attempts} attempt(s): {last}")
        self.node = node
        self.attempts = attempts
        self.last = str(last)


@runtime_checkable
class NodeReasoner(Protocol):
    """One bounded call. The same protocol for a live client and an offline rehearsal.

    `schema` is passed rather than embedded in the prompt by the caller so that a client with
    real structured-output support can use it as a schema instead of as prose.
    """

    model_id: str

    async def think(self, node: str, prompt: str,
                    schema: dict[str, str]) -> dict[str, Any]: ...


async def ask(reasoner: Any, node: str, prompt: str, schema: dict[str, str],
              required: tuple[str, ...] = (), *, validate: Any = None,
              attempts: int = ATTEMPTS, sink: Any = None,
              cycle: int = 0) -> dict[str, Any]:
    """One node's worth of reasoning, or `NodeRefused`.

    `validate` is the node's own check on a reply that has the right keys - that a strategy is
    one of the three that exist, that a count is positive. It runs **inside** the retry loop,
    and that placement is the whole value of it: a node that checked afterwards would reject a
    model naming a strategy it invented and degrade on the spot, never telling it what the
    three strategies are. Corrective retry that cannot correct the commonest mistake is not
    corrective. It raises to reject, like any other failure here.

    Every attempt is recorded through `sink` when one is given - prompt, reply and model id -
    which is what makes a live arm replayable and what the experiment reads for
    decision-layer timing. The reply is not recorded as a *result*: nothing a model says is
    scored, only what the campaign then executed.
    """
    last: Exception | str = "no attempt made"
    text = prompt
    for attempt in range(max(1, attempts)):
        try:
            raw = await reasoner.think(node, text, schema)
            if not isinstance(raw, dict):
                raise TypeError(f"expected a JSON object, got {type(raw).__name__}")
            missing = [k for k in required if raw.get(k) in (None, "")]
            if missing:
                raise ValueError(f"reply is missing {missing}")
            if validate is not None:
                validate(raw)
            if sink:
                sink("decisions", {"node": node, "cycle": cycle, "attempt": attempt,
                                   "model_id": getattr(reasoner, "model_id", "?"),
                                   "prompt": text, "response": raw})
            return raw
        except Exception as failure:          # transport, parse or schema - all bounded here
            last = failure
            log.warning("reasoner: node %s attempt %d rejected: %s", node, attempt, failure)
            text = (f"{text}\n\nYour previous reply was rejected: {failure}. "
                    f"Return ONE JSON object with every key: {json.dumps(schema)}")
    raise NodeRefused(node, max(1, attempts), last)


def degraded(sink: Any, node: str, cycle: int, reason: str, fallback: str) -> None:
    """Record that a node fell back to its deterministic rule.

    A separate function because every caller must do it and none of them should decide how.
    The event name matches model B's `oracle_degraded`, so one query over `transitions` finds
    every degraded decision in a campaign whatever model made it - which is what the
    experiment's void rule needs.
    """
    log.warning("reasoner: node %s degraded to %s (%s)", node, fallback, reason)
    if sink:
        sink("transitions", {"event": "reasoner_degraded", "node": node, "cycle": cycle,
                             "error": reason, "fallback": fallback})


__all__ = ["ATTEMPTS", "NodeRefused", "NodeReasoner", "ask", "degraded"]
