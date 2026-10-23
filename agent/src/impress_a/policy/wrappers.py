"""Composable policy decorators.

Adopted from campaign_manager's `adr/policies/wrappers.py` (Phase 3, pattern #1). Wrapping
is how enforcement and provenance attach without touching policy internals - cleaner than
embedding checks inside each policy, and it implements Part B's "validation is external to
the policy".
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.decision import (CampaignObservation, ComposeAndRun, Decision, Stop,
                             ValidationFailure)


class PolicyWrapper:
    def __init__(self, inner):
        self.inner = inner
        self.name = f"{type(self).__name__.lower()}({getattr(inner,'name','?')})"

    async def decide(self, obs: CampaignObservation) -> Decision:
        return await self.inner.decide(obs)

    async def interpret(self, results, obs):
        return await self.inner.interpret(results, obs)

    async def on_rejected(self, decision, failure):
        return await self.inner.on_rejected(decision, failure)


class LoggingPolicy(PolicyWrapper):
    """Provenance decorator: records every decision with its rationale."""

    def __init__(self, inner, sink: Callable[[str, dict[str, Any]], None]):
        super().__init__(inner)
        self.sink = sink

    async def decide(self, obs: CampaignObservation) -> Decision:
        d = await self.inner.decide(obs)
        self.sink("decisions", {"policy": getattr(self.inner, "name", "?"),
                                "cycle": obs.cycle, "decision": d.model_dump()})
        return d


class RuleCorrectionsPolicy(PolicyWrapper):
    """Unconditional external guard.

    Applies rule-based corrections to EVERY decision before it reaches composition -
    the separation-of-authority pattern from the flowgentic demo (Phase 3, pattern #3),
    made composable.
    """

    def __init__(self, inner, max_replicas: int = 16,
                 forbid_tools: tuple[str, ...] = ()):
        super().__init__(inner)
        self.max_replicas, self.forbid_tools = max_replicas, forbid_tools
        self.corrections: list[str] = []

    async def decide(self, obs: CampaignObservation) -> Decision:
        d = await self.inner.decide(obs)
        if isinstance(d, ComposeAndRun):
            if d.intent.replicas > self.max_replicas:
                self.corrections.append(
                    f"cycle {obs.cycle}: replicas {d.intent.replicas} -> {self.max_replicas}")
                d.intent.replicas = self.max_replicas
            bad = [t for t in d.intent.stages if t in self.forbid_tools]
            if bad:
                self.corrections.append(f"cycle {obs.cycle}: removed {bad}")
                d.intent.stages = [t for t in d.intent.stages if t not in self.forbid_tools]
                if not d.intent.stages:
                    return Stop(reason="all requested stages forbidden by guard")
        return d


class NullPolicy:
    """No-op baseline. Stops immediately - useful as a control and in smoke tests."""

    name = "null"

    async def decide(self, obs: CampaignObservation) -> Decision:
        return Stop(reason="null policy")

    async def interpret(self, results, obs):
        return None

    async def on_rejected(self, decision, failure):
        return Stop(reason="null policy")
