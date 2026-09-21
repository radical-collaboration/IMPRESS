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

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any


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
