# rhapsody: ConcurrentExecutionBackend.cancel_task leaves a running executable's process alive

**Component:** rhapsody-py 0.7.0 (`src/rhapsody/backends/execution/concurrent.py`, checked at
`aca8e3e`) · **Severity:** resource leak; a cancelled GPU task keeps its GPU · **Status:**
diagnosed, not reported upstream
**Evidence:** reproduced 2026-11-11 on a Delta login node with asyncflow 0.7.0 on top (below).
Found on IMPRESS branch `agent/one-engine`, backlog `agent/plans/backlog.md` I2.

## What we saw

An executable task that is `RUNNING` is cancelled through asyncflow 0.7.0, which sends the cancel
to the task's own backend (asyncflow #118). The task's future resolves `CANCELLED`, but the child
process runs on to completion:

```python
flow = await WorkflowEngine.create(backend=await ConcurrentExecutionBackend(
    ProcessPoolExecutor(2), name="compute"))

@flow.executable_task
async def s():
    return "sleep 47.5"

fut = s()
while fut.state != "RUNNING":
    await asyncio.sleep(0.05)
fut.cancel()
# pgrep -x sleep -a | grep 47.5  ->  still present 1 s after the future is CANCELLED
```

## Cause

`cancel_task` (`concurrent.py:283-300`) calls `future.cancel()` on the asyncio Task that wraps
`_handle_task`. That raises `CancelledError` inside `_execute_command` at
`await process.communicate()` (`:232`) or `await process.wait()` (`:227`). The surrounding
`try/finally` (`:236-240`) closes only the capture files; nothing terminates `process`. An
asyncio subprocess is not killed when the coroutine awaiting it is cancelled.

## Fix

In `_execute_command`, catch `asyncio.CancelledError` around the wait, terminate the process,
then kill it after a grace period, reap it, and re-raise:

```python
except asyncio.CancelledError:
    if process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
    raise
```

`cancel_all_tasks` (`:302-308`, used by `shutdown`) gets the same behaviour for free.

## Impact on us

On IMPRESS-A, every tool command is an executable task. Without the fix, a cancelled Stage's
running commands hold their GPU until they finish. Local workaround: each command is wrapped
in coreutils `timeout --kill-after=10 <walltime>` (`agent/src/impress_a/exec/launch.py`), so a
command cannot outlive its declared walltime by more than the grace. That bounds the leak; it
does not reclaim the GPU at cancel time.
