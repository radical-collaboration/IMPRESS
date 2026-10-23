# `radical.asyncflow` v0.5.1 — Phase 2 Middleware Exploration

Refcode root: `<workspace>/impress-a-refcodes/middleware/radical.asyncflow/`
Version under test: **0.5.1** (`VERSION`, `pyproject.toml`), released 2026-08-20. Real git history
(`v0.1.1` → `v0.3.0` → `v0.3.1` → `v0.4.0` → `v0.5.0` → `v0.5.1`), 109 unit/integration tests across
~2,900 lines of test code against ~2,900 lines of source.

All claims below are **verified from source** unless explicitly marked **inferred** or **per docs
(unverified against rhapsody)** — asyncflow's own repo does not contain rhapsody, so anything about
rhapsody's internals is taken from asyncflow's docs/examples, not confirmed against rhapsody's code.

---

## 1. `WorkflowEngine` API surface

**Construction is a two-step async factory, not a plain constructor.** The `__init__` docstring says
it plainly:

> "Note: This is a private constructor. Use `WorkflowEngine.create()` instead."
> — `src/radical/asyncflow/workflow_manager.py:67`

```python
@classmethod
async def create(
    cls,
    backend: Any = None,
    dry_run: bool = False,
    implicit_data: bool = True,
    uid: Optional[str] = None,
    work_dir: Optional[str] = None,
) -> "WorkflowEngine":
```
(`workflow_manager.py:358-365`)

`create()` validates/normalizes the backend (`_setup_execution_backend`, defaulting to
`NoopExecutionBackend` if `dry_run=True` and no backend given, or `LocalExecutionBackend` with a
loud warning otherwise), constructs the instance, then calls `_start_async_components()` which does
`self._run_task = asyncio.create_task(self.run(), name="run-component")` (`workflow_manager.py:425`)
— a single background asyncio task that is the entire scheduler.

Must be called from a running event loop — `get_event_loop_or_raise()` (`utils.py:19-40`) raises a
helpful `RuntimeError` ("must be created within an async context... use `asyncio.run()`") otherwise.

**Work submission** happens by calling a decorated function, which returns immediately with an
`asyncio.Future` (not blocking, not an `await`):

```python
t1 = task1()          # returns asyncio.Future, state="PENDING", already scheduled
t2 = task2(t1)         # t1 (a Future) is a positional arg → detected as a dependency edge
result = await t2      # only awaiting blocks
```

**Results/failures** come back on that same future: `.result()` on success, `.exception()` raising a
`DependencyFailureError`/original exception on failure, `.cancelled()` on cancellation. Every future
also carries a `.state` string (`"PENDING"→"RUNNING"→"DONE"/"FAILED"/"CANCELLED"`), added in 0.5.0
specifically so callers don't have to combine `.done()`+`.exception()` (`CHANGELOG.md:34-37`,
`docs/best_practice.md:40-66`).

**Shutdown**: `await flow.shutdown(skip_execution_backend=False)` — sets a shutdown event, cancels
all non-terminal task/block futures, cancels the internal `run()` task (5 s timeout), then
`await asyncio.gather(*[b.shutdown() for b in self._backends.values()])` for every registered backend,
then clears internal state (`workflow_manager.py:1730-1795`). Also auto-triggers on
`SIGHUP`/`SIGTERM`/`SIGINT` via `_setup_signal_handlers()` — but **only on the main thread**; off-thread
it logs a warning and skips registration, "host process must manage shutdown"
(`workflow_manager.py:311-323`, confirmed by `tests/unit/test_termination.py:305-330`).

---

## 2. Task types (M1 — the load-bearing question)

Four decorators are created in `__init__` (`workflow_manager.py:118-126`):

```python
self.block          = self._register_decorator(comp_type=BLOCK)
self.function_task  = self._register_decorator(comp_type=TASK, task_type=FUNCTION)
self.executable_task = self._register_decorator(comp_type=TASK, task_type=EXECUTABLE)
self.prompt_task    = self._register_decorator(comp_type=TASK, task_type=PROMPT)
```

- **`function_task`** — wraps a plain async Python function. The function itself is shipped to the
  backend and invoked there with *resolved* dependency values (futures replaced with `.result()` by
  `_extract_dependency_values`, `workflow_manager.py:940-969`, called just before submission in the
  scheduler loop). Return value → `task_fut.set_result(task["return_value"])`
  (`handle_task_success`, `workflow_manager.py:1492-1516`). On `LocalExecutionBackend` this runs in a
  `ThreadPoolExecutor`/`ProcessPoolExecutor` (`backends.py:284-309`); on HPC backends it is whatever
  the rhapsody backend implements.

