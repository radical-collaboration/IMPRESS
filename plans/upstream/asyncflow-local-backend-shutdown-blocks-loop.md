# radical.asyncflow: LocalExecutionBackend.shutdown joins its pool synchronously on the event loop

**Component:** radical.asyncflow 0.7.0 (`src/radical/asyncflow/backends.py`, checked at
`482f166`) · **Severity:** deadlock at engine shutdown · **Status:** diagnosed, not reported
upstream
**Evidence:** faulthandler dump, 2026-11-11, of a hung IMPRESS test: the main thread is in
`ThreadPoolExecutor.shutdown -> Thread.join` from `backends.py:414`, and a pool thread is in
`asyncio.run` (`backends.py:292`, `_run_in_thread`), waiting on a future that only the main loop
can resolve.

## What we saw

`await flow.shutdown()` never returned. A function task routed to a thread-pool
`LocalExecutionBackend` was still running, and its body was waiting for something scheduled
on the engine's loop: a result relayed from another task, submitted with
`call_soon_threadsafe`.

## Cause

`LocalExecutionBackend.shutdown` (`backends.py:410-415`) is a coroutine that calls
`self.executor.shutdown(wait=True)` directly (`:414`). That joins every worker thread while
holding the event loop. A thread task needing anything from the loop before it can finish
(a threadsafe callback, a future set from a loop callback) can never get it. The rhapsody
concurrent backend has the same shape (`concurrent.py`'s `shutdown`).

## Fix

Do not block the loop while joining:

```python
async def shutdown(self) -> None:
    await self.cancel_all_tasks()
    await asyncio.to_thread(self.executor.shutdown, wait=True)
```

Optionally pass `cancel_futures=True` so queued-but-unstarted work is dropped.

## Impact on us

IMPRESS-A runs each node's adapter as a function task on a thread-pool `local` route, and the
adapter waits on commands submitted back to the engine loop. Local workaround: a cancelled or
failed Stage is not reaped until every adapter thread has left
(`agent/src/impress_a/exec/stage.py: StageExecutor._settle`, `exec/launch.py: Launcher.idle`),
so no adapter is mid-wait when the engine shuts down.
