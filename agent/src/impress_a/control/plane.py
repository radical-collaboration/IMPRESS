"""The transport-agnostic control plane (Part B doc 06).

One core protocol; MCP / HTTP+SSE / in-process are thin adapters over it. No adapter may
add an operation absent from the core, or the semantics fork.

`observe()` returns the SAME CampaignObservation a policy's `decide` receives - informed
monitoring means parity of evidence, not a progress bar.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Protocol

from ..core.artifacts import Property
from ..core.decision import CampaignObservation
from ..core.results import RunStatus


class Event(dict):
    """An append-only stream record with a resumable cursor."""


class CampaignControlPlane(Protocol):
    """One protocol; MCP / HTTP+SSE / in-process are adapters over it.

    The run operations are part of the CORE protocol rather than something a transport
    adds, which is what keeps ADR 0007's rule intact: no adapter may offer an operation
    the others do not. They are also the same operations `CampaignSession` exposes to a
    reasoner - deliberately, because an external caller steering a campaign and an
    in-process reasoner driving one are the same activity seen from different sides.
    """

    async def submit(self, spec: Any) -> str: ...
    async def observe(self, campaign_id: str,
                      since: int | None = None) -> CampaignObservation: ...
    async def events(self, campaign_id: str, since: int = 0, stream: bool = False,
                     timeout: float = 30.0) -> AsyncIterator[Event]: ...
    async def steer(self, campaign_id: str, directive: dict[str, Any]) -> dict[str, Any]: ...
    async def pause(self, campaign_id: str) -> None: ...
    async def resume(self, campaign_id: str) -> None: ...
    async def stop(self, campaign_id: str, reason: str) -> None: ...
    async def artifacts(self, campaign_id: str, selector: str) -> list[dict[str, Any]]: ...
    async def provenance(self, campaign_id: str, kind: str) -> list[dict[str, Any]]: ...
    async def ingest_measurement(self, campaign_id: str, node_id: str,
                                 prop: Property) -> dict[str, Any]: ...

    # -- runs ----------------------------------------------------------------
    async def submit_run(self, campaign_id: str,
                         intent: dict[str, Any]) -> dict[str, Any]: ...
    async def list_runs(self, campaign_id: str,
                        state: str | None = None) -> list[dict[str, Any]]: ...
    async def run_result(self, campaign_id: str,
                         run_id: str) -> dict[str, Any] | None: ...
    async def await_run_result(self, campaign_id: str, run_id: str,
                               wait_s: float = 30.0) -> dict[str, Any]: ...
    async def status(self, campaign_id: str, run_id: str) -> RunStatus: ...
    async def inflight(self, campaign_id: str) -> list[RunStatus]: ...
    async def cancel_run(self, campaign_id: str, run_id: str) -> dict[str, Any]: ...

    # -- the tree ------------------------------------------------------------
    async def backtrack(self, campaign_id: str, node_id: str,
                        rationale: str = "") -> str: ...
    async def request_human(self, campaign_id: str, question: str,
                            context: dict[str, Any] | None = None) -> None: ...


class InProcessControlPlane:
    """Reference adapter. Drives a CampaignManager in the same process.

    Used by HITL agents co-located in the job, and by the test suite. HTTP+SSE and MCP
    adapters translate transport only.
    """

    def __init__(self, policy_factory: Any = None) -> None:
        self.managers: dict[str, Any] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._events: dict[str, list[Event]] = {}
        # `policy_factory(spec) -> policy`, injected rather than imported: the control
        # layer may reach `manager` and `core`, and building a policy here directly
        # would quietly widen that.
        self.policy_factory = policy_factory

    def register(self, manager) -> str:
        cid = manager.spec.campaign_id
        self.managers[cid] = manager
        self._events.setdefault(cid, [])
        manager.prov_sink = self.emit
        return cid

    def emit(self, cid: str, kind: str, payload: dict[str, Any]) -> None:
        evts = self._events.setdefault(cid, [])
        # Payload keys are flattened onto the event for convenience, but the payload is
        # now campaign provenance rather than only this adapter's own calls, and some
        # records carry their own `kind` (a backtrack decision, for one). Splatting them
        # blindly is a TypeError, so envelope keys win and a collision is renamed rather
        # than dropped - losing a field silently would be worse than an ugly one.
        flat = {(f"record_{k}" if k in ("seq", "kind") else k): v
                for k, v in payload.items()}
        evts.append(Event(seq=len(evts), kind=kind, **flat))

    async def submit(self, spec: Any) -> str:
        """Start a campaign and return its id, without waiting for it to finish."""
        if self.policy_factory is None:
            raise NotImplementedError(
                "no policy_factory configured; construct a CampaignManager "
                "and register() it instead")
        from ..manager import CampaignManager
        mgr = CampaignManager(spec, self.policy_factory(spec))
        cid = self.register(mgr)
        self.tasks[cid] = asyncio.create_task(mgr.run())
        return cid

    async def observe(self, campaign_id: str,
                      since: int | None = None) -> CampaignObservation:
        """Exactly what the reasoner sees - the session's own `observe`, not a
        look-alike assembled here. ADR 0007 asks for parity of evidence, and going
        through the session is what keeps `last_rejection` and the absorption watermark
        on the monitoring side of the wire as well as the deciding side."""
        return await self.managers[campaign_id].session.observe(since)

    async def events(self, campaign_id: str, since: int = 0, stream: bool = False,
                     timeout: float = 30.0) -> AsyncIterator[Event]:
        """One operation, two representations: a cursor-paged page, or a live tail.

        The tail exists because the completion queue a reasoner consumes in-process is an
        `asyncio.Queue` in the executor's memory. A consumer that is not in that memory
        needs the same sequence from somewhere, and this is where it comes from - so the
        streaming form is part of the operation rather than something the HTTP adapter
        invented for itself.

        Polls its own list, because provenance is appended to rather than published.
        A push-based source would replace the body of this loop and nothing else.
        """
        if not stream:
            for e in self._events.get(campaign_id, [])[since:]:
                yield e
            return
        cursor, idle = since, 0.0
        while idle < timeout:
            sent = 0
            for e in self._events.get(campaign_id, [])[cursor:]:
                cursor, sent = int(e["seq"]) + 1, sent + 1
                yield e
            idle = 0.0 if sent else idle + 0.05
            await asyncio.sleep(0.05)

    async def steer(self, campaign_id: str, directive: dict[str, Any]) -> dict[str, Any]:
        """A directive is validated exactly as any policy's decision would be."""
        pol = self.managers[campaign_id].policy
        target = getattr(pol, "inner", pol)
        if not hasattr(target, "steer"):
            return {"accepted": False, "reason": "campaign is not under external control"}
        target.steer(directive)
        self.emit(campaign_id, "steered", {"directive": directive})
        return {"accepted": True}

    async def pause(self, campaign_id: str) -> None:
        self.managers[campaign_id].executor.pause()
        self.emit(campaign_id, "paused", {})

    async def resume(self, campaign_id: str) -> None:
        self.managers[campaign_id].executor.resume()
        self.emit(campaign_id, "resumed", {})

    async def stop(self, campaign_id: str, reason: str) -> None:
        """Ends any campaign, not only an externally steered one.

        This used to work by poking `ExternalPolicy.steer`, so it silently did nothing
        for models A, B and D - the only policies with no caller to poke. Termination
        belongs to the executor, which owns the state the decision rests on.
        """
        mgr = self.managers[campaign_id]
        pol = getattr(mgr.policy, "inner", mgr.policy)
        if hasattr(pol, "steer"):
            pol.steer({"kind": "stop", "reason": reason})   # unblock a waiting caller
        mgr.executor.request_stop(reason)
        self.emit(campaign_id, "stop_requested", {"reason": reason})

    async def artifacts(self, campaign_id: str, selector: str = "front") -> list[dict[str, Any]]:
        m = self.managers[campaign_id]
        nodes = m.observe().pareto_front if selector == "front" else list(m.tree)
        return [{"node": n.id, "qc": n.qc.verdict.value,
                 "properties": {k: p.value for k, p in n.properties.items()}}
                for n in nodes]

    async def provenance(self, campaign_id: str, kind: str) -> list[dict[str, Any]]:
        return list(self.managers[campaign_id].prov.read(kind))

    # -- runs ----------------------------------------------------------------
    async def submit_run(self, campaign_id: str,
                         intent: dict[str, Any]) -> dict[str, Any]:
        """Admit one experiment. Answers accepted-with-an-id, or refused-with-a-reason.

        Synchronous on purpose. Accepting everything and reporting rejections later on
        the event stream would sever a rejection from the request that caused it, and
        there would be nothing left to bound retries against.
        """
        from ..core.decision import ExperimentIntent
        from ..core.session import CampaignStopped, SubmissionRejected
        mgr = self.managers[campaign_id]
        try:
            run_id = await mgr.runs.submit(ExperimentIntent(**intent))
        except SubmissionRejected as rejected:
            self.emit(campaign_id, "run_rejected",
                      {"gate": rejected.failure.gate,
                       "reason": rejected.failure.reason,
                       "transient": rejected.failure.transient})
            return {"accepted": False, "failure": rejected.failure.model_dump()}
        except CampaignStopped as stopped:
            return {"accepted": False, "reason": str(stopped)}
        self.emit(campaign_id, "run_submitted", {"run": run_id})
        return {"accepted": True, "run_id": run_id}

    async def list_runs(self, campaign_id: str,
                        state: str | None = None) -> list[dict[str, Any]]:
        from ..core.results import RunState
        runs = self.managers[campaign_id].runs.list_runs(
            RunState(state) if state else None)
        return [r.model_dump(mode="json") for r in runs]

    async def run_result(self, campaign_id: str,
                         run_id: str) -> dict[str, Any] | None:
        """A finished run's result - from memory, or from the durable log."""
        outcome = self.managers[campaign_id].runs.outcome(run_id)
        return outcome.model_dump(mode="json") if outcome else None

    async def await_run_result(self, campaign_id: str, run_id: str,
                               wait_s: float = 30.0) -> dict[str, Any]:
        """The BLOCKING variant: wait up to `wait_s` for a run to finish.

        `run_result` alone forces every caller to poll, and polling is what an
        out-of-process reasoner must not have to do - `CampaignSession.result` blocks,
        so the operation behind it has to be able to block too.

        No new mechanism is introduced here. `CampaignExecutor.result` already races the
        run's future against the halt event and raises `CampaignStopped`; this is that
        call with a deadline on it, so the three answers a waiter can get in-process -
        the outcome, "the campaign ended", or nothing yet - are the three it gets here.
        The deadline exists because the transport carrying this cannot hold a socket
        open indefinitely; a caller that still wants the answer simply asks again.
        """
        from ..core.session import CampaignStopped
        mgr = self.managers[campaign_id]
        if (known := mgr.runs.outcome(run_id)) is not None:
            return {"state": "ready", "outcome": known.model_dump(mode="json")}
        try:
            outcome = await asyncio.wait_for(mgr.runs.result(run_id), wait_s)
        except asyncio.TimeoutError:
            # `wait_for` cancels the wrapper, never the run's own future - the waiter
            # table is untouched and the next call picks up where this one left off.
            return {"state": "pending"}
        except CampaignStopped as stopped:
            return {"state": "stopped", "reason": str(stopped)}
        except KeyError:
            return {"state": "unknown"}
        return {"state": "ready", "outcome": outcome.model_dump(mode="json")}

    async def status(self, campaign_id: str, run_id: str) -> RunStatus:
        return self.managers[campaign_id].runs.status(run_id)

    async def inflight(self, campaign_id: str) -> list[RunStatus]:
        return self.managers[campaign_id].runs.inflight()

    async def cancel_run(self, campaign_id: str, run_id: str) -> dict[str, Any]:
        self.managers[campaign_id].runs.cancel(run_id)
        self.emit(campaign_id, "run_cancel_requested", {"run": run_id})
        # Advisory, and says so: queued work is reclaimed, running work is not, and the
        # backend does not report which happened.
        return {"requested": True, "advisory": True}

    # -- the tree ------------------------------------------------------------
    async def backtrack(self, campaign_id: str, node_id: str,
                        rationale: str = "") -> str:
        """Branch a new lineage from an earlier node. Returns the new node id.

        Non-destructive: the tree is append-only, so backtracking adds a sibling and
        deletes nothing.
        """
        new_id = self.managers[campaign_id].executor.backtrack(node_id, rationale)
        self.emit(campaign_id, "backtracked",
                  {"from": node_id, "new": new_id, "rationale": rationale})
        return new_id

    async def request_human(self, campaign_id: str, question: str,
                            context: dict[str, Any] | None = None) -> None:
        self.managers[campaign_id].executor.request_human(question, context)
        self.emit(campaign_id, "human_requested", {"question": question})

    async def ingest_measurement(self, campaign_id: str, node_id: str,
                                 prop: Property) -> dict[str, Any]:
        """Out-of-band P8 arrival. Accepted even after termination - the campaign record
        is append-only and outlives execution (decision 0012)."""
        m = self.managers[campaign_id]
        if node_id not in m.tree.nodes:
            return {"accepted": False, "reason": f"unknown node {node_id}"}
        ok = m.tree.ingest_measurement(node_id, prop)
        m.prov.append("results", {"event": "measurement", "node": node_id,
                                  "property": prop.name, "value": prop.value,
                                  "source": prop.source.model_dump(), "accepted": ok})
        self.emit(campaign_id, "measurement_ingested",
                  {"node": node_id, "property": prop.name, "accepted": ok})
        return {"accepted": ok}
