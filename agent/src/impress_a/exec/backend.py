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
import os
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

#: The engine's backends, by the name each task is routed with (`backend=` on its decorator).
#: There is ONE engine per campaign and these are its only routes:
#:
#: * `compute` - the campaign's execution backend (Dragon on Delta, concurrent elsewhere). The
#:   engine's default, so a task that names no backend goes here. Tool work runs here.
#: * `local` - a thread pool in the engine's own process, for Python that must see the
#:   campaign's own objects or is too small to ship: parsing a tool's output, QC gates.
#:
#: Named once here, so a misspelt route is an import error rather than asyncflow's
#: decoration-time `ValueError` in the middle of a campaign.
COMPUTE = "compute"
LOCAL = "local"
#: * `ai` - an inference backend serving a locally hosted model, present only when the
#:   campaign's reasoner is one. Reasoner calls reach it as `prompt_task`s
#:   (`runtime/executor.CampaignExecutor.infer`), so the model's GPUs and its calls are on the
#:   same engine as the tools.
AI = "ai"

#: Threads behind the `local` backend. Its work is parsing and gating, which is short and
#: mostly I/O; the bound only keeps a burst of finishing lineages from spawning a thread each.
LOCAL_WORKERS = 4

# Kinds whose constructor is pure bookkeeping - a pool object or an empty shell. None of
# them can stall, so bounding them buys nothing and would only add a thread hop.
_CHEAP_KINDS = frozenset({"concurrent", "local_process", "mock", "noop", "local"})


class BackendConstructionTimeout(RuntimeError):
    """`make_engine` did not return within its configured bound.

    Most likely cause (verified against a real 2-hour hang, job 22318678):
    rhapsody's Dragon backend builds `Batch()` synchronously in its own constructor - the
    results DDict, GPU-affinity worker pool, telemetry - with no `await` points, so a
    stall there blocks the event loop entirely: no heartbeat, no timeout, nothing, until
    the whole allocation's walltime is spent. See docs/impress-a/limitations.md.
    """


def _construct_backend_sync(kind: str, config: dict[str, Any] | None = None,
                            name: str = COMPUTE):
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
        return ConcurrentExecutionBackend(pool, name=name)

    if kind == "noop":
        from radical.asyncflow import NoopExecutionBackend
        return NoopExecutionBackend(name=name)

    if kind == "local":
        from radical.asyncflow import LocalExecutionBackend
        return LocalExecutionBackend(name=name)

    # Everything else (dragon, radical, dask) resolves by NAME through rhapsody's
    # registry, so no rhapsody backend class is named in our source. `config` is the
    # backend's first constructor argument (Dragon's `batch_kwargs`).
    from rhapsody.backends import get_backend
    return get_backend(kind, config, name=name)


async def _init_backend(be):
    """The ASYNC half: `__await__` runs `_async_init()` and registers the task states.

    Must run on the loop that will submit to the backend - see the module docstring.
    """
    return await be if hasattr(be, "__await__") else be


async def make_backend(kind: str, config: dict[str, Any] | None = None):
    return await _init_backend(_construct_backend_sync(kind, config))


class PromptResults:
    """An inference backend whose finished prompt tasks asyncflow can actually resolve.

    STOPGAP for an upstream mismatch (`plans/upstream/rhapsody-vllm-prompt-result-not-stdout.md`):
    rhapsody's `DragonVllmInferenceBackend` reports a prompt task DONE with its answer in
    `task["response"]` (a list, one entry per prompt), while asyncflow resolves a prompt task
    from `task["stdout"]` - so the documented `@flow.prompt_task(backend="ai")` route never
    resolves. Reproduced against a stand-in that completes exactly as `vllm.py` does.

    This wraps the backend's state callback and nothing else: it copies the answer to `stdout`,
    unwrapping Dragon Inference's `{"assistant": ...}` dict, and turns the backend's in-band
    error strings (`"ERROR: Batch timeout..."`, reported as DONE) into a FAILED task, because a
    reasoner handed an error message as its model's answer would try to parse it as a decision.
    Every other attribute is the wrapped backend's.
    """

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def __await__(self):
        return self._init().__await__()

    async def _init(self) -> PromptResults:
        await _init_backend(self._backend)
        return self

    def register_callback(self, func: Any) -> None:
        def relay(task: dict, state: str) -> None:
            if state == "DONE" and "stdout" not in task:
                answer = task.get("response")
                if isinstance(answer, list):
                    answer = answer[0] if len(answer) == 1 else answer
                if isinstance(answer, dict):
                    answer = answer.get("assistant", answer)
                text = answer if isinstance(answer, str) else str(answer)
                if text.startswith("ERROR:"):
                    task["exception"] = RuntimeError(text)
                    task["stderr"] = text
                    state = "FAILED"
                else:
                    task["stdout"] = text
            func(task, state)

        self._backend.register_callback(relay)


