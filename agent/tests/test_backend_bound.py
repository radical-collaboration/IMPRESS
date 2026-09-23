"""`make_engine_bounded` - bounding a Dragon-style synchronous backend construction.

Job 22318678: rhapsody's Dragon backend builds `Batch()` synchronously in its own
constructor, with no `await` points - a stall there blocks the event loop entirely (no
heartbeat, no timeout, nothing) until the whole allocation's walltime is spent. These
tests stand a fake backend construction in for `Batch()`: one that blocks its OWN event
loop (in its own thread) exactly the way a real hang would, and check that the CALLING
event loop - and therefore the heartbeat and the timeout - are unaffected by it.

Jobs 22328172/22328262: the bound itself then caused a worse hang. It ran ALL of
`make_engine` on that helper thread under `asyncio.run`, so the returned `WorkflowEngine`
belonged to a loop that was closed on the way out and its `run-component` dispatch task
had been cancelled. The campaign submitted its first task and waited forever, with no
error anywhere. Hence `test_a_bounded_engine_actually_runs_a_task`: the only way to tell
a live engine from a dead one is to put work through it.
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
    def blocking_sleep(kind, config):
        # Blocks its OWN thread synchronously - exactly what Dragon's Batch() does to
        # whatever thread calls it, from inside the backend constructor. Never returns.
        time.sleep(60)
        return "backend"                          # pragma: no cover - never reached

    monkeypatch.setattr(backend_mod, "_construct_backend_sync", blocking_sleep)

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


async def test_a_bounded_engine_actually_runs_a_task():
    """A bounded engine must be a LIVE engine - built on the caller's own loop.

    Fails against the pre-fix `make_engine_bounded`, which built the engine on a
    throwaway loop inside the helper thread: `flow` comes back looking healthy and the
    task future never completes.
    """
    flow, _backend = await make_engine_bounded(
        "concurrent", {"executor": "thread", "workers": 2},
        timeout_s=30, heartbeat_s=5)
    try:
        assert flow.loop is asyncio.get_running_loop(), \
            "the engine must belong to the loop that will submit to it"

        @flow.function_task
        async def forty_two():                    # asyncflow requires `async def`
            return 42

        assert await asyncio.wait_for(forty_two(), timeout=20) == 42
    finally:
        await flow.shutdown()


async def test_a_bounded_non_cheap_backend_is_still_built_on_the_caller_loop(monkeypatch):
    """The offloaded path (a real `dragon`-like kind) must end up on our loop too.

    `concurrent` short-circuits to `make_engine`, so it never exercises the daemon
    thread. This stands a cheap backend in for an expensive one under a fake kind name,
    forcing the full bounded path: sync construct off-thread, `await` + engine here.
    """
    real_sync = backend_mod._construct_backend_sync

    def fake_sync(kind, config):
        assert kind == "pretend_dragon"
        return real_sync("concurrent", {"executor": "thread", "workers": 2})

    monkeypatch.setattr(backend_mod, "_construct_backend_sync", fake_sync)

    flow, _backend = await make_engine_bounded("pretend_dragon", {}, timeout_s=30,
                                               heartbeat_s=5)
    try:
        assert flow.loop is asyncio.get_running_loop()

        @flow.function_task
        async def hello():
            return "hello"

        assert await asyncio.wait_for(hello(), timeout=20) == "hello"
    finally:
        await flow.shutdown()