- **`executable_task`** — the IMPRESS idiom. Confirmed still current in 0.5.1: the decorated async
  function's return value must be a shell command **string**:

  ```python
  if task_type == EXECUTABLE:
      cmd = await func(*args, **kwargs)
      if not cmd or not isinstance(cmd, str):
          raise ValueError(
              f"Executable task '{func.__name__}' must return "
              "a non-empty command string"
          )
      parts = shlex.split(cmd)
      ...
      comp_desc[EXECUTABLE] = parts[0]
      comp_desc["arguments"] = parts[1:]
  ```
  (`workflow_manager.py:647-661`)

  **Important nuance not obvious from the docs**: the decorated function body runs (to compute the
  command string) as soon as it is scheduled by `asyncio.create_task(async_wrapper())`
  (`workflow_manager.py:674`) — i.e. essentially immediately, **before** its declared dependencies
  have resolved. If the shell command needs an upstream task's *result* (not just ordering), the
  function body must explicitly `await` that dependency future itself:
  ```python
  @flow.executable_task
  async def stage2(stage1_fut, task_description=...):
      path = await stage1_fut          # explicit — blocks only this task's own coroutine
      return f"/bin/analyze {path}"
  ```
  Passing the future as an *unawaited* arg (as `examples/07-radical_execution_backend.py` does — see
  below) only registers the dependency edge for the scheduler; it does not inject the resolved value
  into the function body. This distinction matters directly for the composer: task functions that
  need upstream data in the command string must be written to await it, not just receive it
  positionally.

- **`prompt_task`** — **not mentioned in the brief but present and tested in 0.5.1**
  (`tests/unit/test_prompt_task.py`). Same registration path as `executable_task`/`function_task` but
  stores a plain prompt string (`comp_desc[PROMPT] = await func(...)`, must be non-empty str) and is
  intended to route to an AI-inference backend via `backend="ai"` (see `examples/04-concurrent_backends.py`,
  which pairs it with a mocked `NoopExecutionBackend(name="ai")` and a comment pointing at RHAPSODY's
  `DragonVllmInferenceBackend` for production). This is a fourth task type worth knowing about if
  IMPRESS ever wants LLM-driven task agents dispatched *through* asyncflow rather than out-of-band.

- **`block`** — not a task type but a composite-workflow decorator: wraps an async function whose body
  calls other tasks/blocks and awaits some subset of them. A block's future resolves when its body
  coroutine returns; cancelling a block future cancels the underlying `asyncio.Task` and cascades
  cancellation to every task/block registered inside it (`_block_members` tracking,
  `workflow_manager.py:788-806`, `1436-1449`). Blocks nest (`examples/03-nested_blocks.py`).

**Dependency expression, and the direct answer to the DAG-at-runtime question:**

Dependencies are **not** expressed by a declarative graph object, and they are **not** required to be
literal `await`-chains hard-coded in source. They are expressed by *passing the Future object returned
by one decorated call as a positional or keyword argument to another decorated call*:

```python
t1 = task1()
t2 = task2(t1)
t3 = task3(t1, t2)
result = await t3
```
(`examples/01-workflows.py:41-44`, `docs/best_practice.md:106-134`)

Detection is purely structural, done in `_detect_dependencies` by scanning the call's `args`/`kwargs`
for `isinstance(x, asyncio.Future)` (`workflow_manager.py:895-938`, unit-tested in
`tests/unit/test_dependencies_detection.py:21-39`). Nothing about that scan requires the calls to
appear as literal source-level `await` expressions — it is ordinary Python function-call machinery.

**This means a runtime-composed DAG from data is directly expressible without code generation.** A
composer can hold a `dict[node_id, asyncio.Future]`, walk its typed DAG in any valid order (topological
or not — the scheduler resolves order itself via the ready-queue/dependency-count machinery in `run()`,
`workflow_manager.py:1069-1320`), and for each node do:

```python
futures[node.id] = decorated_task_fns[node.tool](
    *[futures[dep_id] for dep_id in node.deps],
    task_description=node.resources,
)
```

No per-shape Python source has to be generated; one dispatch loop over the typed DAG suffices. The
caveat from the executable-task nuance above stands: if a node's *command string* needs an upstream
node's *result value* (not just ordering), the tool's wrapped function must `await` the corresponding
positional arg internally — which is a property of how each `ToolSpec`'s task-agent function is
written, not a limitation on runtime composition itself. **Verdict on M1: asyncflow's dependency model
is runtime-composition-friendly by construction — it was not designed as a static-authoring DSL, it is
"just Python calls," which is exactly what makes data-driven composition straightforward.**

One structural constraint worth flagging: `_register_component` assigns UIDs from a single global
monotonically-increasing counter (`get_next_uid()`, `utils.py:6-10`), reset only on `shutdown()`
(`reset_uid_counter()`, called from `_clear_internal_records`). There is no notion of "submit DAG X,
get back DAG X's own namespace" — all tasks/blocks share one flat ID space per engine instance
(`task.000001`, `task.000002`, …) across whatever's concurrently registered. `workflow_scope()` /
`workflow_id=` (added 0.4.0/0.5.0) tags tasks with a *label* for telemetry/grouping but does not create
isolated ID namespaces or a way to list/query "all tasks belonging to cycle N" from the engine's public
surface — that bookkeeping (mapping cycle → task UIDs) is left to the caller.

