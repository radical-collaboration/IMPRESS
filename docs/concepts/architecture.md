# Architecture

IMPRESS is built from four cooperating pieces: an `ImpressManager` that
orchestrates execution, `ImpressBasePipeline` subclasses that define
individual workflows, `PipelineSetup` objects that declare how a pipeline
should be submitted, and a `radical.asyncflow` execution backend that
actually runs each task. This page describes how they fit together. For a
worked, line-by-line example, see [Adaptive Execution](adaptive-execution.md);
for full method-level detail, see the [API Reference](../reference/index.md).

## ImpressManager

`ImpressManager` is the central orchestrator. It owns a
`radical.asyncflow.WorkflowEngine` bound to whatever execution backend you
pass in (a local thread/process pool for testing, or an HPC backend such as
`RadicalExecutionBackend`/`DragonExecutionBackendV3` for production runs).

```python
manager = ImpressManager(execution_backend=my_backend)
await manager.start(pipeline_setups=[...])
```

`start()` is the only real entry point, and its lifecycle is a simple
cooperative polling loop:

1. Create the `WorkflowEngine` and (optionally) start telemetry.
2. Submit every initial `PipelineSetup` as a running `asyncio.Task`.
3. Poll all live pipelines on a tight loop (sleeping briefly when nothing
   changed):
   - If a pipeline has flagged `invoke_adaptive_step`, launch its adaptive
     function as a background task.
   - If a pipeline has a pending child-pipeline request, buffer it as a new
     `PipelineSetup`.
   - If a pipeline has set `kill_parent`, cancel its task.
   - Track which pipelines and adaptive tasks have finished.
   - Submit any buffered child pipelines.
4. Exit once there are no running pipeline tasks, no running adaptive
   tasks, and nothing buffered.

The important invariant here — confirmed by the test suite — is that
`start()` does not return until **both** a pipeline's `run()` coroutine
*and* any adaptive task it triggered have completed. A pipeline whose
`run()` finishes quickly but whose adaptive function is still evaluating
results will keep the manager alive until that adaptive function resolves.

## ImpressBasePipeline

Every workflow subclasses `ImpressBasePipeline` and implements three
methods:

- **`register_pipeline_tasks()`** — called once, synchronously, from
  `__init__`, before anything else runs. Use `@self.auto_register_task()`
  here to bind coroutines as callable task methods.
- **`run()`** — the pipeline's control flow: call the registered task
  methods, and call `await self.run_adaptive_step(...)` at points where the
  pipeline should evaluate intermediate results.
- **`finalize()`** — cleanup/bookkeeping logic, typically invoked by a
  pipeline's own adaptive function after it spawns a child pipeline (for
  example, to remove migrated work items from the parent's tracking state).

`auto_register_task(local_task=False, **task_kwargs)` decides how a task
runs: by default it wraps the function via
`self.flow.executable_task(**task_kwargs)`, submitting it as an
HPC-executable task through the workflow engine; with `local_task=True` the
function runs as a plain in-process coroutine (used for lightweight local
work like parsing a CSV or ranking sequences).

A pipeline's `self.state` dict is the conventional place to pass data
between stages — task methods write intermediate results into it (file
paths, scores, directories), and later stages or the adaptive function read
them back out.

## The adaptive / branching protocol

"Adaptive" in IMPRESS means a pipeline can pause at a checkpoint, hand
control to an external decision function, and optionally spawn new sibling
pipelines based on what that function decides — without any of this being
expressed as a static graph.

1. Inside `run()`, the pipeline calls `await self.run_adaptive_step(wait=True)`
   (or `wait=False` to continue concurrently). This sets
   `invoke_adaptive_step = True`.
2. On its next poll, `ImpressManager` notices the flag and runs the
   pipeline's registered `adaptive_fn(pipeline)` coroutine as a background
   task.
3. `adaptive_fn` inspects/mutates the pipeline's `state` and attributes
   (for example, comparing a current score against a previous one), and may
   call `pipeline.submit_child_pipeline_request(new_config)` to request
   that a new pipeline be launched.
4. When `adaptive_fn` completes (or raises — exceptions are caught and
   logged, never propagated), the manager clears `invoke_adaptive_step` and
   unblocks anything waiting on `run_adaptive_step(wait=True)`.
5. Separately, on every poll tick, the manager calls
   `pipeline.get_child_pipeline_request()` on every live pipeline. If one
   returns a config, it's converted to a `PipelineSetup` and submitted as a
   new pipeline.
6. A pipeline can set `self.kill_parent = True` at any point to have the
   manager cancel its own task on the next tick (self-termination).

Because child pipelines can themselves have an `adaptive_fn` that spawns
further children, this protocol supports arbitrarily deep or wide trees of
self-spawning pipelines, all drained by the same manager loop before
`start()` returns. The three example workflows under
[Examples](../examples/protein-binding.md) each use this protocol
differently — see each page's Adaptive Flow section for specifics.

## PipelineSetup

`PipelineSetup` is a Pydantic model describing one pipeline submission:

- `name` — pipeline instance name.
- `type` — the `ImpressBasePipeline` subclass to instantiate (validated to
  actually be one).
- `config` — configuration dict merged into the pipeline's constructor
  kwargs.
- `adaptive_fn` — optional `async def adaptive_fn(pipeline) -> None`.
- `kwargs` — additional constructor kwargs.

`PipelineSetup.from_dict()`/`.to_dict()` let a plain dict (such as the
config dict returned from `get_child_pipeline_request()`, which often
carries arbitrary extra keys like `parent_name` or `generation`) round-trip
cleanly into a `PipelineSetup` and back.

## ImpressLogger

`ImpressLogger` is a small, hand-rolled colorized console logger used
internally by both `ImpressManager` and `ImpressBasePipeline` (via
`self.logger`) to report lifecycle events — pipeline start/completion,
adaptive function start/completion/failure, child pipeline submission, and
periodic activity summaries. Most users only interact with it indirectly,
through the `use_colors` argument on `ImpressManager`, or by calling
`self.logger.pipeline_log(...)` from within a pipeline's own `run()`.

## Execution backends

`execution_backend` is any backend object supported by
`radical.asyncflow` — for local development and testing,
`ConcurrentExecutionBackend`/`LocalExecutionBackend` wrapping a
`ThreadPoolExecutor` or `ProcessPoolExecutor`; for HPC production runs,
`RadicalExecutionBackend` or `DragonExecutionBackendV3`, configured with
resource requirements (GPUs, cores, runtime, target machine). IMPRESS itself
is agnostic to which backend is used — it only calls
`WorkflowEngine.create(backend=execution_backend)` and submits executable
tasks through the resulting engine.
