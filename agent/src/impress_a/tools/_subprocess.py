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
import re
import shlex
from pathlib import Path
from typing import Any


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


async def run_cmd(cmd: list[str], cwd=None, env=None, timeout_s: float | None = None) -> tuple[str, str]:
    """Run `cmd`, wait for it, return (stdout, stderr). Raises SubprocessError on nonzero exit."""
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
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        for r in readers:
            r.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        partial_err = _decode("err")
        raise SubprocessError(
            cmd, -1, _decode("out"),
            f"timed out after {timeout_s}s"
            + (f"\n--- partial stderr before the kill ---\n{partial_err}"
               if partial_err else ""))
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


def first_dep_output(inputs: dict, port: str):
    """Task requests carry deps positionally (dep0, dep1, ...), not by port name -
    dispatch.py wires edges by TYPE at compose time, not by name at run time. Every real
    agent here has exactly one upstream dep, so scan for the first dict that has `port`
    under its `outputs`."""
    for v in inputs.values():
        if isinstance(v, dict) and port in (v.get("outputs") or {}):
            produced = v["outputs"][port]
            # Upstream now hands over a typed handle rather than a bare string; what an
            # adapter wants is the thing to open.
            return getattr(produced, "located", produced)
    return None


def workdir_for(req: Any, prefix: str) -> Path:
    """A per-task directory for a real tool to work in.

    Defaults to the CURRENT WORKING DIRECTORY, because that is where the launcher has
    already put us and the launcher is what knows the machine: `delta_gpu_run.sh` cds
    into `$WORK_DIR/impress_a_runs/$SLURM_JOB_ID` - a shared filesystem, scoped per
    job so concurrent campaigns cannot collide. It is also where asyncflow already
    writes its own session files.

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
