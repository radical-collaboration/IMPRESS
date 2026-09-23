"""`make_engine_bounded` - bounding a Dragon-style synchronous backend construction.

Job 22318678: rhapsody's Dragon backend builds `Batch()` synchronously in its own
constructor, with no `await` points - a stall there blocks the event loop entirely (no
heartbeat, no timeout, nothing) until the whole allocation's walltime is spent. These
tests stand a fake backend construction in for `Batch()`: one that blocks its OWN event
loop (in its own thread) exactly the way a real hang would, and check that the CALLING
event loop - and therefore the heartbeat and the timeout - are unaffected by it.
"""
import asyncio
import time

import pytest

from impress_a.exec import backend as backend_mod
from impress_a.exec.backend import BackendConstructionTimeout, make_engine_bounded


async def test_disabled_by_default_calls_make_engine_directly(monkeypatch):
    calls = []

    async def fake_make_engine(kind, config):
        calls.append((kind, config))
        return ("flow", "backend")

    monkeypatch.setattr(backend_mod, "make_engine", fake_make_engine)
    result = await make_engine_bounded("concurrent", {"workers": 1}, timeout_s=0,
                                       heartbeat_s=30)
    assert result == ("flow", "backend")
    assert calls == [("concurrent", {"workers": 1})]


async def test_a_stalled_construction_times_out_loudly_instead_of_hanging(monkeypatch,
                                                                          caplog):
    def blocking_sleep():
        # Blocks its OWN thread's event loop synchronously - exactly what Dragon's
        # Batch() does to the process that calls it. Never returns.
        time.sleep(60)

    async def hangs_forever(kind, config):
        await asyncio.to_thread(blocking_sleep)
        return ("flow", "backend")            # pragma: no cover - never reached

    monkeypatch.setattr(backend_mod, "make_engine", hangs_forever)

    t0 = time.monotonic()
    with caplog.at_level("INFO"), pytest.raises(BackendConstructionTimeout):
        await asyncio.wait_for(
            make_engine_bounded("dragon", {}, timeout_s=0.3, heartbeat_s=0.1),
            timeout=5)
    elapsed = time.monotonic() - t0

    assert elapsed < 2.0, \
        "the CALLING event loop must not be blocked by the stalled construction"
    assert "still constructing" in caplog.text, \
        "the heartbeat must fire even while construction is stalled"
