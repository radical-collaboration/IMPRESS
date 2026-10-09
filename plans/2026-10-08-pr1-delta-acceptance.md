# F1 — PR 1 acceptance run on Delta

**Status:** open · **Branch:** `framework-defaults-pr1` (`7327c84`) · **Blocks:** merging PR 1

## Why

PR 1 changes how every task in every example is launched and reported:
- stdio capture is on by default;
- each executable call gets a `workflow_id` and a done-callback;
- local stages are wrapped for telemetry;
- adaptive functions are routed through the manager's offload.

Offline evidence is strong but has gaps:
- 120 unit and integration tests pass, including one on a real `ConcurrentExecutionBackend`.
- The smb mock run gives the identical 124-stage sequence and identical adaptive decisions before and after.
- **None of it ran on Dragon.**

Three parts of PR 1 depend on Dragon behaviour that the offline tests did not exercise:
- the stderr path is rebuilt from private engine attributes (`flow._backends`, `backend._work_dir`, `fut.task['uid']`);
- Dragon raises `SystemExit(code)` rather than `RuntimeError(path)`;
- smb's `rfd3` and `boltz` used to be the only captured tasks. Now all seven tool stages write `.stdout`/`.stderr` into the session dir, roughly 2 more files per task, which matters for the inode quota (smb 18).

## Run

- Shape: 1 node, 1 hour, `gpuA40x4-interactive`, 32 pipelines (8 per GPU), launched from the branch checkout. This matches reference job `22718758`.
- Inject one failure: a pipeline whose `p*_in` dir lacks `ALR.smiles`, so its `boltz` stage fails. That exercises the Dragon failure path.

## Pass criteria

| Check | Pass |
|---|---|
| Throughput | rfd3 per node-hour within noise of `22718758` (315.5); boltz within noise of 94.3 |
| Failures | 0 `TaskFailed` apart from the injected one |
| Labels | every task event in the telemetry JSONL carries `asyncflow.workflow_id` = `p<N>:<stage>` or `p<N>:adaptive`; no `bash` labels |
| Local stages | exactly one `impress.LocalStage` per `analysis_*` call; no duplicates |
| Adaptive | adaptive tasks show `target_backend=local` on TaskQueued; adaptive share of wall clock stays near `22701168`'s 0.96 % |
| Failure report | the injected failure's log line and exception note contain the end of its stderr. If Dragon's `SystemExit` path finds no stderr file, record that and fix `impress.utils.stdio._stderr_path` before merge |
| Storage | file count of the run dir plus the session dir, per task, compared with `22718758`; record the increase |

## After

Record the job ID and results here and in the smb CLAUDE.md revision row added by PR 1 (currently "Not yet run on Delta"). Then close F1.
