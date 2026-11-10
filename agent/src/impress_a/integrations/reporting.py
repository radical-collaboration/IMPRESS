"""Tell something outside this process what a campaign is doing, as it does it.

The delivery half of being a subordinate workflow (decision 0014). An enclosing campaign
manager needs observations on an ongoing basis, and before this there was no way to give it
any: the only hook out of a running campaign was one unguarded `prov_sink` slot carrying raw
provenance records, and an observation was computed on demand and discarded.

**Nothing here touches the executor.** The pump reads `observe()`, which is synchronous and
await-free by invariant, and awaits the sink outside it - so no `await` ever enters a mutating
block and the one-writer property is untouched. The precedent is already in the tree and says
exactly this: `cli._heartbeat`'s docstring notes that "its mutating blocks are await-free by
invariant, so a heartbeat scheduled between them can never see a torn state." This is that
heartbeat with a sink instead of a logger.

`CycleSink` names no enclosing manager's vocabulary, which is what makes a second superstrate
an adapter rather than a redesign - an in-process block function, an HTTP poller and a
subprocess reporting over Redis are three sinks, not three payloads.

One consequence to know about, recorded as backlog G19: the pump calls `observe()`, and
`observe()` calls `touch()`, which refreshes the clock `control_liveness_timeout_s` reads to
decide a caller has vanished. A campaign with a pump attached therefore cannot detect a lost
caller by silence, and liveness has to run the other way - from the enclosing manager's own
staleness bound, which is why the offer declares `report_interval_s` for it to be a multiple
of.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..core.decision import CampaignDigest

log = logging.getLogger("impress_a.reporting")

#: What a caller may send back. Deliberately two words and not an enum shared with any
#: particular superstrate: an adapter translates its own vocabulary into these.
PAUSE, RESUME = "pause", "resume"


@runtime_checkable
class CycleSink(Protocol):
    """Where a digest goes, and where a caller's signals come from."""

    async def report(self, digest: CampaignDigest) -> None:
        """Deliver one digest. Must not raise; the bridge guards it anyway."""
        ...

    async def poll(self) -> str | None:
        """`PAUSE`, `RESUME`, or None. Non-blocking."""
        ...


class JsonlSink:
    """The default sink: one JSON line per digest, under the campaign's own root.

    Deliberately NOT under `provenance/`. The executor is the only writer of files there, and
    a tenth provenance kind would make a report look like a campaign record when it is really
    a record of what somebody else was told. Before this, a report nobody received was simply
    lost; a campaign can now be asked afterwards what it reported and when.
    """

    def __init__(self, path: str | Path, name: str = "reports") -> None:
        self.path = Path(path) / "reports" / f"{name}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.count = 0

    async def report(self, digest: CampaignDigest) -> None:
        record = {"ts": time.time(), **digest.model_dump(mode="json")}
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        self.count += 1

    async def poll(self) -> str | None:
        return None


class _Fanout:
    """Several sinks as one, each guarded, so one broken listener cannot silence the rest."""

    def __init__(self, sinks: list[Any]) -> None:
        self.sinks = list(sinks)
        self.dropped = 0

    async def report(self, digest: CampaignDigest) -> None:
        for sink in self.sinks:
            await _guarded(sink.report(digest), sink, "report", self)

    async def poll(self) -> str | None:
        for sink in self.sinks:
            signal = await _guarded(sink.poll(), sink, "poll", self)
            if signal:
                return signal
        return None


async def _guarded(awaitable: Any, sink: Any, what: str, owner: Any) -> Any:
    """Run a sink call and swallow its failure.

    A sink is somebody else's code reaching into a process that is holding an allocation. The
    campaign is the thing with the GPUs; a listener that raises must cost a log line and a
    counter, never the run. The same rule `policy/reasoning._record` has always applied, and
    that `executor._log` now applies to its own provenance listeners (backlog G18).
    """
    try:
        return await awaitable
    except Exception as broken:                  # noqa: BLE001 - see the docstring
        owner.dropped = getattr(owner, "dropped", 0) + 1
        log.warning("sink %r failed on %s (%d dropped): %r",
                    type(sink).__name__, what, owner.dropped, broken)
        return None


