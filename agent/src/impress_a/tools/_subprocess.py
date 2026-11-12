"""Shared subprocess helper for real (non-mock) task agents.

Every real tool in this repo runs as an external CLI/container invocation. This is the
one place that owns "how do we shell out and check the result" so the four real-toolkit
agent modules do not each reinvent it.

Deliberately NOT imported at module scope by anything under `toolkits/` discovery -
importing this module has no heavy dependency, so it is safe for `Registry.load()` to
resolve `entry:` classes that import it even when none of the real science stack (boltz,
pyrosetta, the LigandMPNN/RFD3 checkoutss) is installed.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from contextvars import ContextVar
from pathlib import Path
from typing import Any

#: The launcher a node's commands go through while that node runs on the engine. Set by
#: `exec/dispatch.node_task` around one adapter call and nowhere else; `None` means "not on
#: the engine" - `impress-a preflight`, a gate fixture, a test calling an adapter directly -
#: and there `run_cmd` runs the command itself, as it always did.
#:
#: A context variable rather than a `TaskRequest` field so that no adapter can forget to pass
#: it: an adapter that did would run its binary on the campaign's own host, unplaced, and
#: nothing would say so. Every real adapter already calls `run_cmd`; none had to change.
LAUNCHER: ContextVar[Any] = ContextVar("impress_a_launcher", default=None)


class SubprocessError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd, self.returncode, self.stdout, self.stderr = cmd, returncode, stdout, stderr
        super().__init__(
            f"command failed ({returncode}): {shlex.join(cmd)}\n--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}")

    def __reduce__(self):
        # This crosses a process boundary: Dragon pickles a worker's exception into its
        # results DDict. Default unpickling calls cls(*self.args), which is (message,) here
        # and fails. rhapsody's monitor loop then drops the completion, and the run hangs
        # with no FAILED ever delivered (job 22536706).
        return (type(self), (self.cmd, self.returncode, self.stdout, self.stderr))


async def run_cmd(cmd: list[str], cwd=None, env=None,
                  timeout_s: float | None = None) -> tuple[str, str]:
    """Run `cmd`, wait for it, return (stdout, stderr). Raises SubprocessError on nonzero exit.

    Inside a node on the engine, the command is an engine task on the `compute` route,
    placed by the node's `Placement` (see `exec/launch.py`). Outside one, it runs here.
    """
    launcher = LAUNCHER.get()
    if launcher is not None:
        return await launcher.run(cmd, cwd=cwd, env=env, timeout_s=timeout_s)
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    # Accumulate as output arrives rather than calling communicate(). On a timeout
    # communicate() is cancelled and whatever it had read is lost - so a timed-out task
    # used to arrive carrying nothing but "timed out after Ns", which is the same shape
    # as a hang and names no cause. Job 22675512's packmin died exactly that way: a 300s
    # timeout, an empty work dir, and no way to tell 290s-of-import from 290s-of-work
    # without spending another allocation. Draining the readers after the kill does not
    # work either; by then the buffers are gone. Holding the chunks ourselves does.
    chunks: dict[str, list[bytes]] = {"out": [], "err": []}

    async def _accumulate(stream, key: str) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                return
            chunks[key].append(chunk)

    readers = [asyncio.create_task(_accumulate(proc.stdout, "out")),
               asyncio.create_task(_accumulate(proc.stderr, "err"))]

    def _decode(key: str) -> str:
        return b"".join(chunks[key]).decode(errors="replace")

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        await asyncio.gather(*readers)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        for r in readers:
            r.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        partial_err = _decode("err")
        # `from None`: the TimeoutError carries no information the message does not already
        # state, and chaining it puts an asyncio frame at the top of a traceback whose
        # interesting part is the child's own partial stderr, below.
        raise SubprocessError(
            cmd, -1, _decode("out"),
            f"timed out after {timeout_s}s"
            + (f"\n--- partial stderr before the kill ---\n{partial_err}"
               if partial_err else "")) from None
    except BaseException:
        # Including cancellation of the caller: do not leak the child or the readers.
        for r in readers:
            r.cancel()
        if proc.returncode is None:
            proc.kill()
        raise

    stdout, stderr = _decode("out"), _decode("err")
    if proc.returncode != 0:
        raise SubprocessError(cmd, proc.returncode, stdout, stderr)
    return stdout, stderr


def input_path(req: Any, port: str):
    """The file an upstream wired to this adapter's own declared input `port`.

    Replaces `first_dep_output`, which **scanned**: the dispatcher used to key inputs
    `dep0..depN` positionally, so an adapter had no way to ask which dependency it was handed
    and took the first whose `outputs` happened to contain the name it wanted. With one
    upstream that is always right; with two it is a coin toss that type-checks at composition.
    It also meant an adapter asked for an upstream *output* port name while declaring an
    *input* port name, and the two coincided here by luck - `ligandmpnn_design` consumes
    `backbone` and rfd3 emits `backbone`, so nothing noticed.

    `TaskRequest.input_ref` resolves by the declared port, using the wiring the composer
    computed and gate 1 type-checked. What this adds is the last step an adapter actually
    wants: the thing to open. `ArtifactRef.located` is a property, so it is unavailable once
    the handle has crossed a process boundary as plain data - which is why the dict form is
    handled rather than assumed away.
    """
    ref = req.input_ref(port)
    if ref is None:
        return None
    if isinstance(ref, dict):
        return ref.get("path") if ref.get("path") is not None else ref.get("value")
    return getattr(ref, "located", ref)


def child_env(req: Any, base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a real tool's child process should run with: a whole one.

    Whole because the env passed to `create_subprocess_exec` REPLACES the child's rather than
    extending it, so passing only additions would strip PATH, MPNN_DIR and BOLTZ_CACHE.

    It carries no GPU pinning and no thread caps any more. Those are the node's `Placement`,
    rendered per backend by `exec/resources` where the backend is known: the concurrent
    backend gets them in the env, Dragon gets a `Policy` - and an adapter that set
    `CUDA_VISIBLE_DEVICES` itself under Dragon would name a device Dragon never gave it.
    `req` is kept for adapters that call it with one.
    """
    del req
    return dict(base if base is not None else os.environ)


def workdir_for(req: Any, prefix: str) -> Path:
    """A per-task directory for a real tool to work in.

    Defaults to the CURRENT WORKING DIRECTORY, because that is where the launcher has
    already put us and the launcher is what knows the machine: `delta_gpu_run.sh` cds
    into `$WORK_DIR/impress_a_runs/<jobid>_<campaign>` - a shared filesystem, scoped
    per job so concurrent campaigns cannot collide.

    The adapters previously called `tempfile.mkdtemp()`, which put every artifact in the
    system temp dir - NODE-LOCAL. Under Dragon multi-node a downstream task can be
    scheduled on a different node from the one that produced its input, where that path
    simply does not exist; the failure then surfaces from inside a science tool as a
    missing file rather than as anything the campaign could reason about.

    Artifacts are not cleaned up: they are the campaign's results and its provenance.
    """
    root = Path(getattr(req, "workdir", None) or Path.cwd())
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(getattr(req, "node_id", None) or "task"))
    work = root / "work" / f"{prefix}_{name}"
    work.mkdir(parents=True, exist_ok=True)
    return work
