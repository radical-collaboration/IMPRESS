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

    async def fake_make_engine(kind, config, work_dir=""):
        calls.append((kind, config, work_dir))
        return ("flow", "backend")

    monkeypatch.setattr(backend_mod, "make_engine", fake_make_engine)
    result = await make_engine_bounded("concurrent", {"workers": 1}, timeout_s=0,
                                       heartbeat_s=30, work_dir="/run/root")
    assert result == ("flow", "backend")
    assert calls == [("concurrent", {"workers": 1}, "/run/root")]


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


async def test_a_bounded_engine_actually_runs_a_task(tmp_path):
    """A bounded engine must be a LIVE engine - built on the caller's own loop.

    Fails against the pre-fix `make_engine_bounded`, which built the engine on a
    throwaway loop inside the helper thread: `flow` comes back looking healthy and the
    task future never completes.
    """
    flow, _backend = await make_engine_bounded(
        "concurrent", {"executor": "thread", "workers": 2},
        timeout_s=30, heartbeat_s=5, work_dir=str(tmp_path))
    try:
        assert flow.loop is asyncio.get_running_loop(), \
            "the engine must belong to the loop that will submit to it"
        assert list(tmp_path.glob("asyncflow.session.*")), \
            "the session dir belongs under work_dir, not in whatever the CWD happens to be"

        @flow.function_task
        async def forty_two():                    # asyncflow requires `async def`
            return 42

        assert await asyncio.wait_for(forty_two(), timeout=20) == 42
    finally:
        await flow.shutdown()


async def test_a_bounded_non_cheap_backend_is_still_built_on_the_caller_loop(monkeypatch,
                                                                          tmp_path):
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
                                               heartbeat_s=5, work_dir=str(tmp_path))
    try:
        assert flow.loop is asyncio.get_running_loop()
        assert list(tmp_path.glob("asyncflow.session.*")), \
            "the threaded path must honour work_dir too - it builds its own engine"

        @flow.function_task
        async def hello():
            return "hello"

        assert await asyncio.wait_for(hello(), timeout=20) == "hello"
    finally:
        await flow.shutdown()


# ── teardown ──────────────────────────────────────────────────────────────────

class _NeverShutsDown:
    """An engine whose `shutdown()` hangs, the way IMPRESS job 22491438's did."""

    def __init__(self):
        self.entered = asyncio.Event()

    async def shutdown(self):
        self.entered.set()
        await asyncio.Event().wait()          # never returns


async def _executor_with(flow, timeout_s):
    from impress_a.compose.validate import SiteCaps
    from impress_a.runtime.executor import CampaignExecutor, CampaignSpec

    spec = CampaignSpec(campaign_id="t-teardown", goal="g", objectives=[],
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", root="/tmp/impress_a_tests",
                        backend_shutdown_timeout_s=timeout_s)
    ex = CampaignExecutor(spec, policy=None)
    ex.flow = flow
    return ex


async def test_a_hung_teardown_is_abandoned_rather_than_holding_the_allocation():
    """The campaign is DONE by the time shutdown runs; a hang there is pure waste.

    Measured on the reference pipeline (IMPRESS job 22491438): `flow.shutdown()` never
    returned once every pipeline had finished, and the job sat 60 minutes before being
    cancelled by hand - ~64 GPU-hours, 37% of its billed total, spent after the science
    was already done. Without the bound this test hangs forever.
    """
    flow = _NeverShutsDown()
    ex = await _executor_with(flow, timeout_s=0.5)

    await asyncio.wait_for(ex._shutdown_engine(), timeout=10)

    assert flow.entered.is_set(), "shutdown must actually have been attempted"


async def test_a_hung_teardown_does_not_fail_the_campaign():
    """Giving up on teardown is not an error - results are already durable.

    Raising here would turn a campaign that produced everything it was asked for into a
    failed one, which is strictly worse than leaking backend state in a process that is
    about to exit.
    """
    ex = await _executor_with(_NeverShutsDown(), timeout_s=0.5)
    assert await asyncio.wait_for(ex._shutdown_engine(), timeout=10) is None


async def test_teardown_is_unbounded_by_default():
    """0 disables, matching `backend_startup_timeout_s` - no existing campaign changes."""
    done = asyncio.Event()

    class _Fine:
        async def shutdown(self):
            done.set()

    ex = await _executor_with(_Fine(), timeout_s=0.0)
    await asyncio.wait_for(ex._shutdown_engine(), timeout=10)
    assert done.is_set()