class Bridge:
    """Polls the campaign's own snapshot and reports when something has landed.

    Triggered by `observe().seq` - the absorption watermark - advancing, and NOT by `cycle`.
    `cycle` is incremented in `_dispatch`, so it counts submissions: a report fired there
    would carry no results. `seq` advances once per lineage absorbed, which is exactly when
    there is something new to say. Polling a monotone integer is race-free and needs nothing
    added to the executor; the alternative, `_activity`, is cleared by `pump` and a second
    consumer would race it.

    `period_s` is a FLOOR, not the only trigger: a cycle of the real chain runs minutes of
    tasks with nothing absorbed, and a caller's staleness bound has to be satisfiable while
    that happens.
    """

    def __init__(self, manager: Any, sink: Any, *, period_s: float = 30.0,
                 tick_s: float = 0.5) -> None:
        self.mgr = manager
        self.sink = sink if not isinstance(sink, list) else _Fanout(sink)
        self.period_s = period_s
        self.tick_s = min(tick_s, period_s)
        self.reported = 0
        self.paused = False
        self._last_seq = -1
        self._last_at = 0.0

    def digest(self, **kw: Any) -> CampaignDigest:
        """One digest, taken between the executor's mutating blocks."""
        return self.mgr.observe().digest(**kw)

    async def report_once(self, **kw: Any) -> CampaignDigest:
        digest = self.digest(**kw)
        await _guarded(self.sink.report(digest), self.sink, "report", self)
        self.reported += 1
        self._last_seq, self._last_at = digest.seq, time.monotonic()
        return digest

    async def run(self, stop: asyncio.Event) -> None:
        """Report until `stop` is set. Never raises into the campaign."""
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self.tick_s)
            if stop.is_set():
                return
            await self._signals()
            try:
                seq = self.mgr.observe().seq
            except Exception as e:               # noqa: BLE001 - diagnostics only
                log.warning("bridge: could not snapshot the campaign: %r", e)
                continue
            landed = seq != self._last_seq
            stale = (time.monotonic() - self._last_at) >= self.period_s
            if landed or stale:
                await self.report_once(status="paused" if self.paused else "running")

    async def _signals(self) -> None:
        """Act on a caller's PAUSE/RESUME.

        Pause gates ADMISSION only. In-flight runs are allowed to finish, because
        cancellation is advisory - the concurrent backend's `Future.cancel()` returns False
        once a callable has started, and asyncflow discards that answer - so a reclaimed GPU
        is not something this system can promise. A paused campaign therefore keeps spending
        for up to one cycle, which the offer declares as `pause_semantics`.
        """
        signal = await _guarded(self.sink.poll(), self.sink, "poll", self)
        if signal == PAUSE and not self.paused:
            self.mgr.executor.pause()
            self.paused = True
            log.info("bridge: paused by the caller - admission stops, in-flight work runs on")
            await self.report_once(status="paused")
        elif signal == RESUME and self.paused:
            self.mgr.executor.resume()
            self.paused = False
            log.info("bridge: resumed by the caller")
            await self.report_once(status="running")


async def run_with_sink(manager: Any, sink: Any, *, period_s: float = 30.0) -> Any:
    """Run a campaign to completion with a bridge attached. Returns its `CampaignResult`.

    One report before the campaign starts, so a caller has a liveness anchor before any work
    exists to describe, and one after it ends - which must be the real one, because the stores
    a caller reads these through keep only the last value per workflow. Everything between is
    the bridge's own cadence.
    """
    bridge = Bridge(manager, sink, period_s=period_s)
    await bridge.report_once(status="starting")
    stop = asyncio.Event()
    pump = asyncio.create_task(bridge.run(stop))
    try:
        result = await manager.run()
    except BaseException:
        stop.set()
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        with contextlib.suppress(Exception):
            await bridge.report_once(status="aborted")
        raise
    stop.set()
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)
    await bridge.report_once(status="stopped",
                             stop_reason=getattr(result, "stop_reason", "") or "")
    return result
