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
  * a reasoner is either a `conduct` implementation or a Specifier/Planner **pair**, which
    `runtime.roles.RolesDriver` drives. There is no third kind: the `decide(obs) -> Decision`
    contract and the driver that adapted it were deleted in phase 11, and with them
    `CampaignSpec.control`, which used to select between two vocabularies.

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
from .runtime.executor import (
    CampaignAborted,
    CampaignExecutor,
    CampaignResult,
    CampaignSpec,
    RunRecord,
)
from .runtime.roles import RolesDriver, goal_from_spec
from .runtime.runservice import RunService
from .runtime.session import InProcessSession
from .tools.registry import Registry

__all__ = ["CampaignAborted", "CampaignManager", "CampaignResult", "CampaignSpec",
           "RunRecord"]

_DELEGATED = ("tree", "budget", "prov", "jobs", "trust", "reg", "root", "cycle",
              "run_seq", "dispatched", "observe", "composer", "validator",
              "pending_human", "record_reasoning")


class CampaignManager:
    def __init__(self, spec: CampaignSpec, policy: Any, registry: Registry | None = None):
        self.spec, self.policy = spec, policy
        self.executor = CampaignExecutor(spec, policy, registry)
        self.session = InProcessSession(self.executor)
        self.runs = RunService(self.executor)
        #: The role driver, once `run()` has built one. See `_roles`.
        self._roles_driver: Any = None

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

    @property
    def under_external_control(self) -> bool:
        return self.executor.under_external_control

    @under_external_control.setter
    def under_external_control(self, value: bool) -> None:
        # A property, not a bare attribute: `__getattr__` delegates READS of a known set and
        # nothing delegates writes, so `manager.under_external_control = True` would have
        # landed on the manager while the executor - which is what consults it - kept its
        # default. The liveness bound would then have stayed disarmed for arm C too, which is
        # the one arm it is actually for.
        self.executor.under_external_control = bool(value)

    # -- the campaign --------------------------------------------------------
    def _roles(self) -> Any:
        """The Spec Loop + Planning Loop pipeline, as one `conduct`.

        It needs no special case in `run()`: the manager already races a reasoner's `conduct`
        against the executor's pump, and a role pipeline is a reasoner that happens to be four
        cooperating responsibilities rather than one. `publish` is handed over explicitly
        because the Spec's only writer is the executor, and `publish_spec` is not a
        `CampaignSession` member until phase 3 - a driver that declares what it needs beats one
        that discovers it on the session.
        """
        # Held, not just returned. The driver carries the Listener's `DataRegistry` - the
        # reasoner's own view of its results - and that is a thing a caller legitimately
        # inspects after a campaign, the same way it inspects `mgr.tree` and `mgr.budget`.
        # It is also the only way to assert that the reasoner saw every run the executor
        # settled, which is what the deleted `interpret` hook used to be tested through.
        self._roles_driver = RolesDriver(
            goal_from_spec(self.spec), self.policy.specifier, self.policy.planner,
            max_turns=self.spec.max_cycles, max_attempts=self.spec.max_attempts,
            concurrency=self.spec.concurrency, publish=self.executor.publish_spec)
        return self._roles_driver

    def _reasoner(self) -> Any:
        """A reasoner that implements `conduct` drives itself; a role pair is driven.

        `conduct` is checked FIRST, and the ordering is load-bearing: a `conduct` reasoner is
        already a complete reasoner, and the role pipeline is one implementation of one rather
        than a wrapper every reasoner must wear. Checking the other way round wrapped
        `impress-a serve`'s deliberately absent reasoner and drove it - a served campaign has
        no local reasoner by design, which is the whole point of serving it.

        There is no third case any more. `SequentialPolicyDriver` and the `decide` contract it
        drove are gone (phase 11): a reasoner is either a `conduct` implementation or a
        Specifier/Planner pair, and `CampaignSpec.control` no longer selects between two
        vocabularies because there is only one.
        """
        if hasattr(self.policy, "conduct"):
            return self.policy
        if hasattr(self.policy, "specifier") and hasattr(self.policy, "planner"):
            return self._roles()
        raise TypeError(
            f"{type(self.policy).__name__} is neither a `conduct` reasoner nor a "
            f"Specifier/Planner pair. The `decide(obs) -> Decision` contract was deleted in "
            f"phase 11; build a pair with `policy.registry.build_roles(letter)`")

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
