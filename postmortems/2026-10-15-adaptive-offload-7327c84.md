**Subject:** `ImpressManager` adaptive-function offload (commit `7327c84`, framework defaults PR 1, bullet 4)
**Written:** 2026-10-15 · **Reviewed against:** `framework-defaults-pr1` @ `f12c2cb`, radical.asyncflow 0.5.1

# `7327c84` bullet 4: "ImpressManager runs adaptive functions off the event loop by default"

## What it is fixing

One asyncio loop drives every pipeline: task dispatch, subprocess reaping, Dragon
completion handling. Before this commit the manager called the user's adaptive callback
directly on that loop (`await adaptive_fn(pipeline)`). In job `22534628` (8 nodes /
32 pipelines) `adaptive_decision` was declared `async def` with **zero `await`** in a
220-line body that did blocking Lustre reads, so each call owned the loop outright.
Adaptive occupancy of manager wall clock went 3.4% at 16 pipelines → **67.1%** at 32,
p99 per-call 1.36s → 56.0s with the median flat (a serial server crossing saturation),
GPU utilisation fell to 0.7%, and the run finished at **37% of the 4-node baseline** —
0.666 GPU-h per passing fold against 0.194. Full write-up:
`examples/small_molecule_binding/plans/2026-09-30-adaptive-callback-serialization.md`.
Fix validated at scale on `22701168`: 0.96% occupancy, p99 0.071s over 13,074 calls.

The example had fixed it locally (wrap the callback in `flow.function_task(backend="local")`
at the call site). This bullet moves that into the framework so no workflow can reintroduce
the defect by writing an ordinary-looking callback.

## The code path, line by line

**Entry, unchanged.** `ImpressBasePipeline.run_adaptive_step()`
(`src/impress/pipelines/impress_pipeline.py:189`) sets `invoke_adaptive_step=True`, clears
`_adaptive_barrier` (`:200-204`), and awaits it (`:206-208`). The manager's poll loop sees
the flag and spawns one background task per pipeline
(`src/impress/impress_manager.py:211-219`), and refuses to retire a pipeline until that task
is done (`:240-247`, `:255-259`). So a pipeline is *blocked* on its own adaptive call either
way — the serialization this bullet removes is the cross-pipeline one.

**`_run_adaptive_fn` (`impress_manager.py:115-137`)** is the only changed line in the old
body: `:131` now calls `self._invoke_adaptive_fn(...)` instead of `await adaptive_fn(pipeline)`.
Two supporting edits: the annotation at `:127` widened from `Callable[..., Awaitable[None]]`
to `Callable[..., Any]` (sync callbacks are now legal — hence `Awaitable` dropped from the
imports at `:3`), and the `except`/`finally` at `:133-137` now also covers the off-loop paths,
so an exception raised in a worker thread still logs `adaptive_failed` and still sets the
barrier. Without that last part an offloaded crash would hang its pipeline forever
(`test_offloaded_exception_still_releases_barrier`).

**`_invoke_adaptive_fn` (`:139-154`)** is the dispatcher, three branches:

- `:146-148` — escape hatch and pass-through. `not self.adaptive_offload` runs the callback
  inline on the loop, the old behaviour, for a callback that must await objects bound to the
  main loop (an engine future, for instance). `_is_flow_task(adaptive_fn)` means the caller
  already wrapped it themselves — it dispatches to a backend on its own, so wrapping it again
  would be wrong. Note: in this branch a *sync* callback is called inline, i.e.
  `adaptive_offload=False` plus a blocking body is exactly the original defect, which is why
  `examples/small_molecule_binding/CLAUDE.md:184` tells you not to pass it.
- `:150-152` — preferred path: run as a function task on a backend named `local`, awaited,
  labelled `{pipeline}:adaptive`.
- `:153-154` — fallback: `asyncio.to_thread(_run_to_completion, adaptive_fn, pipeline)`.
  Same off-loop property, but unbounded (one thread per concurrent call) and invisible to
  telemetry.

**`_local_backend_task` (`:156-176`)** is where most of the subtlety lives, and every line maps
to an upstream fact in `radical/asyncflow/workflow_manager.py`:

- `:162-164` — `getattr(self.flow, "_backends", None)` with an `isinstance(dict)` guard. The
  engine's backend table is private (`workflow_manager.py:90`, populated at `:155`), there is
  no public accessor, and the guard is what lets the manager work against a flow object that
  doesn't have one at all — the unit `MockWorkflowEngine` (`tests/conftest.py:17`) has no
  `_backends`, so those tests exercise the `to_thread` branch. This private-attribute
  dependency is logged as an upstream ask in `plans/2026-10-08-framework-deferred.md:37`.