---

## 3. Backend seam — testing "rhapsody is never called directly"

**Verdict: false for the primary/preferred HPC backend, true only for the built-in fallback backends.**

asyncflow's own `pyproject.toml` dependencies are `pydantic`, `typeguard`, `requests`, `cloudpickle` —
**no rhapsody dependency at all** (`pyproject.toml:20-25`). `src/radical/asyncflow/backends.py` defines
exactly two backend classes natively: `NoopExecutionBackend` (dry-run/testing, always returns dummy
output) and `LocalExecutionBackend` (wraps a stdlib `ThreadPoolExecutor`/`ProcessPoolExecutor`,
`backends.py:168-455`). Both are re-exported from `src/radical/asyncflow/__init__.py:5,16-17`.

For HPC execution — including the context doc's stated preferred backends,
`DragonExecutionBackend`/`DragonExecutionBackendV3` and `RadicalExecutionBackend` — **the user imports
rhapsody directly and constructs it themselves**, then hands the already-constructed object to
`WorkflowEngine.create()`:

```python
from rhapsody.backends import DragonExecutionBackendV3
...
backend = await DragonExecutionBackendV3()
flow = await WorkflowEngine.create(backend=backend)
```
(`examples/06-dragon_execution_backend.py:19,33,37`)

```python
from rhapsody.backends import RadicalExecutionBackend
...
backend = await RadicalExecutionBackend({"nodes": 1, "resource": "local.localhost"})
flow = await WorkflowEngine.create(backend=backend)
```
(`examples/07-radical_execution_backend.py:14,26-27`)

The docs are explicit about this being the intended division of labor:

> "For HPC execution, install RHAPSODY: `pip install rhapsody-py` ... RHAPSODY is a dedicated HPC
> execution layer that provides additional backends, all of which integrate immediately with
> AsyncFlow — no changes to your workflow logic are needed."
> — `docs/exec_backends.md:22-34`

So: **asyncflow does not re-export or wrap rhapsody backends, and it does not construct one for you.**
It defines a backend *protocol* (duck-typed, not a formal ABC in this codebase — see `_attach_backend`,
which just calls `backend.get_task_states_map()`, `backend.register_callback()`, sets
`backend._work_dir`/`is_attached`/`attached_to`, `workflow_manager.py:146-157`) and expects any
object satisfying it. `NoopExecutionBackend`/`LocalExecutionBackend` satisfy it natively; RHAPSODY's
`RadicalExecutionBackend`/`DragonExecutionBackendV3`/`DaskExecutionBackend`/`ConcurrentExecutionBackend`
satisfy it too, but the user must `pip install rhapsody-py`, `from rhapsody.backends import ...`, and
construct the object themselves. **This is rhapsody being called directly by the application, at
construction time, for every non-toy deployment.** The "reached through asyncflow" framing only holds
in the narrow sense that *task submission and result plumbing* after construction goes through
`WorkflowEngine`, not in the sense that rhapsody types never appear in application code.

**A second, separate place rhapsody is called directly — this time inside asyncflow's own source, not
just user code:**

```python
async def start_telemetry(self, ...) -> Any:
    """Create and start a RHAPSODY TelemetryManager for this workflow engine. ..."""
    from rhapsody.telemetry.manager import TelemetryManager  # noqa: PLC0415
    self._telemetry = TelemetryManager(session_id=self.uid, ...)
    ...
    from rhapsody.telemetry.events import (
        TaskCanceled, TaskCompleted, TaskCreated, TaskFailed,
        TaskQueued, TaskStarted, TaskSubmitted, define_event, make_event,
    )
```
(`workflow_manager.py:159-251`)

This import is lazy (inside the method, `# noqa: PLC0415` = "don't flag late import") specifically so
that `rhapsody-py` stays an optional dependency — but if `flow.start_telemetry()` is called, asyncflow
itself reaches directly into `rhapsody.telemetry.manager` and `rhapsody.telemetry.events`. So the
"rhapsody is reached through asyncflow" framing is *accurate* for telemetry (asyncflow wraps
rhapsody's TAL and exposes one call), and *inaccurate* for execution backends (asyncflow expects the
caller to already have a rhapsody backend object in hand).

**Net finding for the hypothesis**: qualify it, don't drop it. Telemetry: asyncflow genuinely
intermediates rhapsody. Execution on HPC: rhapsody is a hard, direct, user-visible dependency —
`from rhapsody.backends import DragonExecutionBackend`/`RadicalExecutionBackend` is exactly the line
IMPRESS's HPC code will contain. The "rhapsody is reference-only" framing in the shared context
document does not survive contact with the examples directory as written for 0.5.1.

