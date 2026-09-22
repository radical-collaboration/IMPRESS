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

**Version drift is real.** Check the installed version before trusting any API note here; this integration
targets `radical.asyncflow` 0.5.1 and `rhapsody-py` 0.5.0.

**Session directories.** asyncflow writes an `asyncflow.session.*` directory into the working directory on
every engine run. Gitignored; clean periodically.

## Python floor

Python **≥3.11** where Dragon is used (`dragonhpc` requires it). **3.10 is sufficient** for the
mock/laptop path. Heavy scientific tools run in containers or as subprocesses and do not constrain the
agent environment — only the in-process P6 libraries do.
