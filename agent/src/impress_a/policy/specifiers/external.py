"""Model C's Specifier half: one of the two role inboxes.

Decision 0002 ruled that model C **is** headless control mode 2 rather than a mode any model
can run in, so the role split must not turn one headless mode into two. It does not: there is
still one `steer` operation on the control plane, and a directive says which role it is for
with a `role` key **inside the dict it already carries**. ADR 0007 forbids an adapter carrying
an operation the core protocol lacks, so adding `steer_specifier` would have meant adding it to
the protocol and to every adapter, to express something one field expresses.

    await plane.steer(cid, {"role": "specifier", "kind": "revise", "objectives": [...]})
    await plane.steer(cid, {"role": "planner", "stages": [...], "replicas": 2})

A directive with no `role` goes to the planner, which is what every existing caller and
`tests/test_http_adapter.py` send.

**Two things a caller may not do, and they are the interesting part of the contract.**

*It may not declare an objective satisfied.* `Specifier.satisfied` is a finding computed from
realized data, not a decision - and a caller who could assert it could end a campaign by
saying the work was done. The campaign's stop condition is the one thing external control does
not get, for the same reason an LLM may author a protocol and not score it (decision 0013).
A directive that tries is refused with its reason, not ignored.

*It does not author the initial Spec.* `Goal -> Spec` for the declared objectives is a
transcription - one objective per declared metric, bounded ones getting a threshold and
unbounded ones a measurement - so it is delegated to `ThresholdSpecifier` exactly as model A
delegates it. That also keeps the four-arm comparison answerable: an arm whose Specifier starts
from different objectives is void for the primary endpoint, so starting from the campaign's own
is not a limitation but the condition of being compared at all. Everything after the first Spec
is the caller's.

**A silent timeout here is harmless, which is why it is handled differently from the planner's.**
A Specifier that hears nothing returns an empty revision: the Spec simply does not change, no
decision is lost, and the campaign keeps drawing against what was already specified. A *Planner*
that hears nothing has a cycle to fill, which is where `on_timeout` matters and where falling
back to a rule cascade would turn arm C into arm D - the single most dangerous failure mode in
the four-arm design.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...core.goal import Goal
from ...core.spec import (
    Aim,
    SatisfactionRule,
    Spec,
    SpecObjective,
    SpecRevision,
)
from ..specifier import BaseSpecifier, SpecEvidence
from .explicit import ThresholdSpecifier

log = logging.getLogger(__name__)

#: Keys a specifier directive may carry. Anything else is refused by name, because a caller
#: whose typo was ignored has been told its directive was accepted.
DIRECTIVE_KEYS = frozenset({"role", "kind", "objectives", "delete", "rationale", "aim"})


class ExternalSpecifier(BaseSpecifier):
    """Blocks on a `{"role": "specifier"}` inbox; the caller authors revisions."""

    name = "external-spec"

    def __init__(self, timeout_s: float = 5.0, sink: Any = None) -> None:
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.timeout_s = timeout_s
        self.sink = sink
        #: What the caller was asked about, so it can `observe()` what this half saw.
        self.evidence: asyncio.Queue[SpecEvidence] = asyncio.Queue()
        self.refusals: list[str] = []
        self._base = ThresholdSpecifier()

    # -- called by the control plane, through `RolePair.steer` ---------------
    def steer(self, directive: dict[str, Any]) -> None:
        self.inbox.put_nowait(directive)

    # -- Specifier -----------------------------------------------------------
    async def initial_spec(self, goal: Goal) -> Spec:
        return await self._base.initial_spec(goal)

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        self.evidence.put_nowait(ev)
        try:
            directive = await asyncio.wait_for(self.inbox.get(), timeout=self.timeout_s)
        except TimeoutError:
            if self.sink:
                self.sink("transitions", {"event": "caller_timeout", "role": "specifier",
                                          "cycle": ev.cycle})
            return SpecRevision()
        try:
            return self._to_revision(directive, spec)
        except ValueError as refused:
            # Refused, recorded, and the campaign continues on the Spec it has. A revision
            # nobody could apply is not a reason to end a campaign, but it must not look like
            # one that was applied either.
            self.refusals.append(str(refused))
            log.warning("external specifier: directive refused: %s", refused)
            if self.sink:
                self.sink("transitions", {"event": "directive_refused", "role": "specifier",
                                          "cycle": ev.cycle, "reason": str(refused)})
            return SpecRevision()

    def _to_revision(self, directive: dict[str, Any], spec: Spec) -> SpecRevision:
        """A directive as a `SpecRevision`, or `ValueError` naming what is wrong with it."""
        unknown = sorted(set(directive) - DIRECTIVE_KEYS)
        if unknown:
            raise ValueError(f"unknown directive key(s) {unknown}; allowed: "
                             f"{sorted(DIRECTIVE_KEYS)}")
        if "satisfied" in directive or directive.get("kind") == "satisfied":
            raise ValueError(
                "a caller may not declare an objective satisfied: satisfaction is computed "
                "from realized data, and a caller able to assert it could end a campaign by "
                "saying the work was done")

        deleted = [oid for oid in (directive.get("delete") or [])]
        for oid in deleted:
            if oid not in spec.objectives:
                raise ValueError(f"cannot delete {oid!r}: no such objective in the Spec")

        aims: list[Aim] = []
        objectives: list[SpecObjective] = []
        raw_objectives = directive.get("objectives") or []
        if raw_objectives:
            aim = Aim(statement=str(directive.get("aim") or "the caller's aim"))
            aims.append(aim)
            for raw in raw_objectives:
                targets = list(raw.get("targets") or [])
                if not targets:
                    raise ValueError("every objective needs at least one target metric")
                bounded = raw.get("min") is not None or raw.get("max") is not None
                objectives.append(SpecObjective(
                    aim=aim.id,
                    statement=str(raw.get("statement") or f"measure {targets[0]}"),
                    targets=targets,
                    parent_node=raw.get("parent_node"),
                    satisfied_when=SatisfactionRule(
                        kind="metric_in_range" if bounded else "metric_present",
                        metric=targets[0], min=raw.get("min"), max=raw.get("max"),
                        n=int(raw.get("n") or 1)),
                ))
        return SpecRevision(new_aims=aims, new_objectives=objectives, deleted=deleted,
                            rationale=str(directive.get("rationale")
                                          or f"{self.name}: external directive"))


__all__ = ["DIRECTIVE_KEYS", "ExternalSpecifier"]
