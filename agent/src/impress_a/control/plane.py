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


class Event(dict):
    """An append-only stream record with a resumable cursor."""


class CampaignControlPlane(Protocol):
    async def submit(self, spec: Any) -> str: ...
    async def observe(self, campaign_id: str) -> CampaignObservation: ...
    async def events(self, campaign_id: str, since: int = 0) -> AsyncIterator[Event]: ...
    async def steer(self, campaign_id: str, directive: dict[str, Any]) -> dict[str, Any]: ...
    async def pause(self, campaign_id: str) -> None: ...
    async def resume(self, campaign_id: str) -> None: ...
    async def stop(self, campaign_id: str, reason: str) -> None: ...
    async def artifacts(self, campaign_id: str, selector: str) -> list[dict[str, Any]]: ...
    async def provenance(self, campaign_id: str, kind: str) -> list[dict[str, Any]]: ...
    async def ingest_measurement(self, campaign_id: str, node_id: str,
                                 prop: Property) -> dict[str, Any]: ...


class InProcessControlPlane:
    """Reference adapter. Drives a CampaignManager in the same process.

    Used by HITL agents co-located in the job, and by the test suite. HTTP+SSE and MCP
    adapters translate transport only.
    """

    def __init__(self) -> None:
        self.managers: dict[str, Any] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._events: dict[str, list[Event]] = {}
        self._paused: dict[str, asyncio.Event] = {}

    def register(self, manager) -> str:
        cid = manager.spec.campaign_id
        self.managers[cid] = manager
        self._events.setdefault(cid, [])
        ev = asyncio.Event(); ev.set()
        self._paused[cid] = ev
        manager.prov_sink = self.emit
        return cid

    def emit(self, cid: str, kind: str, payload: dict[str, Any]) -> None:
        self._events.setdefault(cid, []).append(Event(seq=len(self._events[cid]),
                                                      kind=kind, **payload))

    async def submit(self, spec: Any) -> str:
        raise NotImplementedError("construct a CampaignManager and register() it")

    async def observe(self, campaign_id: str) -> CampaignObservation:
        return self.managers[campaign_id].observe()

    async def events(self, campaign_id: str, since: int = 0) -> AsyncIterator[Event]:
        for e in self._events.get(campaign_id, [])[since:]:
            yield e

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
        self._paused[campaign_id].clear()
        self.emit(campaign_id, "paused", {})

    async def resume(self, campaign_id: str) -> None:
        self._paused[campaign_id].set()
        self.emit(campaign_id, "resumed", {})

    async def stop(self, campaign_id: str, reason: str) -> None:
        pol = self.managers[campaign_id].policy
        target = getattr(pol, "inner", pol)
        if hasattr(target, "steer"):
            target.steer({"kind": "stop", "reason": reason})
        self.emit(campaign_id, "stop_requested", {"reason": reason})

    async def artifacts(self, campaign_id: str, selector: str = "front") -> list[dict[str, Any]]:
        m = self.managers[campaign_id]
        nodes = m.observe().pareto_front if selector == "front" else list(m.tree)
        return [{"node": n.id, "qc": n.qc.verdict.value,
                 "properties": {k: p.value for k, p in n.properties.items()}}
                for n in nodes]

    async def provenance(self, campaign_id: str, kind: str) -> list[dict[str, Any]]:
        return list(self.managers[campaign_id].prov.read(kind))

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
