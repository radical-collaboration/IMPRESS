"""Backend construction.

Phase 2 finding: asyncflow ships only Noop/Local; every real backend lives in rhapsody
and must be imported directly. We keep rhapsody's NAME out of our source by resolving it
through `rhapsody.backends.get_backend(name)` from site config.

GOTCHA (verified 0.5.0): rhapsody backends are AWAITABLE - `__await__` triggers
`_async_init()`, which registers the backend's task states. Constructing one
synchronously leaves it unregistered and fails later with a confusing
"Backend 'x' not registered" from StateMapper.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)


class BackendConstructionTimeout(RuntimeError):
    """`make_engine` did not return within its configured bound.

    Most likely cause (verified against a real 2-hour hang, job 22318678):
    rhapsody's Dragon backend builds `Batch()` synchronously in its own constructor - the
    results DDict, GPU-affinity worker pool, telemetry - with no `await` points, so a
    stall there blocks the event loop entirely: no heartbeat, no timeout, nothing, until
    the whole allocation's walltime is spent. See docs/limitations.md.
    """


async def make_backend(kind: str, config: dict[str, Any] | None = None):
    config = dict(config or {})
    kind = kind.lower()

    if kind in ("concurrent", "local_process", "mock"):
        workers = int(config.get("workers", 4))
        pool = (ThreadPoolExecutor(max_workers=workers)
                if config.get("executor", "process") == "thread"
                else ProcessPoolExecutor(max_workers=workers))
        from rhapsody.backends import ConcurrentExecutionBackend
        return await ConcurrentExecutionBackend(pool)

    if kind == "noop":
        from radical.asyncflow import NoopExecutionBackend
        return NoopExecutionBackend()

    if kind == "local":
        from radical.asyncflow import LocalExecutionBackend
        return LocalExecutionBackend()

    # Everything else (dragon, radical, dask) resolves by NAME through rhapsody's
    # registry, so no rhapsody backend class is named in our source.
    from rhapsody.backends import get_backend
    be = get_backend(kind, config)
    return await be if hasattr(be, "__await__") else be


async def make_engine(kind: str, config: dict[str, Any] | None = None):
    from radical.asyncflow import WorkflowEngine
    backend = await make_backend(kind, config)
    return await WorkflowEngine.create(backend=backend), backend


def _run_make_engine_in_thread(kind: str, config: dict[str, Any] | None,
                               fut: Future) -> None:
    """Runs `make_engine` to completion on its own event loop, in its own OS thread.

    Not offloaded via `loop.run_in_executor`: that would still run on the CALLING
    process's default thread pool, whose worker threads are joined at interpreter
    shutdown - so a genuinely stuck Dragon `Batch()` call would hang process exit even
    after the awaiting coroutine gives up on it. A dedicated `daemon=True` thread is
    abandoned for free instead.
    """
    try:
        result = asyncio.run(make_engine(kind, config))
        if not fut.done():
            fut.set_result(result)
    except BaseException as e:                      # noqa: BLE001 - relayed, not swallowed
        if not fut.done():
            fut.set_exception(e)


async def make_engine_bounded(kind: str, config: dict[str, Any] | None,
                              timeout_s: float, heartbeat_s: float):
    """`make_engine`, bounded by a wall-clock timeout with progress logging.

    `timeout_s <= 0` disables the bound entirely and calls `make_engine` directly - this
    keeps every existing campaign (none of which sets it) byte-for-byte unaffected.
    """
    if timeout_s <= 0:
        return await make_engine(kind, config)

    fut: Future = Future()
    threading.Thread(target=_run_make_engine_in_thread, args=(kind, config, fut),
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
        return await asyncio.wait_for(asyncio.shield(async_fut), timeout=timeout_s)
    except asyncio.TimeoutError:
        raise BackendConstructionTimeout(
            f"constructing {kind!r} backend did not complete within {timeout_s:.0f}s - "
            "most likely a stall inside the backend's own synchronous construction "
            "(e.g. Dragon's Batch()/Pool()), which blocks the event loop and produces "
            "no further log output. See docs/limitations.md.") from None
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
