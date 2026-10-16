# rhapsody Dragon backend: completions held back for up to 2.5 min, all pipelines idle

**Component:** rhapsody 0.5.0 `DragonExecutionBackend` (`rhapsody/backends/execution/dragon.py`), on dragonhpc 0.14.1 `dragon.workflows.batch`
**Severity:** medium (cost about 2.5 % of `22767771`'s throughput window in one stall, and synchronised every pipeline afterwards)
**Status:** diagnosed from telemetry, cause not yet confirmed in-process, not reported upstream
**Evidence:** jobs `22767771` (1 node, 32 pipelines, framework PR 1) and `22714866` (1 node, 16 pipelines, before PR 1); `22718758` as the control. Telemetry: `logs/<job>/telemetry/*.telemetry.jsonl`

## What we saw

On `22767771`, from 23:57:26 to 23:58:43 **no task completion was delivered for 76 s**. Then 26
completions arrived within 30 ms (`TaskCompleted` for p1–p31, all stamped 23:58:43.09–.20). The
tasks had really finished: node CPU fell 65 % → 36 % (ResourceUpdate) and GPUs 0, 1 and 3 dropped
to 0 % (`nvsmi.csv`) during the window. Every pipeline was waiting on the engine, so the node idled.

After the stall, the 26 pipelines restarted in lockstep. For the next 13 minutes, completions
kept arriving in batches of short CPU tasks with identical durations: 12 mpnn/packmin tasks at
67 s, 11 at 90 s, 8 at 111 s and 7 at 224 s, against a 15.6 s mpnn median.

Silences of more than 15 s between executable completions, counted after minute 10:

| Job | Silences > 15 s | Total | Longest | rfd3 `TaskFailed` with `error=unknown` (smb 16) |
|---|---|---|---|---|
| `22718758` (control) | 3 | 57 s | 20 s | none |
| `22767771` | 8 | 198 s | **76 s** (min 28.4) | p24 at 23:59:13, 1.8 min into the stall |
| `22714866` | 12 | — | **152 s** (min 3.9) | p7, p15 at 21:40:32–33, 1 min before it |

Both runs with the largest stalls also had smb 16: an rfd3 task reported `TaskFailed` after it
had written all of its outputs. In `22767771` the stderr tail of p24's rfd3 (`task.001694.stderr`)
shows 4 models written at 23:58:38 and no error; the failure arrived 35 s later.

## Cause (suspected)

One thread delivers every completion. `_monitor_loop` (`dragon.py:185`) polls
`self.batch.poll(timeout=0.05)` (`:196`), drains every finished tuid, then for each one calls
`batch_task.get(block=True)` (`:236`, "Block until the result is fully committed to the DDict").
Only after the whole sweep does it hand the batch to the event loop
(`call_soon_threadsafe(self._deliver_batch, …)`, `:278`).

So a single task whose result commit is slow blocks:
- that task's own delivery;
- every other completion in the same sweep;
- all later polls.

That fits the pattern: a long silence, then many completions with the same timestamp. A stuck or
malformed commit for the smb 16 rfd3 task fits as the trigger, with the
`'NoneType' object is not subscriptable` that kills the pipeline (smb 15) as its result.

Not yet confirmed. Telemetry shows *when* completions were delivered, not where the thread was
blocked.

## Fix

- Upstream: bound the wait (`get(timeout=…)`, then requeue the tuid as `_pending_tuids` already
  does for unregistered ones), or resolve each tuid independently so one slow commit cannot hold
  back the sweep.
- Diagnosis first: on the next run that shows a silence over 30 s, take a `py-spy dump` of the
  runner process to see whether the monitor thread is inside `batch_task.get`.

## Impact on us

- `22767771`: the stall and the lockstep that followed it took full-window rfd3 throughput to
  264.3/node-h, against 315.5 on `22718758`. Over minutes 10–28, before the stall, the same run was
  at 10.33 rfd3/pipeline-h against 9.78. See [F1](../../../../plans/2026-10-08-pr1-delta-acceptance.md#result).
- No local workaround. `capture_stdio` does not obviously matter: `22714866` (before PR 1, with
  capture on for rfd3/boltz only) stalled longer.
