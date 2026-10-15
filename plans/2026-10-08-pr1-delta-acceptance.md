# F1 — PR 1 acceptance run on Delta

**Status:** **passed** on job `22767771` (`<allocation A>`, `gpuA40x4-interactive`, 1 node, 1 h, 32 pipelines, from `1372251`; ran 2026-10-08 23:28:51 → 2026-10-09 00:28:56, `TIMEOUT` at the 1 h limit as planned). Throughput passed with attribution, decided 2026-10-15: see [Result](#result) · **Branch:** `framework-defaults-pr1` (`7327c84`) · **Blocks:** merging PR 1

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
- Inject one failure by hiding `p32_in/ALR.params` (renamed to `ALR.params.f1-hold`), so p32's first `packmin` fails inside the Rosetta tool process on Dragon.
  - Hiding `ALR.smiles`, as first planned, would not test the backend: the `boltz` coroutine reads it in-process and raises before anything is dispatched.
  - Only the Rosetta tools read `ALR.params`, as `-extra_res_fa`. Its one in-process reader is the guided-rfd3 path, which runs only after a passing fold.
  - Dependent job `22767773` (`afterany`) renames the file back when the run ends. Check `logs/f1_restore_22767773.out` says `restored` before the next run that uses p32.
  - Expected side effect: per smb 15, p32 dies at that failure. Compare throughput per pipeline over the 31 healthy ones as well as per node.

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

<a id="result"></a>
## Result — job `22767771` (scored 2026-10-15)

The run was 1 node (gpub085), 23:28:51 → 00:28:56, `TIMEOUT` at the limit as planned. Restore job
`22767773` finished `COMPLETED`, and `logs/f1_restore_22767773.out` says `restored`.

Scoring used the gpu-saturation method on both this run and `22718758`'s archived telemetry, the
latter from `<hdd work dir>/impress_run_archive/22718758_nvme.tar.gz`. The method reproduces that
doc's figures exactly (315.5 / 94.3 / 1073). Sources: `logs/22767771/telemetry/*.jsonl`,
`logs/22767771/nvsmi.csv`, `impress_22767771.out`.

| Check | `22767771` | Reference | Verdict |
|---|---|---|---|
| Throughput, full window (min 10–60), per node-h | rfd3 **264.3** (−16 %), boltz **83.3** (−12 %), mpnn 932.8 (−13 %) | `22718758`: 315.5 / 94.3 / 1073 | below the bar; **passed with attribution** (below) |
| Throughput, min 10–28, per pipeline-h, over the 30 pipelines both runs share | rfd3 10.33, boltz 2.78, mpnn 34.89 | 9.78 / 2.56 / 33.78 | pass (+6 % / +9 % / +3 %) |
| Failures | 2 `TaskFailed`: `p32:packmin` (injected) and `p24:rfd3` (smb 16, below) | 0 | pass: the second failure predates PR 1 |
| Labels | 3549 of 3549 tasks carry `asyncflow.workflow_id` = `p<N>:<stage>` or `p<N>:adaptive`; none unlabelled. The separate `executable` attribute still reads `bash` (F13) | `22718758`: 2059 adaptive tasks unlabelled | pass |
| Local stages | 1759 `impress.LocalStage`, all `completed`, 0 duplicates. One per analysis call: backbone 264 = rfd3 completions, sequence 871 = mpnn, packmin 259, fastrelax 193, interface 96, fold 76 = boltz | 1:1 | pass |
| Adaptive | 1759 of 1759 TaskQueued on `local`; 0.47 % of wall clock, p50 0.003 s, p99 0.140 s, max 0.418 s | `22701168`: 0.96 %, p99 0.071 s | pass |
| Failure report | p32's log line has the Rosetta stderr tail (`Cannot find file … p32_in/ALR.params`). p24's has its rfd3 stderr tail (`asyncflow.session.596bbac4/task.001694.stderr`). `_stderr_path` found both files on Dragon | present | pass; no fix needed |
| Storage | 51,409 run-dir + 3,590 session files for 1790 tool tasks = **30.7 files/task** | `22718758`: 59,432 + 4,216 for 2090 = 30.4 | pass: +1 %, not the +2 files/task expected |

### Throughput: why it is below the bar, and why that is not PR 1

**The IMPRESS side is unchanged or better.**
- Median gap between one task's completion and the pipeline's next submission: 0.27 s (p99 0.59 s),
  against 0.24 s (p99 0.51 s).
- Pipelines were inside a tool task 98 % of the time.
- The stagger was identical: 4 pipelines per minute, 0–7 min.
- Local stages took 0.27 % of wall clock, against 0.28 %.

**What happened instead: completion delivery from the Dragon backend stalled.**
- From 23:57:26 to 23:58:43 (min 28.4), no completion arrived for **76 s**. Then 26 arrived within
  30 ms.
- The tools had finished: node CPU fell 65 → 36 %, and GPUs 0, 1 and 3 went to 0 %.
- After the stall the pipelines restarted in lockstep. Until about min 42, short CPU tasks kept
  completing in batches with identical durations, e.g. 12 mpnn/packmin tasks at 67 s against a
  15.6 s median.
- After minute 10 there were 8 silences over 15 s (198 s total). `22718758` had 3 (57 s, longest 20 s).
- Per pipeline-h, rfd3 ran 10.33 before the stall, 6.57 in min 28–42 and 8.69 in min 42–60. The
  reference ran 9.78, 8.57 and 11.00 over the same windows.

**The stall sits next to the smb 16 failure, as it did before PR 1.**
- p24's rfd3 wrote all 4 models at 23:58:38 with nothing in stderr. It was reported `TaskFailed`
  (`error=unknown`) at 23:59:13, and the pipeline then died with `'NoneType' object is not
  subscriptable` (smb 15).
- `22714866`, before PR 1, had the same pair: p7/p15 rfd3 failures at 21:40:32–33, then a **152 s**
  stall a minute later.
- Runs without smb 16 never stalled longer than 31 s.
- Suspected cause: rhapsody's single monitor thread blocks in `batch_task.get(block=True)`. See
  [upstream/rhapsody-dragon-completion-stall](../examples/small_molecule_binding/plans/upstream/rhapsody-dragon-completion-stall.md).

**Lost pipelines.** p32 died at min 9.7, before the counting window opened, so it cost 1/32 of the
node rate. p24 died at min 30.2.

**Decision (2026-10-15): F1 passes.**
- No criterion fails because of PR 1.
- The full-window throughput gap is attributed to the Dragon delivery stall, smb 15/16 and the
  injected failure.
- Caveat: this is one run per side. If a later run at this shape is more than 10 % below
  `22718758` *without* a stall or an smb 16 event, reopen the question.

**Surprises.**
- Storage did not grow. `22718758`'s session dir already held a `.stdout`/`.stderr` pair for every
  task: 2108 pairs, 493 files non-empty. So "only rfd3 and boltz were captured" in [Why](#why) was
  wrong about the files on disk.
- p32 failed as `RuntimeError('1')`, not the `SystemExit(code)` this doc expected. The stderr tail
  was found either way.