---

## 4. Resource shapes (M2)

No typed resource-description class exists in asyncflow. `task_description` is a **loose dict**,
merged from the decorated function's default kwarg value and any call-time override
(`_register_decorator`, `workflow_manager.py:521-554`: call-time keys win). It is passed straight
through to the backend's `task_specific_kwargs`/`task_backend_specific_kwargs` with **zero validation
or schema enforcement** by asyncflow — asyncflow does not know or care what `'ranks'`, `'gpus_per_rank'`,
`'nodes'`, `'process_template'`, `'walltime'` mean; interpretation is entirely the backend's:

```python
task1_resources = {"ranks": 1, "gpus_per_rank": 1}
...
@flow.executable_task
async def task1(task_description=task1_resources): ...
```
(`examples/07-radical_execution_backend.py:29,33-34`, RadicalExecutionBackend/RADICAL-Pilot shape)

```python
single_process = {"process_template": {}}
parallel_processes = {"process_templates": [(2, {}), (2, {})]}
...
@flow.executable_task
async def parallel_executable(*args, task_description=parallel_processes): ...
```
(`examples/06-dragon_execution_backend.py:40-41,49-51`, DragonExecutionBackendV3 shape)

Two different HPC backends in the *same* asyncflow release use **structurally different**
`task_description` shapes (`ranks`/`gpus_per_rank` vs. `process_template`/`process_templates`). There
is no cross-backend resource abstraction to design against — a portable resource layer (Polaris/Dragon
vs. ACCESS/RADICAL-Pilot vs. edge/Local) is something IMPRESS must own; asyncflow deliberately declines
to normalize it (`docs/exec_backends.md:182-188`: "Specifying `task_description` keys and values
depends on the corresponding `ExecutionBackend` used").

---

## 5. Cancellation (M4)

**Per-task cancellation is real and backend-aware**, not just local bookkeeping. Calling
`.cancel()` on a task future is monkey-patched at registration time
(`_setup_future_cancel_hook`, `workflow_manager.py:838-881`):

```python
def patched_cancel(*args, **kwargs):
    if not fut.done() and uid in self.running:
        asyncio.create_task(self.backend.cancel_task(uid))   # fire-and-forget
        return True
    else:
        result = fut.original_cancel(*args, **kwargs)         # still pending → cancel locally
        ...
```

If the task hasn't been submitted yet, cancellation is purely local (never reaches the backend). If
it's already running, `backend.cancel_task(uid)` is invoked — this exists on both built-in backends
(`NoopExecutionBackend.cancel_task` is a no-op stub; `LocalExecutionBackend.cancel_task` calls
`future.cancel()` on the underlying `asyncio.Task`, `backends.py:371-388`) and is presumably
implemented meaningfully by RHAPSODY backends for real job cancellation (**inferred** — not verifiable
from this repo). This is asyncio's best-effort semantics: `.cancel()` returns `True` for "requested,"
not "guaranteed."

**Block cancellation cascades** to every task/block registered inside it — confirmed by
`test_block_cancel_stops_execution` (`tests/unit/test_cancellation.py:56-79`) and the membership
teardown wired at registration time (`_block_members`, `workflow_manager.py:788-806`, propagated on
`_on_block_fut_done`, `1438-1449`). **This is the practical mechanism for "cancel one campaign
lineage/cycle without affecting others"**: wrap a cycle's composed DAG in `@flow.block`, and cancelling
the block future recursively cancels every task registered inside it during that call. There is no
separate "cancel by workflow_id" or "cancel by tag" API — `workflow_scope()`/`workflow_id=` are
telemetry labels only, not cancellation handles (confirmed: nothing in `workflow_manager.py` reads
`workflow_id` for cancellation routing).

**There is no whole-engine "cancel everything but keep the engine alive" call** short of `shutdown()`,
which tears down the run loop and all backends and clears internal state — a one-way trip, not a
pause/resume. For `stop` semantics that's adequate; for `Backtrack` (kill one lineage, keep the
campaign running) the block-cancellation path is what to build on, and it is adequate but manual —
IMPRESS's composer will need to consistently wrap each cycle/lineage in a block to get a cancellation
handle for it.

---

## 6. Telemetry (M5)

`flow.start_telemetry(...)` (`workflow_manager.py:159-251`) is a thin, well-documented wrapper around
RHAPSODY's `TelemetryManager`: it constructs the manager, calls `attach_backend()` for every registered
backend (silently skipping `LocalExecutionBackend`/`NoopExecutionBackend`, which have no adapter —
"per docs," `docs/telemetry.md:11` says telemetry itself requires `pip install rhapsody-py[telemetry]`
even to enable it on the no-op path), starts its async dispatch loop, and registers a span enricher
that stamps `asyncflow.workflow_id` onto spans.

