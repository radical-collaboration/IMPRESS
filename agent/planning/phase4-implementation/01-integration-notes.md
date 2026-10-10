# 01 — Integration Notes

Gotchas discovered by *building* rather than reading. Each cost real debugging time and
none is documented upstream in a form we found.

## asyncflow / rhapsody

**Rhapsody backends are awaitable, and must be awaited.**
`ConcurrentExecutionBackend.__await__` triggers `_async_init()`, which registers the
backend's task states with `StateMapper`. Constructing one synchronously "succeeds" and
then fails later with a confusing
`ValueError: Backend 'concurrentexecutionbackend' not registered. Available backends: []`.

```python
backend = await ConcurrentExecutionBackend(ProcessPoolExecutor(max_workers=4))  # correct
backend = ConcurrentExecutionBackend(ProcessPoolExecutor(max_workers=4))        # breaks later
```

**`ConcurrentExecutionBackend` lives in rhapsody, not asyncflow.** asyncflow exports only
`NoopExecutionBackend` and `LocalExecutionBackend`. This confirms the Phase 2 finding
directly: rhapsody is a construction-time import for any real backend.

**Task names come from `fn.__name__`.** The task decorators accept no `name=` kwarg —
`flow.function_task(name=...)` raises `TypeError`. Set `__name__` before decorating, which
is what lets one generic factory serve every node:

```python
async def _run(*deps): ...
_run.__name__ = node_id
task = flow.function_task(_run)
```

**Version drift is real.** The system environment had asyncflow **0.3.1** installed while
the refcode Phase 2 analysed was **0.5.1**. We pinned 0.5.1 in an isolated venv. Check the
installed version before trusting any API note.

## The central bet, validated

A DAG described as **data** dispatches to asyncflow with one generic factory — no code
generation, no AST manipulation. Dependencies are expressed by passing **unawaited
futures** as call arguments; asyncflow's scheduler resolves order itself.

Both asyncflow idioms are needed and they are **not interchangeable**:

| Idiom | Expresses |
|---|---|
| dependency-as-argument | **edges** in the DAG |
| `asyncio.gather` | awaiting **independent** work (replica fan-out) |

## flowgentic

Pinned to commit `dd27bd8b` on `demo/radical` per the Phase 4 decision. Two practical
notes: it must be installed `--no-deps` (its `pyproject.toml` declares `radical.asyncflow`
twice, once as a git URL on `main`), and it needs `python-json-logger`, `python-dotenv` and
`langchain-openai` supplied manually.

## Python floor — a correction to Part C

Part C set the agent environment at **≥3.12**, inherited from foundry. That was wrong:
foundry runs in containers and does not constrain the agent. The real floor is rhapsody's
Dragon extra at **≥3.11**. Everything in this implementation runs on **3.10**, which is
sufficient for the laptop/mock tier. Part C's constraint should read:

> Agent environment: **≥3.11** where Dragon is used; 3.10 is sufficient for the
> mock/laptop path.
