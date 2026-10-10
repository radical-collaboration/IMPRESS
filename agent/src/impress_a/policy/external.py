"""Control model C - external caller steering. This IS headless control mode 2.

`decide` does not compute; it BLOCKS on the control plane until a directive arrives or a
declared timeout fires. The campaign is otherwise identical - same state, composition,
validation and execution. Being external confers no privilege: a directive is composed and
validated exactly as any policy's decision would be.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..core.decision import (Backtrack, CampaignObservation, ComposeAndRun, Decision,
                             ExperimentIntent, RequestHuman, Stop, ValidationFailure)
from .base import BasePolicy


class ExternalPolicy(BasePolicy):
    name = "external"

    def __init__(self, timeout_s: float = 30.0, on_timeout: str = "fallback",
                 fallback: Any = None, sink: Any = None):
        if on_timeout not in ("hold", "fallback", "stop"):
            raise ValueError("on_timeout must be hold | fallback | stop")
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.observations: asyncio.Queue[CampaignObservation] = asyncio.Queue()
        self.timeout_s, self.on_timeout = timeout_s, on_timeout
        self.fallback, self.sink = fallback, sink
        self.rejections: list[ValidationFailure] = []

    # -- called by the control plane ---------------------------------------
    def steer(self, directive: dict[str, Any]) -> None:
        self.inbox.put_nowait(directive)

    # -- ControlPolicy ------------------------------------------------------
    async def decide(self, obs: CampaignObservation) -> Decision:
        self.observations.put_nowait(obs)      # caller can observe() what we saw
        try:
            d = await asyncio.wait_for(self.inbox.get(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            if self.sink:
                self.sink("transitions", {"event": "caller_timeout", "cycle": obs.cycle,
                                          "policy": self.on_timeout})
            if self.on_timeout == "fallback" and self.fallback is not None:
                return await self.fallback.decide(obs)
            if self.on_timeout == "hold":
                return RequestHuman(question="external caller silent; awaiting directive",
                                    context={"cycle": obs.cycle})
            return Stop(reason="external caller timed out")
        return self._to_decision(d, obs)

    @staticmethod
    def _to_decision(d: dict[str, Any], obs: CampaignObservation) -> Decision:
        kind = d.get("kind", "compose_and_run")
        if kind == "stop":
            return Stop(reason=d.get("reason", "caller stop"))
        if kind == "backtrack":
            return Backtrack(node_id=d["node_id"], rationale=d.get("rationale", ""))
        if kind == "request_human":
            return RequestHuman(question=d.get("question", ""), context=d.get("context", {}))
        return ComposeAndRun(
            intent=ExperimentIntent(
                goal=obs.goal, stages=list(d["stages"]),
                replicas=int(d.get("replicas", 1)), params=d.get("params", {}) or {},
                parent_node=d.get("parent_node")),
            rationale=d.get("rationale", "external directive"))

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision:
        """The caller is told WHY and gets another turn - no privilege, but a fair one."""
        self.rejections.append(failure)
        if self.sink:
            self.sink("transitions", {"event": "directive_rejected",
                                      "gate": failure.gate, "reason": failure.reason})
        return await self.decide_after_rejection(failure)

    async def decide_after_rejection(self, failure: ValidationFailure) -> Decision:
        try:
            d = await asyncio.wait_for(self.inbox.get(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            return Stop(reason=f"caller did not respond to rejection at {failure.gate}")
        return self._to_decision(d, CampaignObservation(campaign_id="", cycle=0, goal=""))