Events emitted (per `docs/telemetry.md:132-172`, cross-checked against the event names imported in
`workflow_manager.py:223-233` and emitted at `_emit()` call sites throughout the file):
`TaskCreated` → `asyncflow.TaskResolved` (asyncflow-specific, defined via rhapsody's `define_event()`
so core rhapsody stays DAG-agnostic, `workflow_manager.py:235-249`) → `TaskSubmitted` →
(`TaskQueued`, backend-specific) → `TaskStarted` → `TaskCompleted`/`TaskFailed`/`TaskCanceled`.
`asyncflow.TaskResolved` specifically times *dependency wait* (when all upstream deps are satisfied,
i.e. eligible for submission) — a metric IMPRESS's composer/scheduler will want for the budget ledger
and for detecting bottleneck tool chains.

`telemetry.subscribe(callback)` accepts sync or async callbacks and "runs on the asyncio event loop"
(`docs/telemetry.md:178`) — this is the subscription hook the context doc asks about, and it looks
directly reusable as (or adaptable into) the control plane's `events()`/`observe()` stream: a
`PipelineMonitor`-style subscriber pattern is shown in the docs (`docs/telemetry.md:279-306`) that is
structurally identical to what an `observe()` adapter would need. One real constraint: **do not call
`telemetry.emit()` from inside a task function body** — task functions may be `cloudpickle`-serialized
for subprocess/process-pool execution, and capturing the telemetry object in a closure breaks that
serialization (`docs/telemetry.md:308-325`, explicit ✗/✓ example). Application-level custom events are
supported via `define_event()`/`make_event()`, namespaced with a dot, which is exactly the mechanism
asyncflow used to add its own `asyncflow.TaskResolved` — IMPRESS could add e.g. `impressA.QCGatePassed`
the same way, again re-confirming telemetry is the one place where "reached through asyncflow" is
literally true (asyncflow wraps it; the user never imports `rhapsody.telemetry` directly unless
defining custom events, which the docs show importing `from rhapsody.telemetry import define_event`
directly even in the "application-level frameworks" section, `docs/telemetry.md:238`).

**Caveat**: `pip install rhapsody-py[telemetry]` is a hard requirement to use `start_telemetry()` at
all — this is not a zero-dependency feature; it can't be exercised on the `NoopExecutionBackend` /
`LocalExecutionBackend`-only edge/laptop configuration without also pulling in rhapsody.

---

## 7. Failure semantics

No built-in retry anywhere in the codebase (`grep -rn "retry\|retries" src/ docs/` returns nothing).
A task failure sets an exception on its future
(`handle_task_failure`, `workflow_manager.py:1517-1571`, wraps stderr/exception into a `RuntimeError`
or passes through an existing `Exception`). **Failure propagates automatically to dependents** as a
distinguishable, chained exception type:

```python
class DependencyFailureError(Exception):
    def __init__(self, message, failed_dependencies=None, root_cause=None):
        ...
        if root_cause:
            self.__cause__ = root_cause
```
(`src/radical/asyncflow/errors.py`)

Built by `_create_dependency_failure_exception` (`workflow_manager.py:1020-1051`) in the scheduler
loop when a dependent is about to become ready and finds a failed/cancelled upstream future; it names
every failed dependency and chains the *root* cause (unwrapping nested `DependencyFailureError`s,
confirmed by `test_chain_of_dependency_failures`, `tests/unit/test_failure_propagation.py:82-116`, which
walks a 4-deep chain and gets the original `ValueError` at the bottom). Partial-failure fan-in also
works correctly: a task depending on one successful + one failed upstream gets a
`DependencyFailureError` naming only the failed one (`test_partial_dependency_failure`,
`tests/unit/test_failure_propagation.py:120-146`). Blocks propagate the same way
(`test_block_dependency_failure`, `:150-168`). This is solid, well-tested machinery — 9 dedicated tests
just for failure propagation — and gives the composer everything it needs to detect "this branch of the
DAG is dead" without polling: any future's `.exception()` being a `DependencyFailureError` (vs. some
other exception type) already distinguishes "this task itself failed" from "an ancestor failed."

**No retry policy layer** (bounded retries, backoff, idempotency checks) exists at any level —
if IMPRESS wants retry-with-backoff for flaky P4/P5 tasks, that is entirely the composer/task-agent's
job to implement around the future returned by asyncflow (e.g., re-invoke the decorated function on
failure), not something asyncflow offers as a decorator option or engine setting.

---

## 8. Async model