- `:165-166`, `:175` — `self._offloaded_fns` (declared at `:62`) memoises the registration,
  keyed on the callback object. All 32 pipelines pass the *same* function, so the task is
  registered once and reused; `test_uses_local_backend_when_present` asserts
  `flow.registered == [("adaptive_decision", "local")]` after two pipelines.
- `:168-169` — the `async def run_adaptive` shim exists because `flow.function_task` rejects
  non-coroutine functions outright (`workflow_manager.py:666`: "must be async"), and the whole
  point of the bullet is that a plain `def` is now accepted. `_maybe_await` inside it handles
  the case where the callback *is* a coroutine function.
- `:171-173` — renaming `run_adaptive.__name__`/`__qualname__` to the callback's name. asyncflow
  names a component from the function it registers (`workflow_manager.py:714`:
  `comp_desc["name"] = comp_desc["function"].__name__`), so without this every adaptive task
  would appear in telemetry as `run_adaptive`. The test asserts the registered name is
  `adaptive_decision`.
- `:174` — `self.flow.function_task(backend="local")` (`workflow_manager.py:119`) routes to that
  named backend.
- `:152` — `workflow_id=f"{pipeline.name}:adaptive"` is popped from call kwargs by asyncflow
  (`workflow_manager.py:617`) and takes precedence over the ContextVar (`:716-718`), landing as
  `asyncflow.workflow_id` on the events. Same mechanism `auto_register_task` uses for
  `{pipeline}:{stage}` in bullet 1.

**Module helpers (`:317-337`)**

- `_is_flow_task` (`:317-323`) tests for `__task_description__`. asyncflow sets that attribute on
  the decorated function (`workflow_manager.py:524`) and the `@wraps(func)` immediately below
  (`:525`) copies it onto the wrapper the decorator returns — so the mark survives on the object
  a caller holds. `test_flow_task_passed_through` relies on exactly this.
- `_maybe_await` (`:326-329`) is the sync/async tolerance: `inspect.isawaitable` on the result,
  await only if needed.
- `_run_to_completion` (`:332-337`) is the `to_thread` body. It calls the function in the worker
  thread and, if the result is awaitable, drives it with `asyncio.run` — a *new* loop in that
  thread. That is the mechanical reason `adaptive_offload=False` exists: anything bound to the
  main loop cannot be awaited from here.

## What the callers lost

In `examples/small_molecule_binding/run_small_molecule_binding.py` the commit deleted
`adaptive_fn = flow.function_task(backend="local")(adaptive_decision)` and passes
`adaptive_fn=adaptive_decision` directly; `adaptive_decision` lost its `async def` wrapper and
the `_adaptive_decision_sync` split and is now a plain `def`. The `local` backend itself stays in
the runner (`ConcurrentExecutionBackend(ThreadPoolExecutor(max_workers=cfg.n_pipelines),
name="local")`) — it is the *name* `local` that the framework now looks for.
`docs/concepts/architecture.md:138-156` documents the contract, including that the backend must
be a **thread** pool: the callback mutates the live `pipeline.state`, and a process pool would
mutate a pickled copy.

## Properties worth keeping in mind

- **Bounded vs unbounded.** With a `local` backend, concurrency is capped by its pool; without
  one, `to_thread` spawns per call (default executor caps at `min(32, cpu+4)`, so it queues
  rather than explodes, but it is not sized by you).
- **No new intra-pipeline race.** The manager still awaits a pipeline's adaptive task before that
  pipeline advances, so there is no concurrent writer to one pipeline's `state`. What *is* new is
  that callbacks for different pipelines now run in parallel threads — any module-level cache the
  callback shares (`_FASTA_SEQ_CACHE`, the `lru_cache`d PDB reader) is now touched from several
  threads at once. Noted in the docs at `:155-156`.
- **Tests.** `tests/unit/test_manager_adaptive_logic.py` `TestAdaptiveOffload` covers all of it:
  the loop keeps ticking during a 0.5s blocking callback, an awaitless `async def` lands
  off-thread, a sync callback's mutation is visible on the live pipeline,
  `adaptive_offload=False` runs on the loop thread, the `local` backend is used and registered
  once with the right label, an already-wrapped flow task is not double-wrapped, and a raising
  callback still releases the barrier.
