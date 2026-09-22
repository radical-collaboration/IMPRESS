"""HTTP adapter for the control plane.

This is the transport that lets the reasoner leave the allocation: the executor stays
where the GPUs and the toolkit are, and whatever is steering the campaign talks to it
over a socket. Everything the wire carries is already serializable - that was Stage 4's
whole point - so this module translates transport and nothing else.

**No operation here is absent from the core protocol** (ADR 0007). The routes are a
mechanical rendering of `CampaignControlPlane`; if an operation is missing from the
protocol it must not appear here, and if it is added there it belongs here too.

Admission is SYNCHRONOUS: `POST /runs` answers `202` with a run id or `409` with the
`ValidationFailure` that refused it. Accepting everything and reporting rejections later
on the event stream would sever a rejection from the request that caused it, and leave
nothing to bound retries against.

Deliberately built on `asyncio.start_server` rather than a web framework. The dependency
list is already heavy, and this speaks a small, fixed dialect: JSON request/response plus
one event stream, on loopback, for a single trusted client. It is NOT a public-facing
server - there is no auth, no TLS, and no request-size limit beyond the one below - and
it should be bound to localhost or a private interface only.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..core.artifacts import Property
from ..core.decision import CampaignObservation
from .plane import Event

#: Requests larger than this are refused rather than buffered. An intent is a few
#: hundred bytes; anything approaching this is a mistake or an attack.
MAX_BODY_BYTES = 1 << 20

_STATUS = {200: "OK", 202: "Accepted", 400: "Bad Request", 404: "Not Found",
           405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
           500: "Internal Server Error"}


class _Request:
    __slots__ = ("body", "headers", "method", "path", "query")

    def __init__(self, method: str, target: str, headers: dict[str, str], body: bytes):
        parsed = urlparse(target)
        self.method = method
        self.path = parsed.path.rstrip("/") or "/"
        self.query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.headers = headers
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body or b"{}")


class ControlPlaneServer:
    """Serves a `CampaignControlPlane` over HTTP."""

    def __init__(self, plane: Any, host: str = "127.0.0.1", port: int = 0):
        self.plane, self.host, self.port = plane, host, port
        self._server: asyncio.AbstractServer | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("server is not started")
        host, port = self._server.sockets[0].getsockname()[:2]
        return f"http://{host}:{port}"

    async def start(self) -> ControlPlaneServer:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> "ControlPlaneServer":  # noqa: PYI034
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # -- transport ----------------------------------------------------------
    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, *_ = lines[0].split(" ")
        headers = {k.lower(): v.strip()
                   for k, _, v in (h.partition(":") for h in lines[1:] if h)}

        length = int(headers.get("content-length", "0") or 0)
        if length > MAX_BODY_BYTES:
            await self._send(writer, 413, {"error": "body too large"})
            return
        body = await reader.readexactly(length) if length else b""
        req = _Request(method, target, headers, body)

        try:
            if req.path.endswith("/events"):
                return await self._events(req, writer)
            status, payload = await self._route(req)
        except json.JSONDecodeError as e:
            status, payload = 400, {"error": f"malformed JSON: {e}"}
        except KeyError as e:
            status, payload = 404, {"error": f"unknown: {e}"}
        except NotImplementedError as e:
            status, payload = 405, {"error": str(e)}
        except Exception as e:  # noqa: BLE001 - a handler fault must not kill the server
            status, payload = 500, {"error": f"{type(e).__name__}: {e}"}
        await self._send(writer, status, payload)

    async def _send(self, writer: asyncio.StreamWriter, status: int,
                    payload: Any) -> None:
        body = json.dumps(payload, default=str).encode()
        writer.write(
            f"HTTP/1.1 {status} {_STATUS.get(status, 'OK')}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n".encode() + body)
        try:
            await writer.drain()
        finally:
            writer.close()

    async def _events(self, req: _Request, writer: asyncio.StreamWriter) -> None:
        """One operation, two representations: a cursor-paged page, or a live stream.

        Streaming polls, because the in-process plane's `events()` yields the records it
        already has and returns - it does not tail. A genuinely push-based source would
        slot in here without changing the wire format.
        """
        cid = req.path.split("/")[2]
        since = int(req.query.get("since", "0"))
        if "text/event-stream" not in req.headers.get("accept", ""):
            page = [dict(e) async for e in self.plane.events(cid, since)]
            return await self._send(writer, 200, page)

        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                     b"Cache-Control: no-cache\r\nConnection: close\r\n\r\n")
        cursor, idle = since, 0.0
        try:
            while idle < float(req.query.get("timeout", "30")):
                sent = 0
                async for e in self.plane.events(cid, cursor):
                    writer.write(b"data: " + json.dumps(dict(e), default=str).encode()
                                 + b"\n\n")
                    cursor, sent = int(e["seq"]) + 1, sent + 1
                await writer.drain()
                idle = 0.0 if sent else idle + 0.1
                await asyncio.sleep(0.1)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    # -- the protocol, rendered as routes ------------------------------------
    async def _route(self, req: _Request) -> tuple[int, Any]:
        parts = [p for p in req.path.split("/") if p]
        if not parts or parts[0] != "campaigns":
            raise KeyError(req.path)

        if len(parts) == 1:                                   # /campaigns
            if req.method != "POST":
                raise NotImplementedError("POST /campaigns to submit a campaign")
            return 202, {"campaign_id": await self.plane.submit(req.json())}

        cid, rest = parts[1], parts[2:]
        p = self.plane

        if not rest:
            return 200, {"campaign_id": cid}
        head = rest[0]

        if head == "observe":
            obs: CampaignObservation = await p.observe(cid)
            return 200, obs.model_dump(mode="json")
        if head == "steer":
            return 200, await p.steer(cid, req.json())
        if head in ("pause", "resume"):
            await getattr(p, head)(cid)
            return 200, {head + "d": True}
        if head == "stop":
            await p.stop(cid, req.json().get("reason", "stopped over http"))
            return 200, {"stopped": True}
        if head == "artifacts":
            return 200, await p.artifacts(cid, req.query.get("selector", "front"))
        if head == "provenance":
            return 200, await p.provenance(cid, req.query.get("kind", "graphs"))
        if head == "measurements":
            body = req.json()
            return 200, await p.ingest_measurement(
                cid, body["node_id"], Property(**body["property"]))

        if head == "runs":
            if len(rest) == 1:
                if req.method == "POST":
                    # Synchronous admission: accepted, or refused with the reason.
                    out = await p.submit_run(cid, req.json())
                    return (202, out) if out.get("accepted") else (409, out)
                return 200, await p.list_runs(cid, req.query.get("state"))
            run_id = rest[1]
            if len(rest) > 2 and rest[2] == "cancel":
                return 200, await p.cancel_run(cid, run_id)
            result = await p.run_result(cid, run_id)
            if result is None:
                return 404, {"error": f"no result for {run_id}"}
            return 200, result

        raise KeyError(req.path)


class ControlPlaneClient:
    """A `CampaignControlPlane` that happens to live at the other end of a socket.

    Same protocol, same argument and return types - which is what makes the reasoner
    indifferent to whether the executor is in this process or on another machine.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        import httpx  # imported here so the module loads without the `http` extra

        self._c = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def aclose(self) -> None:
        await self._c.aclose()

    async def __aenter__(self) -> "ControlPlaneClient":  # noqa: PYI034
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def submit(self, spec: Any) -> str:
        r = await self._c.post("/campaigns", json=spec)
        return r.json()["campaign_id"]

    async def observe(self, campaign_id: str) -> CampaignObservation:
        r = await self._c.get(f"/campaigns/{campaign_id}/observe")
        return CampaignObservation(**r.json())

    async def events(self, campaign_id: str, since: int = 0) -> AsyncIterator[Event]:
        r = await self._c.get(f"/campaigns/{campaign_id}/events",
                              params={"since": since})
        for e in r.json():
            yield Event(**e)

    async def steer(self, campaign_id: str, directive: dict[str, Any]) -> dict[str, Any]:
        return (await self._c.post(f"/campaigns/{campaign_id}/steer",
                                   json=directive)).json()

    async def pause(self, campaign_id: str) -> None:
        await self._c.post(f"/campaigns/{campaign_id}/pause", json={})

    async def resume(self, campaign_id: str) -> None:
        await self._c.post(f"/campaigns/{campaign_id}/resume", json={})

    async def stop(self, campaign_id: str, reason: str) -> None:
        await self._c.post(f"/campaigns/{campaign_id}/stop", json={"reason": reason})

    async def artifacts(self, campaign_id: str,
                        selector: str = "front") -> list[dict[str, Any]]:
        return (await self._c.get(f"/campaigns/{campaign_id}/artifacts",
                                  params={"selector": selector})).json()

    async def provenance(self, campaign_id: str, kind: str) -> list[dict[str, Any]]:
        return (await self._c.get(f"/campaigns/{campaign_id}/provenance",
                                  params={"kind": kind})).json()

    async def ingest_measurement(self, campaign_id: str, node_id: str,
                                 prop: Property) -> dict[str, Any]:
        return (await self._c.post(
            f"/campaigns/{campaign_id}/measurements",
            json={"node_id": node_id,
                  "property": prop.model_dump(mode="json")})).json()

    # -- runs ---------------------------------------------------------------
    async def submit_run(self, campaign_id: str,
                         intent: dict[str, Any]) -> dict[str, Any]:
        return (await self._c.post(f"/campaigns/{campaign_id}/runs",
                                   json=intent)).json()

    async def list_runs(self, campaign_id: str,
                        state: str | None = None) -> list[dict[str, Any]]:
        return (await self._c.get(f"/campaigns/{campaign_id}/runs",
                                  params={"state": state} if state else None)).json()

    async def run_result(self, campaign_id: str,
                         run_id: str) -> dict[str, Any] | None:
        r = await self._c.get(f"/campaigns/{campaign_id}/runs/{run_id}")
        return None if r.status_code == 404 else r.json()

    async def cancel_run(self, campaign_id: str, run_id: str) -> dict[str, Any]:
        return (await self._c.post(
            f"/campaigns/{campaign_id}/runs/{run_id}/cancel", json={})).json()