Asyncio-native throughout — the entire engine is one coroutine (`run()`,
`workflow_manager.py:1069-1320`) driven by an internal ready-queue/dependency-count structure
(`_ready_queue`, `_dependency_count`, `_dependents_map`) plus an `asyncio.Event`
(`_component_change_event`) to avoid busy-waiting; it blocks on
`asyncio.wait([event_task, shutdown_task], timeout=1.0)` when idle rather than spinning
(`workflow_manager.py:1282-1312`). Task registration (`wrapped()` → `async_wrapper()`) is scheduled via
`asyncio.create_task` and returns a `Future` synchronously without blocking the caller
(`workflow_manager.py:674,682`) — this is exactly what makes "call `task()` in a loop while composing a
DAG from data" cheap and non-blocking.

**The outer loop remains responsive while tasks run**, subject to two caveats:
1. `LocalExecutionBackend._execute_command`/`_execute_function` correctly use
   `asyncio.create_subprocess_shell`/`exec` and `loop.run_in_executor()` (`backends.py:311-346,
   284-309`) — no blocking calls on the event loop from the built-in backend.
2. HPC backends (RHAPSODY) are **inferred** to follow the same discipline since the whole library is
   asyncio-first by design (`await SomeBackend(...)` construction pattern everywhere), but this cannot
   be verified from asyncflow's own repo.
3. One genuine blocking hazard exists in asyncflow's own code: `shutdown()` executes
   `await asyncio.wait_for(self._run_task, timeout=5.0)` (`workflow_manager.py:1780`) — a real await
   with a bounded timeout, not a hard block, so this is fine; it degrades to a warning-and-continue on
   timeout rather than hanging.

Signal handling (`SIGHUP`/`SIGTERM`/`SIGINT` → graceful `shutdown()`) is installed via
`loop.add_signal_handler`, itself asyncio-native and non-blocking (`workflow_manager.py:325-336`).

**Conclusion: this is a genuinely responsive async model.** A control-plane adapter (`observe`/`steer`)
running as another coroutine on the same event loop, or subscribing via `telemetry.subscribe()`, should
not be starved by task execution — the scheduler loop itself never blocks longer than the 1 s
`asyncio.wait` timeout while idle, and never longer than one dependency-resolution pass while busy.

---

## 9. P4 / P5 / P6 / P7 fit (M7)

- **P4 (external HPC job submitted outside the allocation, must survive process restart)**: expressible
  as a `function_task` (or `executable_task` wrapping a CLI submit-and-poll script) whose body does
  submit + async-sleep-poll internally — nothing stops arbitrary async logic inside a task body, and
  the event loop stays responsive to other tasks while one task polls. **What asyncflow does not give
  you**: durability. There is no persisted task ledger — `self.components`/`self.dependencies` are
  in-memory dicts (`workflow_manager.py:98-100`), cleared on `shutdown()`/`_clear_internal_records()`.
  If the IMPRESS agent process dies mid-poll, the `asyncio.Future` and everything about that submission
  is gone; nothing in asyncflow reconstructs "job 12345 was submitted, go check on it" after a restart.
  **The durable job ledger for P4 is squarely IMPRESS's own responsibility, outside asyncflow.**

- **P5 (network service over HTTPS, needs caching/concurrency caps/backoff)**: a plain `function_task`
  doing an async HTTP call (`aiohttp`/`httpx`) fits cleanly — asyncio-native, non-blocking. asyncflow
  provides no governor primitives (no built-in rate limiter, cache, or backoff decorator) — the
  concurrency-cap/backoff/caching layer is, again, something IMPRESS layers on top (e.g., an
  `asyncio.Semaphore` around the task body, or a wrapper before calling the decorated function).

- **P6 (in-process, must never be scheduled)**: trivially bypassable — nothing requires routing a call
  through `flow.function_task`/`executable_task`. A plain `await my_inprocess_fn(...)` call, entirely
  outside the engine, coexists fine with an active `WorkflowEngine` in the same event loop (confirmed
  by the pattern in every example where regular Python/async code runs alongside `flow.*` calls,
  e.g. `run_wf`/`run_pipeline` orchestration functions themselves are never decorated).

- **P7 (composite pipeline launched as one task)**: this maps directly onto `@flow.block` — a block is
  precisely "a logical grouping of dependent and independent workflows" launched and awaited as a
  single unit (`docs/composite_workflow.md:3`), with its own future, state lifecycle, and cascading
  cancellation. Blocks nest (`examples/03-nested_blocks.py`), so a P7 pipeline-of-pipelines is directly
  expressible.

- **P1/P2/P3 (GPU-node-local, CPU fan-out, MPI multi-node, all in-job)**: these are exactly what
  `executable_task`/`function_task` + `task_description` (`ranks`, `gpus_per_rank`,
  `process_template(s)`, MPI-rank fan-out shown in `docs/exec_backends.md:156-180`) were built for —
  the best-supported, most-documented case in the whole library.

- **P8 (external experiment, forward-declared, unused)**: not evaluated (out of scope per context doc).

