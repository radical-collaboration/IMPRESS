# dragon: a process that leads its own process group is never reaped, and its task never completes

**Component:** dragonhpc 0.15.0 (`src/dragon/localservices/server.py`, checked at `fae6165`),
reached through rhapsody-py 0.7.0's DragonExecutionBackend · **Severity:** silent hang; the
task holds its slot until the job's walltime · **Status:** diagnosed, not reported upstream
**Evidence:** IMPRESS job 23814643 (Delta, gpuA40x4-interactive, 2026-11-11). Two executable
tasks, each `timeout --kill-after=10 900 apptainer exec ... rfd3 design ...`, wrote their
outputs at 16:40:21. Their `timeout` processes were then `Z [timeout] <defunct>`, parented by
the `dragon` launcher, 7+ minutes later. asyncflow never received DONE for either.

## What we saw

Any executable whose top-level process calls `setpgid(0, 0)` (coreutils `timeout` does, unless
given `--foreground`; so do `setsid` and many daemonising tools) exits normally, stays a zombie,
and its Dragon task is never reported complete.

## Cause

`LocalServer.watch_death` reaps with `os.waitpid(0, os.WNOHANG)` (`server.py:2604`). A pid of 0
waits only for children **in the caller's process group**. A child that moved itself to its own
group is never matched, never reaped, and never popped from `self.apt`, so its completion is
never sent.

## Fix

Reap any child: `os.waitpid(-1, os.WNOHANG)`, keeping the `self.apt` lookup to ignore pids
local services did not start. Or track each started process by pid (`os.waitpid(pid, WNOHANG)`
per entry, or a pidfd on Linux), so that a group change cannot hide it.

## Impact on us

IMPRESS-A wrapped every tool command in coreutils `timeout` so a command could not outlive
its walltime on backends whose cancel kills nothing (see
[rhapsody-concurrent-cancel-leaves-process-running](rhapsody-concurrent-cancel-leaves-process-running.md)).
On Dragon that hung the whole campaign at its first stage. Local fix: no wrapper under Dragon;
the walltime is Dragon's own task `timeout` (`agent/src/impress_a/exec/launch.py`). Any tool
that leads its own process group would still hang the same way.
