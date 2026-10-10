# Architecture

IMPRESS is built from four cooperating pieces: an `ImpressManager` that
orchestrates execution, `ImpressBasePipeline` subclasses that define
individual workflows, `PipelineSetup` objects that declare how a pipeline
should be submitted, and a `radical.asyncflow` `WorkflowEngine` (bound to an
execution backend) that actually runs each task. This page describes how they fit together. For a
worked, line-by-line example, see [Adaptive Execution](adaptive-execution.md);
for full method-level detail, see the [API Reference](../reference/index.md).

## ImpressManager

`ImpressManager` is the central orchestrator. It runs pipelines on a
`radical.asyncflow.WorkflowEngine` that **you** create and pass in. The
caller owns the engine: create it from an execution backend (a local
thread/process pool for testing, or an HPC backend such as
`DragonExecutionBackend`/`RadicalExecutionBackend` for production runs),
hand it to the manager, and shut it down when done. The manager never
creates or shuts down the flow.

```python
flow = await WorkflowEngine.create(backend=my_backend)
manager = ImpressManager(flow)
try:
    await manager.start(pipeline_setups=[...])
finally:
    await flow.shutdown()
```

`ImpressManager` also accepts `use_colors` (console log coloring),
`telemetry_config` (kwargs forwarded to `flow.start_telemetry()`, e.g.
`checkpoint_path`, `resource_poll_interval`; `None` disables telemetry), and
`telemetry_subscribers` (callables registered on the telemetry stream right
after it starts). When telemetry is enabled, the handle is available as
`manager.telemetry`.

`start()` is the only real entry point, and its lifecycle is a simple
cooperative polling loop:

1. (Optionally) start telemetry on the supplied engine.
2. Submit every initial `PipelineSetup` as a running `asyncio.Task`.
3. Poll all live pipelines on a tight loop (sleeping briefly when nothing
   changed):
   - If a pipeline has flagged `invoke_adaptive_step`, launch its adaptive
     function as a background task.
   - If a pipeline has a pending child-pipeline request, buffer it as a new
     `PipelineSetup`.
   - If a pipeline has set `kill_parent`, cancel its task.
   - Track which pipelines and adaptive tasks have finished. A pipeline
     whose `run()` raised is logged as failed (`pipeline_failed`, with the
     exception) rather than completed; the manager keeps running the rest.
   - Submit any buffered child pipelines.
4. Exit once there are no running pipeline tasks, no running adaptive
   tasks, and nothing buffered.

The important invariant here — confirmed by the test suite — is that
`start()` does not return until **both** a pipeline's `run()` coroutine
*and* any adaptive task it triggered have completed. A pipeline whose
`run()` finishes quickly but whose adaptive function is still evaluating
results will keep the manager alive until that adaptive function resolves.

## ImpressBasePipeline

Every workflow subclasses `ImpressBasePipeline` and implements two
required methods, plus one optional one:

- **`register_pipeline_tasks()`** — called once, synchronously, from
  `__init__`, before anything else runs. Use `@self.auto_register_task()`
  here to bind coroutines as callable task methods.
- **`run()`** — the pipeline's control flow: call the registered task
  methods, and call `await self.run_adaptive_step(...)` at points where the
  pipeline should evaluate intermediate results.
- **`finalize()`** *(optional; default no-op)* — cleanup/bookkeeping
  logic, typically invoked by a pipeline's own adaptive function after it
  spawns a child pipeline (for example, to remove migrated work items from
  the parent's tracking state).

`auto_register_task(local_task=False, capture_stdio=True, **task_kwargs)`
decides how a task runs: by default it wraps the function via
`self.flow.executable_task(**task_kwargs)`, submitting it as an
HPC-executable task through the workflow engine; with `local_task=True` the
function runs as a plain in-process coroutine (used for lightweight local
work like parsing a CSV or ranking sequences).

Defaults that every pipeline gets without asking:

- **stdio is captured.** An executable task's stdout and stderr go to
  `{task uid}.stdout` / `.stderr` in the backend's work dir, which is
  `{work_dir}/{engine uid}` for the `work_dir` passed to
  `WorkflowEngine.create()`. The task's future then resolves to the stdout
  file path, not the text; pass `capture_stdio=False` to get the text.
- **failures explain themselves.** When an executable task fails, the last
  lines of its captured stderr are logged and attached to the exception as
  a note (Python 3.11+). Without this, the error is only a file path or an
  exit code.
- **tasks are labelled.** Each call is tagged `{pipeline}:{stage}` in
  telemetry unless the caller passes `workflow_id=`. Otherwise asyncflow
  names a task after its executable, which is usually just `bash`.
- **local tasks are traced.** Each call of a `local_task=True` stage emits
  one `impress.LocalStage` telemetry event (stage, pipeline, duration,
  status), since local tasks never reach the engine.

For a per-task log file next to a task's outputs, return
`self.logged_command(log_file, cmd)` instead of `cmd`.

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
   pipeline's registered `adaptive_fn(pipeline)` as a background task,
   **off the event loop** (see below).
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

**Adaptive functions run off the event loop.** One event loop drives every
pipeline's task dispatch, so an adaptive function that blocks it, even an
`async def` that never awaits, stalls all pipelines while it runs. On an
8-node, 32-pipeline run this held the loop for 67% of wall clock and cut
throughput to 37% of baseline. The manager therefore runs each adaptive
function in a worker thread, against the live pipeline object:

- If the engine has a backend named `local`, the function runs there as a
  `flow.function_task`, which bounds concurrency and shows it in telemetry
  as `{pipeline}:adaptive`. Use a thread-pool backend for it, such as
  `ConcurrentExecutionBackend(ThreadPoolExecutor(), name="local")`: a
  process pool would mutate a pickled copy of the pipeline.
- Otherwise it runs in `asyncio.to_thread`.
- A function that is already a flow task runs as it is.

Pass `ImpressManager(..., adaptive_offload=False)` for an adaptive function
that must await objects bound to the main loop, such as engine tasks.
Module-level caches an adaptive function shares across pipelines may now be
touched from several threads at once.

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
- `adaptive_fn` — optional `adaptive_fn(pipeline) -> None`, a plain
  function or a coroutine function.
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
pipeline failures, and periodic activity summaries (at DEBUG level). All
levels, including ERROR and CRITICAL, are written to the logger's
`output_stream` (default `sys.stdout`); a `min_level` argument drops
messages below a given `LogLevel`. Most users only interact with it
indirectly, through the `use_colors` argument on `ImpressManager`, or by
calling `self.logger.pipeline_log(...)` from within a pipeline's own
`run()`.

## Execution backends

The execution backend is any backend object supported by
`radical.asyncflow`. For local development and testing, use
`LocalExecutionBackend` (from `radical.asyncflow`) wrapping a
`ThreadPoolExecutor` or `ProcessPoolExecutor`. For HPC production runs, use
a backend from [`rhapsody`](https://pypi.org/project/rhapsody-py/)
(`rhapsody.backends`): `DragonExecutionBackend`/`DragonExecutionBackendV3`,
`RadicalExecutionBackend` (configured with resource requirements such as
GPUs, cores, runtime, and target machine), or
`ConcurrentExecutionBackend`.

IMPRESS itself is agnostic to which backend is used. You build the engine
with `WorkflowEngine.create(backend=...)`, pass it to `ImpressManager`, and
every task registered with `auto_register_task()` is submitted through that
engine.