| Pattern | asyncflow construct | Fit | Notes |
|---|---|---|---|
| P1 GPU-node-local | `executable_task`/`function_task` + `task_description` | Clean | primary documented use case |
| P2 CPU fan-out | `executable_task`/`function_task` + `task_description` (ranks/cores) | Clean | same as P1 |
| P3 MPI multi-node | `function_task` with `{'ranks': N, 'type': 'mpi'}` | Clean | shown in `docs/exec_backends.md:156-180` |
| P4 external HPC job | `function_task`/`executable_task` w/ internal poll loop | Partial | no durable ledger — IMPRESS must build |
| P5 network service | `function_task` w/ async HTTP call | Clean (fit) / None (governor) | no rate-limit/cache/backoff primitives |
| P6 in-process | bypass entirely — plain async call | Clean | no forced routing through the engine |
| P7 composite pipeline | `@flow.block` | Clean | nests; own future, state, cancellation |
| P8 external experiment | — | Not evaluated | out of scope |

---

## 10. Maturity signals

- **Version**: 0.5.1, tagged releases back to v0.1.1, real PR-based git history (merge commits,
  `git log` shows `Merge pull request #95 ...`), active as of 2026-08-20.
- **Tests**: 109 test functions across 15 unit files + 3 integration files
  (`tests/unit/test_cancellation.py`, `test_failure_propagation.py` [9 tests], `test_prompt_task.py`
  [13 tests], `test_termination.py` [9 tests], `test_engine_lifecycle.py`, `test_dependencies_*`,
  `test_data_dependencies.py`, `test_capture_stdio.py`, `test_future_state.py`,
  `test_workflow_scope_isolation.py`, `test_block_execution.py`, `test_task_registration_component.py`,
  `test_async.py`) + `tests/integration/{test_multi_backend,test_workflow_failures,
  test_workflow_runs_to_completion}.py`. Coverage config present (`pyproject.toml:78-88`,
  `[tool.coverage.run] source = ["radical.asyncflow"]`); CI runs on GitHub Actions
  (`.github/workflows/tests.yml`).
- **CHANGELOG.md** is detailed, dated, and each entry names the exact fix/behavior change (e.g. block
  future state lifecycle bugs fixed in 0.5.0, non-main-thread event loop crash fixed in 0.5.1) — this
  reads as a project fixing real bugs found in real use, not a stub.
- **TODO/FIXME**: exactly one in the whole `src/` tree — `# FIXME: assign name for this comp (comp
  uid)` (`workflow_manager.py:673`), cosmetic (an internal `asyncio.create_task(...)` isn't given a
  debug name). No other markers found.
- **Docs**: substantial and current — `docs/exec_backends.md`, `docs/telemetry.md`,
  `docs/composite_workflow.md`, `docs/best_practice.md`, `docs/async_workflows.md`,
  `docs/multi_backend.md`, plus a Jupyter tutorial (`tutorials/build_async_workflows.ipynb`) and 7
  runnable examples + 3 telemetry examples with a README each. This is well above "early 0.x throwaway"
  quality for the parts it covers.
- **What is thin**: the backend *protocol* is duck-typed convention, not a formal `Protocol`/ABC
  enforced anywhere in this repo — `_attach_backend` just calls methods and hopes they exist; a
  malformed custom backend would fail at call time with an `AttributeError`, not at registration time
  with a clear contract violation. `prompt_task` (AI-routing) is new-ish and thinly exercised outside
  its own unit test file plus one example paired with a mock backend — no HPC-realistic AI backend
  example exists in this repo.

---

## Verdict on the hypothesis

> "Task execution via asyncflow, rhapsody reached through asyncflow, never called directly."

**Partially true, and the qualification matters for the design.**

- **Task execution genuinely goes through asyncflow.** The `WorkflowEngine` — decorators, dependency
  graph, scheduling loop, futures, failure propagation, cancellation hooks — is real, load-bearing,
  and well-built for exactly the runtime-composed-DAG use case IMPRESS needs (see §2). This part of the
  hypothesis holds up well.
- **"rhapsody is never called directly" is false for execution backends on HPC**, which is IMPRESS's
  primary deployment target (Polaris/Dragon, ACCESS/RADICAL-Pilot per the platform decisions in the
  context doc). Every documented and exemplified HPC path in this repo has application code do
  `from rhapsody.backends import DragonExecutionBackend` / `RadicalExecutionBackend`, construct it, and
  hand it to `WorkflowEngine.create(backend=backend)`. asyncflow does not wrap, re-export, or
  instantiate these for you — it only defines the duck-typed seam they plug into. `NoopExecutionBackend`
  and `LocalExecutionBackend`, which *are* rhapsody-free, only cover dry-run/testing and edge/laptop
  execution — exactly the "edge/laptop/mock testing" case the context doc already carved out as
  secondary.