async def make_ai_backend(inference: dict[str, Any]) -> Any:
    """The `ai` route: rhapsody's `DragonVllmInferenceBackend` for one locally hosted model.

    `inference` is plain data (from a `rhapsody_vllm` model profile, `policy/llm.py`):
    `model` (Dragon `ModelConfig` fields, `model_name` required, `hf_token` filled from
    `hf_token_env`), `hardware` (`HardwareConfig`: `num_nodes`, `num_gpus`, `node_offset`), and
    optionally `batching`. Imports Dragon's AI stack only here, and lazily, through rhapsody's
    own re-export - so nothing else in the package names it.
    """
    try:
        from rhapsody.backends.ai.config import HardwareConfig, ModelConfig
        from rhapsody.backends.ai.vllm import DragonVllmInferenceBackend
    except ImportError as exc:
        raise RuntimeError(
            "a local reasoner needs rhapsody's AI backend and Dragon's inference stack: "
            "install the `[dragon]` extra with dragonhpc[ai] on the allocation") from exc
    if ModelConfig is None:
        raise RuntimeError("dragon.ai.inference is not importable - install dragonhpc[ai]")
    model = dict(inference.get("model") or {})
    if env := inference.get("hf_token_env"):
        model.setdefault("hf_token", os.environ.get(env, ""))
    model.setdefault("hf_token", "")
    model.setdefault("tp_size", 1)
    backend = DragonVllmInferenceBackend(
        model=ModelConfig(**model), hardware=HardwareConfig(**(inference.get("hardware") or {})),
        use_service=False, name=AI)
    return await PromptResults(backend)


async def _engine_over(compute, work_dir: str, ai: Any = None):
    """The one engine: `compute` first, so it is the default route, then `local`, then `ai`
    when the campaign's reasoner is a locally hosted model.

    Called on the caller's loop - the `local` backend's async init and the engine both bind
    to it (module docstring). `local` is asyncflow's own thread backend rather than rhapsody's
    concurrent one: it needs no rhapsody, and nothing routed there is ever pickled.
    """
    from radical.asyncflow import LocalExecutionBackend, WorkflowEngine
    local = await LocalExecutionBackend(ThreadPoolExecutor(max_workers=LOCAL_WORKERS),
                                        name=LOCAL)
    backends = [compute, local] + ([ai] if ai is not None else [])
    return await WorkflowEngine.create(backend=backends, work_dir=work_dir)


async def make_engine(kind: str, config: dict[str, Any] | None = None, work_dir: str = "",
                      ai: Any = None):
    """`(engine, compute_backend)`. The engine carries the `compute` and `local` routes, and
    `ai` when an inference backend is passed."""
    backend = await make_backend(kind, config)
    return await _engine_over(backend, work_dir, ai), backend


async def probe_topology(backend: Any) -> list[dict[str, Any]]:
    """What the compute backend says it has: `[{"id": host, "cores": n, "gpus": n}, ...]`.

    rhapsody's `BaseBackend.topology()`. Dragon answers from `Batch.topology()` plus an NVML
    probe of the local node; concurrent answers for this host. Off the loop, because it may
    block (Dragon runtime calls, NVML) - rhapsody's own Session does the same. Best effort:
    `[]` means unknown, never "no GPUs", and a backend without the method (asyncflow's own)
    is unknown too.
    """
    fn = getattr(backend, "topology", None)
    if fn is None:
        return []
    try:
        return list(await asyncio.to_thread(fn) or [])
    except Exception:                                   # noqa: BLE001 - best effort
        log.warning("engine: %s topology probe failed; placement falls back to the "
                    "campaign's declared site", getattr(backend, "name", "?"), exc_info=True)
        return []


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
                              timeout_s: float, heartbeat_s: float, work_dir: str = "",
                              ai: Any = None):
    """`make_engine`, bounded by a wall-clock timeout with progress logging.

    `timeout_s <= 0` disables the bound entirely and calls `make_engine` directly - this
    keeps every existing campaign (none of which sets it) byte-for-byte unaffected. So do
    the cheap built-in kinds, whose constructors cannot stall.

    Only the synchronous construction is offloaded to the daemon thread; the backend's
    async init and the `WorkflowEngine` are built here, on the caller's own loop, because
    that is the loop that will submit to them.
    """
    if timeout_s <= 0 or kind.lower() in _CHEAP_KINDS:
        return await make_engine(kind, config, work_dir, ai=ai)

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
        except TimeoutError:
            raise BackendConstructionTimeout(
                f"constructing {kind!r} backend did not complete within {timeout_s:.0f}s - "
                "most likely a stall inside the backend's own synchronous construction "
                "(e.g. Dragon's Batch()/Pool()), which blocks the event loop and produces "
                "no further log output. See docs/impress-a/limitations.md.") from None

        # On OUR loop, within whatever is left of the same budget: see the module
        # docstring for why neither of these may happen on the helper thread.
        remaining = timeout_s - (time.monotonic() - t0)

        async def _finish():
            backend = await _init_backend(be)
            return await _engine_over(backend, work_dir, ai), backend

        try:
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(_finish(), timeout=remaining)
        except TimeoutError:
            raise BackendConstructionTimeout(
                f"{kind!r} backend was constructed but its async init / engine build did "
                f"not complete within the remaining {max(remaining, 0.0):.0f}s of the "
                f"{timeout_s:.0f}s budget. See docs/impress-a/limitations.md.") from None
    finally:
        hb.cancel()
        try:
            await hb
        except asyncio.CancelledError:
            pass
