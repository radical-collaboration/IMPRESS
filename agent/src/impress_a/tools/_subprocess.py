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
import shlex


class SubprocessError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd, self.returncode, self.stdout, self.stderr = cmd, returncode, stdout, stderr
        super().__init__(
            f"command failed ({returncode}): {shlex.join(cmd)}\n--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}")


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
        if isinstance(v, dict) and port in v.get("outputs", {}):
            return v["outputs"][port]
    return None
