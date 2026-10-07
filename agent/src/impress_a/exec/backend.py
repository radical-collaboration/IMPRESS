"""Backend construction.

Phase 2 finding: asyncflow ships only Noop/Local; every real backend lives in rhapsody
and must be imported directly. We keep rhapsody's NAME out of our source by resolving it
through `rhapsody.backends.get_backend(name)` from site config.

GOTCHA (verified 0.5.0): rhapsody backends are AWAITABLE - `__await__` triggers
`_async_init()`, which registers the backend's task states. Constructing one
synchronously leaves it unregistered and fails later with a confusing
"Backend 'x' not registered" from StateMapper.

GOTCHA (verified 0.5.1, jobs 22328172/22328262): a `WorkflowEngine` and a backend's
async init BELONG TO THE LOOP THEY ARE BUILT ON. `WorkflowEngine.__init__` captures
`self.loop = get_event_loop_or_raise(...)` from the running loop and
`_start_async_components` puts its `run-component` dispatch task on it; the rhapsody
backend captures its own loop for cross-thread result delivery. Build either on a
throwaway loop - e.g. `asyncio.run(...)` on a helper thread - and the caller gets an
engine whose dispatcher was cancelled when that loop closed: every task submitted to it
hangs forever, silently. Only the genuinely blocking SYNCHRONOUS construction step
(`_construct_backend_sync`) may be offloaded; the `await` steps run on the caller's loop.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

# Kinds whose constructor is pure bookkeeping - a pool object or an empty shell. None of
# them can stall, so bounding them buys nothing and would only add a thread hop.
_CHEAP_KINDS = frozenset({"concurrent", "local_process", "mock", "noop", "local"})


class BackendConstructionTimeout(RuntimeError):
    """`make_engine` did not return within its configured bound.

    Most likely cause (verified against a real 2-hour hang, job 22318678):
    rhapsody's Dragon backend builds `Batch()` synchronously in its own constructor - the
    results DDict, GPU-affinity worker pool, telemetry - with no `await` points, so a
    stall there blocks the event loop entirely: no heartbeat, no timeout, nothing, until
    the whole allocation's walltime is spent. See docs/limitations.md.
    """


def _construct_backend_sync(kind: str, config: dict[str, Any] | None = None):
    """The SYNCHRONOUS half of backend construction: returns an un-awaited backend.

    This is the part that can stall - `get_backend()` runs the backend's `__init__`, and
    Dragon's builds `Batch()` (results DDict, GPU-affinity worker pool, telemetry) with no
    `await` points. It is therefore the only part `make_engine_bounded` offloads.

    It is loop-agnostic by construction: nothing here captures a running loop (verified
    against rhapsody 0.5.1 - the Dragon backend sets `self._loop = None` in `__init__` and
    captures the real loop on first submission, inside the async path).
    """
    config = dict(config or {})
    kind = kind.lower()

    if kind in ("concurrent", "local_process", "mock"):
        workers = int(config.get("workers", 4))
        pool = (ThreadPoolExecutor(max_workers=workers)
                if config.get("executor", "process") == "thread"
                else ProcessPoolExecutor(max_workers=workers))
        from rhapsody.backends import ConcurrentExecutionBackend
        return ConcurrentExecutionBackend(pool)

    if kind == "noop":
        from radical.asyncflow import NoopExecutionBackend
        return NoopExecutionBackend()

    if kind == "local":
        from radical.asyncflow import LocalExecutionBackend
        return LocalExecutionBackend()

    # Everything else (dragon, radical, dask) resolves by NAME through rhapsody's
    # registry, so no rhapsody backend class is named in our source.
    from rhapsody.backends import get_backend
    return get_backend(kind, config)


async def _init_backend(be):
    """The ASYNC half: `__await__` runs `_async_init()` and registers the task states.

    Must run on the loop that will submit to the backend - see the module docstring.
    """
    return await be if hasattr(be, "__await__") else be


async def make_backend(kind: str, config: dict[str, Any] | None = None):
    return await _init_backend(_construct_backend_sync(kind, config))


async def make_engine(kind: str, config: dict[str, Any] | None = None, work_dir: str = ""):
    from radical.asyncflow import WorkflowEngine
    backend = await make_backend(kind, config)
    return await WorkflowEngine.create(backend=backend, work_dir=work_dir), backend


def _construct_backend_in_thread(kind: str, config: dict[str, Any] | None,
                                 fut: Future) -> None:
    """Runs `_construct_backend_sync` - and ONLY that - in its own OS thread.

    Not offloaded via `loop.run_in_executor`: that would still run on the CALLING
    process's default thread pool, whose worker threads are joined at interpreter
    shutdown - so a genuinely stuck Dragon `Batch()` call would hang process exit even
    after the awaiting coroutine gives up on it. A dedicated `daemon=True` thread is
    abandoned for free instead.

    This deliberately stops short of the backend's `_async_init()` and of building the
    `WorkflowEngine`. Running those here (as this did until jobs 22328172/22328262, via
    `asyncio.run(make_engine(...))`) hands the caller an engine bound to a loop that is
    already closed, whose `run-component` dispatch task was cancelled on the way out -
    the campaign then submits its first task and waits forever. See the module docstring.
    """
    try:
        result = _construct_backend_sync(kind, config)
        if not fut.done():
            fut.set_result(result)
    except BaseException as e:                      # noqa: BLE001 - relayed, not swallowed
        if not fut.done():
            fut.set_exception(e)


async def make_engine_bounded(kind: str, config: dict[str, Any] | None,
                              timeout_s: float, heartbeat_s: float, work_dir: str = ""):
    """`make_engine`, bounded by a wall-clock timeout with progress logging.

    `timeout_s <= 0` disables the bound entirely and calls `make_engine` directly - this
    keeps every existing campaign (none of which sets it) byte-for-byte unaffected. So do
    the cheap built-in kinds, whose constructors cannot stall.

    Only the synchronous construction is offloaded to the daemon thread; the backend's
    async init and the `WorkflowEngine` are built here, on the caller's own loop, because
    that is the loop that will submit to them.
    """
    if timeout_s <= 0 or kind.lower() in _CHEAP_KINDS:
        return await make_engine(kind, config, work_dir)

    fut: Future = Future()
    threading.Thread(target=_construct_backend_in_thread, args=(kind, config, fut),
                     daemon=True, name="backend-construct").start()
    async_fut = asyncio.wrap_future(fut)

    t0 = time.monotonic()

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(heartbeat_s)
            elapsed = time.monotonic() - t0
            log.info("engine: still constructing %s backend (%.0fs elapsed, "
                     "timeout in %.0fs)", kind, elapsed, timeout_s - elapsed)

    hb = asyncio.ensure_future(_heartbeat())
    try:
        try:
            be = await asyncio.wait_for(asyncio.shield(async_fut), timeout=timeout_s)
        except asyncio.TimeoutError:
            raise BackendConstructionTimeout(
                f"constructing {kind!r} backend did not complete within {timeout_s:.0f}s - "
                "most likely a stall inside the backend's own synchronous construction "
                "(e.g. Dragon's Batch()/Pool()), which blocks the event loop and produces "
                "no further log output. See docs/limitations.md.") from None

        # On OUR loop, within whatever is left of the same budget: see the module
        # docstring for why neither of these may happen on the helper thread.
        remaining = timeout_s - (time.monotonic() - t0)

        async def _finish():
            from radical.asyncflow import WorkflowEngine
            backend = await _init_backend(be)
            return await WorkflowEngine.create(backend=backend, work_dir=work_dir), backend

        try:
            if remaining <= 0:
                raise asyncio.TimeoutError
            return await asyncio.wait_for(_finish(), timeout=remaining)
        except asyncio.TimeoutError:
            raise BackendConstructionTimeout(
                f"{kind!r} backend was constructed but its async init / engine build did "
                f"not complete within the remaining {max(remaining, 0.0):.0f}s of the "
                f"{timeout_s:.0f}s budget. See docs/limitations.md.") from None
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
