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
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SubprocessError(cmd, -1, "", f"timed out after {timeout_s}s")
    stdout, stderr = out.decode(errors="replace"), err.decode(errors="replace")
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
