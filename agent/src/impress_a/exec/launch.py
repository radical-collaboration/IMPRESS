"""The seam between a tool adapter and the engine: every command a node runs is an engine task.

A node's adapter - pre-process, parameterize, run, post-process, QC - runs as a function task
on the engine's `local` route: a thread in the campaign's own process, with its own event loop
(asyncflow runs each with `asyncio.run`). When that adapter shells out through
`tools._subprocess.run_cmd`, the command does not start there. It is submitted back to the
engine as an `executable_task` on the `compute` route, carrying this node's `Placement`, so
the backend - Dragon on Delta - places it: on a host, on the node's GPU, with its thread share.

That is the difference from what this replaces. The whole node used to be one opaque Python
`function_task` on `compute` with no task description at all, so the backend scheduled a
Python callable and never saw the binary it started; Dragon's GPU placement could not apply,
and the comment saying "there the placement policy pins" described a policy nobody set.

Commands cross a thread boundary here: the adapter's loop is not the engine's, and a
`WorkflowEngine` belongs to the loop it was built on (jobs 22328172/22328262). Submission is
therefore handed to the engine loop, and only the result comes back.

**Commands are members of their Stage's block.** asyncflow records a task as a block member
when it registers inside the block's context (its own context variable, read at registration;
an explicit `workflow_id` is only a label). A command submitted from the adapter's thread would
register in no block at all, so a Stage's cancel would never reach it. The `Launcher` is built
inside the block body and keeps a copy of that context, and every command's submission runs in
a copy of it - so the block's cancel cascade reaches the command on its backend.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import re
import shlex
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..tools._subprocess import SubprocessError
from .backend import COMPUTE
from .resources import KILL_GRACE_S, Placement

#: How often the engine-side watcher checks whether a submitted command has started. Only
#: the queued/ran split depends on it; the result does not.
_POLL_S = 0.05

#: `timeout`'s exit status when it had to stop the command (124), or kill it (137 = 128+9).
_TIMED_OUT = {124, 137}


def _task_name(node: str, cmd: Sequence[str]) -> str:
    """`<node>.<program>`: asyncflow names a task after its function, so this is the label
    every telemetry event and trace carries for the command."""
    prog = Path(str(cmd[0])).name if cmd else "cmd"
    return re.sub(r"[^A-Za-z0-9_.]", "_", f"{node}.{prog}")


def _read(path_or_text: Any) -> str:
    """A captured stream: asyncflow hands back a file path when `capture_stdio` is set."""
    if not path_or_text:
        return ""
    p = Path(str(path_or_text))
    try:
        if p.is_file():
            return p.read_text(errors="replace")
    except OSError:
        pass
    return str(path_or_text)


class Launcher:
    """Runs one node's commands on the engine's `compute` route.

    Built on the engine loop when the node is submitted; used from the adapter's thread.
    Accumulates how long the node's commands waited in the backend's queue, so measured cost
    can exclude it - a task that waited is not a task that was slow.
    """

    def __init__(self, flow: Any, loop: asyncio.AbstractEventLoop, node: str,
                 placement: Placement, workflow_id: str | None = None,
                 context: contextvars.Context | None = None,
                 slots: asyncio.Semaphore | None = None) -> None:
        self.flow, self.loop, self.node = flow, loop, node
        #: Commands this ENGINE may run at once, where the backend does not bound them itself.
        #: A STOPGAP for rhapsody's concurrent backend, which runs every executable as its own
        #: asyncio subprocess and bounds only function tasks by its `workers` - so with tools as
        #: executables, `workers: 1` would start every command at once. Shared by every
        #: Launcher on the engine; `None` (Dragon, whose Batch has its own capacity) is no
        #: bound. Remove when rhapsody bounds executables.
        self.slots = slots
        self.placement = placement
        self.workflow_id = workflow_id
        #: The context commands are submitted in: the Stage block's, when built inside one.
        self.context = context
        #: Engine futures of this node's commands that have not finished.
        self.inflight: set[Any] = set()
        #: Submissions handed to the engine loop that have not finished - including one still
        #: waiting for a command slot, which has no engine future yet.
        self.pending: set[asyncio.Task] = set()
        self.cancelled = False
        #: Set while the node's adapter is NOT running in its thread. A cancelled Stage is not
        #: settled until every adapter has left, because the engine's `local` backend joins its
        #: threads synchronously on the engine loop at shutdown - an adapter still waiting on a
        #: command there would deadlock it - and because a reservation must not be released
        #: while work it paid for is still running.
        self.idle = asyncio.Event()
        self.idle.set()
        #: Seconds this node's commands spent submitted but not yet running.
        self.queued_s = 0.0
        #: Seconds they spent running, as the backend reported them started and finished.
        self.ran_s = 0.0
        self.commands = 0

    async def run(self, cmd: Sequence[str], *, cwd: Any = None,
                  env: dict[str, str] | None = None,
                  timeout_s: float | None = None) -> tuple[str, str]:
        """`run_cmd`'s contract, on the engine: `(stdout, stderr)`, or `SubprocessError`.

        Called from the adapter's own loop. Cancelling the caller cancels the engine task too,
        which asyncflow sends to the backend that runs it; whether a running process actually
        dies is the backend's business (see `docs/impress-a/limitations.md`), which is one
        reason every command also carries its own `timeout`.
        """
        if self.cancelled:
            raise asyncio.CancelledError(f"{self.node}: its Stage was cancelled")
        cfut: concurrent.futures.Future = concurrent.futures.Future()
        coro = self._submit_and_wait(list(map(str, cmd)), cwd, env, timeout_s)
        self.loop.call_soon_threadsafe(self._start, coro, cfut)
        try:
            return await asyncio.wrap_future(cfut)
        except asyncio.CancelledError:
            cfut.cancel()
            raise

    def _start(self, coro: Any, cfut: concurrent.futures.Future) -> None:
        """On the engine loop: run `coro` in a copy of the Stage's context, relay its outcome.

        `create_task(..., context=)` rather than `run_coroutine_threadsafe`, which offers no
        way to choose the context - and the context is what makes the command a block member.
        A copy per command, because one `Context` may not be entered by two tasks at once.
        """
        if cfut.cancelled() or self.cancelled:
            coro.close()
            cfut.cancel()
            return
        ctx = self.context.copy() if self.context is not None else None
        task = self.loop.create_task(coro, context=ctx)
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

        def relay(t: asyncio.Task) -> None:
            if cfut.done():
                return
            if t.cancelled():
                cfut.cancel()
            elif t.exception() is not None:
                cfut.set_exception(t.exception())
            else:
                cfut.set_result(t.result())

        task.add_done_callback(relay)
        cfut.add_done_callback(
            lambda f: self.loop.call_soon_threadsafe(task.cancel) if f.cancelled() else None)

    def cancel(self) -> None:
        """Refuse further commands and cancel the running ones. On the engine loop.

        The block's cascade already cancels member commands; this also stops an adapter that
        is between commands from starting another one after its Stage was abandoned.
        """
        self.cancelled = True
        for fut in list(self.inflight):
            fut.cancel()
        for task in list(self.pending):
            task.cancel()

    def entered(self) -> None:
        """The adapter started in its thread. Thread-safe."""
        self.loop.call_soon_threadsafe(self.idle.clear)

    def left(self) -> None:
        """The adapter returned or raised in its thread. Thread-safe."""
        self.loop.call_soon_threadsafe(self.idle.set)

    async def _submit_and_wait(self, cmd: list[str], cwd: Any, env: dict[str, str] | None,
                               timeout_s: float | None) -> tuple[str, str]:
        """On the engine loop: submit one executable task, wait for it, translate the outcome.

        The command is wrapped in coreutils `timeout`, which sends TERM at the walltime and
        KILL `KILL_GRACE_S` later. The adapter's old in-process timeout killed its child; a
        backend's cancel may not (rhapsody's concurrent backend cancels its own coroutine and
        leaves the process running), so the bound has to travel with the command to hold on
        every backend.
        """
        argv = list(cmd)
        if timeout_s and not self.placement.dragon:
            # NOT under Dragon, which bounds the command itself (`Placement.describe` passes
            # its `timeout`) - and must: coreutils `timeout` makes itself a process-group
            # leader, and Dragon's local services reaps only children in ITS group
            # (`os.waitpid(0, ...)`, dragon localservices/server.py), so a wrapped command
            # exits, is never reaped, and its task never completes. Measured on job 23814643:
            # both rfd3 commands finished at 16:40 and sat as `[timeout] <defunct>` zombies.
            argv = ["timeout", f"--kill-after={KILL_GRACE_S}", f"{float(timeout_s):g}", *argv]
        line = shlex.join(argv)

        async def command() -> str:
            return line

        command.__name__ = _task_name(self.node, cmd)
        task = self.flow.executable_task(command, backend=COMPUTE, capture_stdio=True)
        kwargs: dict[str, Any] = {"task_description": self.placement.describe(
            env=env, cwd=str(cwd) if cwd is not None else None, timeout_s=timeout_s)}
        if self.workflow_id:
            kwargs["workflow_id"] = self.workflow_id

        submitted = time.monotonic()
        if self.slots is not None:
            await self.slots.acquire()          # waiting for a slot is queueing too
        try:
            if self.cancelled:
                raise asyncio.CancelledError(f"{self.node}: its Stage was cancelled")
            fut = task(**kwargs)
            self.inflight.add(fut)
            fut.add_done_callback(self.inflight.discard)
            started: float | None = None
            try:
                while not fut.done():
                    if started is None and getattr(fut, "state", "") == "RUNNING":
                        started = time.monotonic()
                    await asyncio.wait({fut}, timeout=_POLL_S)
            except asyncio.CancelledError:
                fut.cancel()
                raise
        finally:
            if self.slots is not None:
                self.slots.release()
        finished = time.monotonic()
        started = started if started is not None else submitted
        self.commands += 1
        self.queued_s += started - submitted
        self.ran_s += finished - started

        if fut.cancelled():
            if (self.placement.dragon and timeout_s and not self.cancelled
                    and finished - started >= timeout_s):
                # Dragon reports its own timeout as a cancellation. Nobody cancelled this
                # Stage, and the command ran its full walltime: say what happened.
                raise SubprocessError(cmd, -1, "", f"timed out after {timeout_s}s "
                                                   "(Dragon's task timeout)")
            raise asyncio.CancelledError
        desc = getattr(fut, "task", None) or {}
        stdout, stderr = _read(desc.get("stdout")), _read(desc.get("stderr"))
        if fut.exception() is None:
            return stdout, stderr
        try:
            code = int(desc.get("exit_code"))
        except (TypeError, ValueError):
            code = -1
        if timeout_s and code in _TIMED_OUT:
            raise SubprocessError(
                cmd, -1, stdout, f"timed out after {timeout_s}s"
                + (f"\n--- partial stderr before the kill ---\n{stderr}" if stderr else ""))
        raise SubprocessError(cmd, code, stdout, stderr or str(fut.exception()))