- **"rhapsody is never called directly" is true for telemetry**, where asyncflow's own source
  (`start_telemetry()`) imports and wraps `rhapsody.telemetry.manager.TelemetryManager` internally, and
  the public surface is `flow.start_telemetry(...)` + `telemetry.subscribe(...)` — genuinely
  intermediated, exactly as hypothesized.

**Recommended framing for the design doc going forward**: "asyncflow is the execution/DAG layer;
rhapsody is a required, directly-imported dependency for any real HPC backend (Dragon on Polaris/Aurora,
RADICAL-Pilot on ACCESS) — asyncflow only intermediates rhapsody for telemetry, not for backend
construction." Treat rhapsody as a first-class, directly-referenced dependency in IMPRESS's own backend
factory code, not as something hidden behind asyncflow.

---

## Open risks

1. **No durable task/job ledger.** All engine state (`components`, `dependencies`, futures) is
   in-process and in-memory, cleared on shutdown. P4's "outlives the agent" requirement and any
   crash-recovery story for the campaign state tree get zero help from asyncflow — this has to be
   built as an IMPRESS-side layer that shadows submitted tasks with a persisted record (submission
   time, external job id, expected poll cadence) independent of the `asyncio.Future` lifecycle.
2. **Flat, global UID namespace** (`task.NNNNNN`, single counter, reset only at shutdown) — no
   built-in way to enumerate "all tasks belonging to cycle 7" or "all futures under lineage X" from the
   engine's public API. IMPRESS's composer must maintain its own cycle→UID / lineage→futures mapping
   alongside asyncflow's, and must consistently use `@flow.block` per cycle/lineage to get a usable
   cancellation handle (see §5) and a `workflow_scope()` telemetry tag together.
3. **Backend protocol is unenforced duck-typing** in this codebase — no formal interface, no
   registration-time validation beyond "does it have `.name`, `.get_task_states_map()`,
   `.register_callback()`." A broken/partial custom backend (if IMPRESS ever needs one, e.g. for P4/P5
   governance) fails late and unclearly.
4. **Executable-task command-string timing nuance** (§2): dependency futures passed positionally do
   not automatically inject resolved values into the command-building function; each `ToolSpec`'s
   task-agent function must know to `await` a dependency's future explicitly if it needs the value.
   Easy to get subtly wrong when composing dozens of tool wrappers generically — worth codifying as a
   convention/lint rule in the composer or the `ToolSpec` contract.
5. **Telemetry requires `rhapsody-py[telemetry]` even for the mock/edge path** — cannot be exercised
   on a pure `Noop`/`Local` backend setup without pulling in rhapsody, which cuts against a fully
   rhapsody-free "edge/laptop/mock" configuration if telemetry parity with HPC runs is desired there.
6. **`prompt_task` is thin** — real, tested, but with only one example (paired with a mock AI backend)
   and no HPC-realistic AI-inference backend shown in this repo. If IMPRESS routes LLM-driven task
   agents through asyncflow's `prompt_task` rather than calling an LLM API directly, expect to be
   pathfinding rather than following a documented pattern.
7. **No retry/backoff primitive anywhere** — confirmed absent by grep. Any retry policy for flaky P4/P5
   tasks is 100% IMPRESS's own code, wrapped around the future-returning call.

---

## Blunt assessment

asyncflow **does** support a runtime-composed DAG driven by an autonomous agent — it was not designed
as a statically-authored-workflow DSL. Its dependency model (pass unawaited Futures as call arguments;
scheduler resolves order from a ready-queue/dependency-count structure, not from literal `await` chains
in source) is, structurally, closer to a dataflow/promise graph than to a script. A single generic
dispatch loop driven by IMPRESS's typed DAG (`futures[node_id] = decorated_fn(*dep_futures, **resources)`)
is enough — no code generation, no AST manipulation, no templating required to get dynamic composition
working. That is a genuine point in favor of the architecture the user described.

What IMPRESS has to build on top, because asyncflow deliberately does not provide it: a durable
external-job ledger (P4), resource-shape normalization across backends (asyncflow's own examples show
two incompatible `task_description` shapes for Dragon vs. RADICAL-Pilot in the same release), a
per-cycle/lineage bookkeeping layer (UID namespace is flat and global), rate-limiting/caching/backoff
governance for P5, and any retry policy at all. None of these are asyncflow gaps in the sense of "not
yet implemented, coming soon" — they are explicitly out of scope by design (backend abstraction is
intentionally minimal; "write-once, run-anywhere" is about *execution*, not about job durability or
resource portability). And on the central "rhapsody is reference-only" claim: it holds for telemetry,
it does not hold for the execution backend that actually runs jobs on Polaris/Aurora/ACCESS — rhapsody
will appear as a direct, named import in IMPRESS's own backend-construction code, not just in a
reference repo nobody imports from.
