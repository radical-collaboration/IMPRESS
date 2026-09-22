"""The campaign manager - now a facade over an executor and a reasoner.

  observe -> DECIDE -> compose -> validate -> execute -> analyze -> update -> terminate?

The loop is still ours, and every step above still happens in that order for any one
experiment. What changed is who drives it. The manager used to BE the loop, calling the
policy once per cycle and then blocking on the graph it asked for, so a reasoner could
never be consulted while work was running. Now:

  * `runtime.executor.CampaignExecutor` owns all campaign state and the engine, and
    reaps runs as they finish;
  * the reasoner runs as its own coroutine and reaches the executor through
    `core.session.CampaignSession`;
  * `policy.driver.SequentialPolicyDriver` makes a `decide`-style policy look like a
    reasoner, so control models A-D are unchanged.

`CampaignManager` remains the public entry point and the thing the control plane
registers. It builds the executor in `__init__` - not in `run()` - because callers
legitimately inspect `mgr.tree`, `mgr.budget` and `mgr.observe()` before and after a
campaign, and a facade that only existed mid-run would break every one of them.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .core.pareto import pareto_front
from .core.session import CampaignStopped
from .policy.driver import SequentialPolicyDriver
from .runtime.executor import (
    CampaignAborted,
    CampaignExecutor,
    CampaignResult,
    CampaignSpec,
    RunRecord,
)
from .runtime.runservice import RunService
from .runtime.session import InProcessSession
from .tools.registry import Registry

__all__ = ["CampaignAborted", "CampaignManager", "CampaignResult", "CampaignSpec",
           "RunRecord"]

_DELEGATED = ("tree", "budget", "prov", "jobs", "trust", "reg", "root", "cycle",
              "run_seq", "dispatched", "observe", "composer", "validator",
              "pending_human")


class CampaignManager:
    def __init__(self, spec: CampaignSpec, policy: Any, registry: Registry | None = None):
        self.spec, self.policy = spec, policy
        self.executor = CampaignExecutor(spec, policy, registry)
        self.session = InProcessSession(self.executor)
        self.runs = RunService(self.executor)

    # -- delegation ----------------------------------------------------------
    # The executor owns campaign state; these keep the long-standing surface working for
    # the control plane, the CLI and the tests.
    def __getattr__(self, name: str) -> Any:
        if name in _DELEGATED:
            return getattr(self.executor, name)
        raise AttributeError(name)

    @property
    def prov_sink(self) -> Any:
        return self.executor.prov_sink

    @prov_sink.setter
    def prov_sink(self, sink: Any) -> None:
        self.executor.prov_sink = sink

    # -- the campaign --------------------------------------------------------
    def _reasoner(self) -> Any:
        """A policy that implements `conduct` drives itself; anything else is driven."""
        target = getattr(self.policy, "inner", self.policy)
        if hasattr(self.policy, "conduct") or hasattr(target, "conduct"):
            return self.policy if hasattr(self.policy, "conduct") else target
        return SequentialPolicyDriver(
            self.policy, max_turns=self.spec.max_cycles,
            max_attempts=self.spec.max_attempts, concurrency=self.spec.concurrency)

    async def run(self) -> CampaignResult:
        ex = self.executor
        await ex.start()
        aborted: BaseException | None = None
        pump = asyncio.create_task(ex.pump())
        reasoner = asyncio.create_task(self._reasoner().conduct(self.session))
        try:
            # Whichever finishes first ends the campaign: the reasoner running out of
            # things to do, or the executor deciding it is over. The executor's reasons
            # - budget, stagnation, repeated failure - are facts about state the reasoner
            # cannot see, so termination is not the reasoner's to declare.
            done, _ = await asyncio.wait({pump, reasoner},
                                         return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                if not t.cancelled() and (err := t.exception()) is not None:
                    aborted = err
        finally:
            ex.request_stop(ex.stop_reason)
            for t in (reasoner, pump):
                t.cancel()
            await asyncio.gather(reasoner, pump, return_exceptions=True)
            await ex.shutdown(aborted)

        if aborted is not None and not isinstance(aborted, CampaignStopped):
            raise aborted

        front = pareto_front(ex.tree.live(), self.spec.objectives)
        ex._log("transitions", {"event": "terminated", "reason": ex.stop_reason,
                                "cycles": ex.cycle,
                                "front": [n.id for n in front]})
        return CampaignResult(campaign_id=self.spec.campaign_id, cycles=ex.cycle,
                              stop_reason=ex.stop_reason, front=front, tree=ex.tree,
                              corrections=getattr(self.policy, "corrections", []),
                              runs=ex.dispatched)
