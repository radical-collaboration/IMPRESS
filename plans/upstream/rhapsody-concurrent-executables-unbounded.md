# rhapsody: ConcurrentExecutionBackend runs executables without any concurrency bound

**Component:** rhapsody-py 0.7.0 (`src/rhapsody/backends/execution/concurrent.py`, checked at
`aca8e3e`) · **Severity:** oversubscription; `workers` silently does not apply to executables ·
**Status:** diagnosed, not reported upstream
**Evidence:** IMPRESS `agent/tests/test_stage_block.py::test_cancelling_a_stage_stops_queued_commands_and_accounts_for_every_node`,
first version: with `ConcurrentExecutionBackend(ProcessPoolExecutor(1))` all three submitted
executables started at once (3 start markers where 1 was expected). 2026-11-11.

## What we saw

A backend built with an executor of one worker starts every submitted executable immediately.
The executor's size bounds only function tasks.

## Cause

`submit_tasks` (`concurrent.py:265-280`) creates one asyncio Task per task (`:275`), with no
semaphore. Function tasks then queue on the executor through `run_in_executor` (`:164`), but
`_execute_command` (`:175`) starts the child directly with
`asyncio.create_subprocess_exec`/`_shell` (`:209`, `:218`). The executor is never consulted, so
nothing bounds how many executables run at once. `topology()` (`:104-112`) even reports cores
capped at the executor's `_max_workers`, describing a capacity that executables do not respect.

## Fix

Bound executables by the same capacity, so that a backend's size means one thing. Either:

- an `asyncio.Semaphore(max_workers)` acquired in `_execute_command` around the subprocess, or
- run the subprocess wait inside the executor, as function tasks are run.

The first is smaller and keeps executables off the pool's threads. A separate
`max_concurrent_executables` constructor argument is fine if mixing the two is intended.

## Impact on us

IMPRESS-A moved tool commands from function tasks (bounded) to executable tasks (unbounded),
so a campaign's `workers: N` would have stopped meaning "N tools at once" on every non-Dragon
run. Local workaround: a per-engine semaphore sized from `workers`
(`agent/src/impress_a/exec/stage.py: command_slots`, `exec/launch.py: Launcher.slots`), applied
only to the concurrent backend. It is removed when this is fixed.
