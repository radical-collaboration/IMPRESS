# Middleware Integration

How IMPRESS-A sits on `radical.asyncflow` and `rhapsody`, and the behaviours that are easy to get wrong.

## The seam

```
  campaign manager  ── validated DAG ──►  radical.asyncflow.WorkflowEngine
        ▲                                          │
        └──── typed results, QC ────  rhapsody backend (Dragon / Concurrent / …)
```

The agent owns the `WorkflowEngine` directly, and keeps several graphs in flight on it at once.
`Dispatcher.submit` registers a graph and returns a handle without awaiting it; `collect` awaits one.
Backends are constructed by `exec/backend.py` and named only in site configuration.

Two things make concurrent graphs safe on one engine, both verified against 0.5.1. Task **names** come
from `fn.__name__` and collide across graphs, but they are only labels: components are keyed by a unique
uid and dependencies resolve by future *identity*, never by name. And `workflow_id=` tags every task of
a run, which is what keeps a log readable when two identical chains are running — though asyncflow
exposes no way to look tasks up by that tag, so the run table stays the index.

## Runtime-composed DAGs

A graph described as **data** is dispatched with one generic factory — no code generation:

```python
async def _run(*deps):
    ...
_run.__name__ = node_id            # asyncflow reads the task name from __name__
task = flow.function_task(_run)
futures[tid] = task(*[futures[d] for d in deps])   # unawaited futures express edges
```

Two idioms, both needed and **not interchangeable**:

| Idiom | Expresses |
|---|---|
| passing unawaited futures as call arguments | **edges** in the DAG |
| `asyncio.gather` | awaiting **independent** work (replica fan-out) |

## Gotchas

**Rhapsody backends are awaitable and must be awaited.** `__await__` triggers `_async_init()`, which
registers the backend's task states with `StateMapper`. Constructing one synchronously appears to succeed
and then fails later with an unrelated-looking error:

```python
backend = await ConcurrentExecutionBackend(ProcessPoolExecutor(max_workers=4))  # correct
backend = ConcurrentExecutionBackend(ProcessPoolExecutor(max_workers=4))
# ... later: ValueError: Backend 'concurrentexecutionbackend' not registered. Available backends: []
```

**Real backends live in rhapsody, not asyncflow.** asyncflow exports only `NoopExecutionBackend` and
`LocalExecutionBackend`. `ConcurrentExecutionBackend`, `DragonExecutionBackend`, `RadicalExecutionBackend`
and `DaskExecutionBackend` come from `rhapsody.backends`, and are resolved **by name** through
`rhapsody.backends.get_backend()` so that site configuration, not source code, selects them.

**Task decorators accept no `name=` kwarg.** `flow.function_task(name=...)` raises `TypeError`. Setting
`__name__` before decorating is what allows a single generic factory to serve every node.

**Resource shapes are not portable.** RADICAL takes `{"ranks", "gpus_per_rank"}`; Dragon takes
`process_template` / `process_templates`. There is no shared vocabulary, so `exec/resources.py` owns the
translation from `ToolSpec.resources`. Treat site-level resource defaults as required, not convenience.

**asyncflow provides no retry primitive and no durable job state.** Engine state is in-process and cleared
at shutdown. Retry policy and the external-job ledger (`exec/ledger.py`) are ours.

**Dragon backend construction is fully synchronous and can block the event loop indefinitely.**
`DragonExecutionBackend.__init__` builds Dragon's own `Batch()` (results DDict, GPU-affinity worker
pool, telemetry) with no `await` points - a stall there blocks the calling thread's event loop
entirely, so nothing else on that loop (a heartbeat task, an `asyncio.wait_for` deadline) gets a
chance to run until `Batch()` returns. Measured, not theoretical: job 22318678 ran its full 2-hour
SLURM allocation this way, producing only Dragon's own internal infra-connect log lines the whole
time - the campaign's own heartbeat never fired once. `exec/backend.make_engine_bounded` works
around this by running the construction on a dedicated OS thread, so a timeout and heartbeat on the
calling loop stay effective regardless of what the backend's own constructor does.

**The engine and a backend's async init belong to the loop they are built on.** `WorkflowEngine`
captures `self.loop = get_event_loop_or_raise(...)` in `__init__` and `_start_async_components`
schedules its `run-component` dispatch task on exactly that loop; a rhapsody backend likewise
captures its own loop for cross-thread result delivery. So an engine built on a *different* loop
from the one that will submit to it is already dead when you get it - and it does not look dead:
construction returns normally, `flow.function_task` decorates normally, and the first task future
simply never completes. This is how the bound above went wrong: `make_engine_bounded` originally ran
all of `make_engine` on the daemon thread under `asyncio.run(...)`, whose exit cancelled
`run-component` and closed the loop. Jobs 22328172 and 22328262 both wrote `r0001 submitted` to the
ledger and then burned their walltime in silence. Only the synchronous
`_construct_backend_sync()` may be offloaded; `await backend` and `WorkflowEngine.create()` run on
the caller's loop. `tests/test_backend_bound.py` guards this the only way it can be guarded - by
putting a real task through the engine.

```python
flow, be = await make_engine_bounded("dragon", cfg, 600, 60)
assert flow.loop is asyncio.get_running_loop()   # false => every submit hangs forever
```

**Version drift is real.** Check the installed version before trusting any API note here; this integration
targets `radical.asyncflow` 0.5.1 and `rhapsody-py` 0.5.0.

**Session directories.** asyncflow writes an `asyncflow.session.*` directory into `work_dir` on every
engine run, and `work_dir` defaults to the CWD. `exec/backend.make_engine` and `make_engine_bounded` both
take a `work_dir` and pass it to `WorkflowEngine.create`; the executor passes the campaign root, so the
session dir sits beside that campaign's provenance. Construct an engine without one and it lands in
whatever directory you ran from.

## Python floor

Python **≥3.11** where Dragon is used (`dragonhpc` requires it). **3.10 is sufficient** for the
mock/laptop path. Heavy scientific tools run in containers or as subprocesses and do not constrain the
agent environment — only the in-process P6 libraries do.
