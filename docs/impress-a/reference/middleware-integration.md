# Middleware Integration

How IMPRESS-A sits on `radical.asyncflow` and `rhapsody`, and the behaviours that are easy to get wrong.

## The seam

```
  campaign manager  ── validated DAG ──►  radical.asyncflow.WorkflowEngine
        ▲                                   │      │        │
        │                             compute    local      ai
        │                          (Dragon or   (thread   (rhapsody
        │                           Concurrent)  pool)     vLLM)
        └──── typed results, QC ───────┴────────┴─────────┘
```

**One engine per campaign, carrying named routes.** `exec/backend.make_engine` builds `compute`
first, so it is the default; `local` is asyncflow's own `LocalExecutionBackend` over a thread pool,
for work that must not be pickled and must not sit on the engine's loop; `ai` is added only when the
campaign declares a locally hosted reasoner. A decorator names its route (`backend="compute"`), and
an unknown name fails at decoration rather than at submission.

The agent owns the `WorkflowEngine` directly, and keeps several graphs in flight on it at once.
`StageExecutor.submit` (`exec/stage.py`) runs a graph as one asyncflow **block** and returns the
block's future without awaiting it; `collect` waits for one. Inside a node, the adapter runs on the
engine's `local` route and each tool command is an executable task on `compute`, placed per backend
(`exec/launch.py`, `exec/resources.py`).
Backends are constructed by `exec/backend.py` and named only in site configuration.

Two things make concurrent graphs safe on one engine, both verified against 0.7.0. Task **names** come
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

## A node is two kinds of engine work

The factory above builds only half of a node. The adapter — pre-process, parameterize, post-process
and the deterministic QC gates — is a `function_task` on **`local`**, a thread in the campaign
process under its own `asyncio.run`. Every command that adapter starts through `tools/_subprocess.run_cmd`
is a separate `executable_task` on **`compute`**, submitted by `exec/launch.Launcher` and found
through a `LAUNCHER` contextvar rather than passed down every call site.

That split is what puts a binary where the placement says and keeps the adapter's Python off both the
engine's loop and the backend's pickle boundary. An adapter that shelled out any other way would run
its binary on the campaign host, unplaced and uncounted.

A whole Stage is one `@flow.block` (`exec/stage.StageExecutor`): the block's future is the graph's
result, its members inherit its uid as `workflow_id`, and cancelling it cascades to every unfinished
member with each cancel sent to the backend that member was routed to (0.7.0, asyncflow #118).

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

What a node needs is decided once, at submission (`Placement`), and rendered per command
(`Placement.describe`), because a tool's commands differ in environment and working directory but
share their GPU and their thread share. Two asymmetries are easy to get backwards:

- **Who sets `CUDA_VISIBLE_DEVICES`.** Under Dragon, *nothing here does*: the placement carries
  `Policy(host_name=…, gpu_affinity=[g])` and Dragon sets the variable itself. Setting it in the
  template's env does not work — local services merges the template env and applies the policy
  layout afterwards, and a policy with no `gpu_affinity` resolves to every GPU on the node. On the
  concurrent backend the env is the only pinning mechanism, so there it carries the variable.
- **How much of the environment travels.** The concurrent backend *replaces* a child's environment,
  so it is given the whole thing. Dragon *merges* a template's env into the target node's own, so it
  is given only what differs from ours — sending the head node's entire environment would overwrite
  the remote node's.

Thread caps (`thread_caps`, `thread_share`) are part of a placement and therefore **per command**.
They used to be written into the campaign process's own environment at start-up and inherited by
every child, which meant one campaign's caps leaked into its siblings under an enclosing manager.

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

**A coreutils `timeout` wrapper must not be used under Dragon.** `timeout` leads its own process
group; Dragon's local services reaps only its own, so a wrapped command exits, its wrapper becomes
`[timeout] <defunct>`, and the task never reaches a terminal state. Job 23814643 hung at stage 1
exactly this way. The wrapper is applied on the concurrent backend only; Dragon is handed
`walltime_s + KILL_GRACE_S` as the task's own `timeout` and enforces it itself
(`exec/launch.py`, `exec/resources.py`).

**Telemetry starts and stops with the engine, and its stop does not drain.** `flow.start_telemetry`
takes a checkpoint path; the executor points it at `<campaign root>/telemetry/` when
`telemetry_checkpoint_s > 0`. `stop()` does not forward rhapsody's `drain_on_stop`, so a stalled
drain can only be cut short by a timeout of ours, and stopping telemetry from a task other than the
one that started it makes OpenTelemetry log `Failed to detach context`. Counts read off a checkpoint
can double-count across flushes — read a span's shape, not its totals.

**`LocalExecutionBackend.shutdown` joins its pool synchronously on the engine loop.** If an adapter
thread on the `local` route is still waiting on a command, teardown deadlocks: the command's
completion needs the loop that is blocked in the join. `exec/stage._settle` and `Launcher.idle` wait
for in-flight commands before shutdown for that reason.

**Version drift is real.** Check the installed version before trusting any API note here; this
integration was first written against `radical.asyncflow` 0.5.1 and `rhapsody-py` 0.5.0.
**Verified on 0.7.0 / 0.7.0** (2026-11-11, Python 3.12.12, both installed editable from sibling
checkouts): the whole local tier is green, including the loop-ownership guard in
`tests/test_backend_bound.py` that puts real work through a bounded engine, and job 23815248 ran the
stack on Delta with `dragonhpc` 0.15.0. `agent/pyproject.toml` floors both at `>=0.7.0`, because the
execution loop relies on 0.7.0 specifically: a cancel reaches the backend a task was routed to, a
block cancel cascades to its members, `future.uid` exists at call time, and every task event names
its real backend.

**Session directories.** asyncflow writes an `asyncflow.session.*` directory into `work_dir` on every
engine run, and `work_dir` defaults to the CWD. `exec/backend.make_engine` and `make_engine_bounded` both
take a `work_dir` and pass it to `WorkflowEngine.create`; the executor passes the campaign root, so the
session dir sits beside that campaign's provenance. Construct an engine without one and it lands in
whatever directory you ran from.

## Python floor

Python **≥3.11**, unconditionally: `radical.asyncflow` and `rhapsody-py` 0.7.0 both require it, so
the floor no longer depends on whether Dragon is in use. Dragon itself is the `[dragon]` extra
(`rhapsody-py[dragon]`), which keeps CI, the laptop tier and the knob-lab notebook runnable with no
Dragon installed. Heavy scientific tools run in containers or as subprocesses and do not constrain
the agent environment.

The root `impress` package is a separate matter: it is `>=3.9` with radical.pilot, and this project
does not depend on it. That is the dependency firewall, not a conflict.
