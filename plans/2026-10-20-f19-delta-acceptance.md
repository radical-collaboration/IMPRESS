# F19 — declared adaptive tasks, acceptance run on Delta

**Status:** `23062773` (2026-10-20, gpub001, `TIMEOUT` 1:00:05 as planned): routing, labels, telemetry and storage **pass**; throughput **unscored** after backend faults killed 11 of 32 pipelines. See [Result](#result). Rerun `23065238` submitted · **Branch:** `framework-defaults-pr1` at `22a1f82` · **Blocks:** pushing and merging PR 1 · **Items:** F19

## Why

F18 passed on `22927576`, launched from `9f91e46`. Since then `22a1f82` (F19) changes the
code path every adaptive call takes
([pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f19)):

- the smb runner declares `flow.function_task(backend="local")(adaptive_decision)`
  (`run_small_molecule_binding.py:486`) and passes the task as `adaptive_fn`;
- `ImpressManager._invoke_adaptive_fn` is one `await` with
  `workflow_id=f"{pipeline.name}:adaptive"`; `adaptive_backend=`, `adaptive_offload`,
  `_check_adaptive_backend` and the thread fallback are deleted;
- `submit_new_pipelines()` raises `TypeError` for an `adaptive_fn` that is not a task;
- smb's callback is `async def` again (asyncflow rejects a sync body).

Offline evidence: 125/125 tests, and a byte-identical 496-event smb mock sequence against
`4cd860b`. Offline cannot show that the declared task lands on Dragon's sibling `local` pool
with its label, nor that occupancy and throughput hold at 32 pipelines.

Out of scope: F7's other runners (`protein_binding`, `discontinuous_scaffolds`,
`run_nonadaptive`). This run exercises `run_small_molecule_binding.py` only, so F7 stays
"awaiting a Delta run".

## Run

- Shape: 1 node, 1 h, `gpuA40x4-interactive`, 32 pipelines (8 per GPU), account
  `<allocation A>`. Matches `22927576`, `22767771` and `22718758`.
- From a clean checkout of `22a1f82`. No failure injection.
- `IMPRESS_N_PIPELINES=32 sbatch --partition=gpuA40x4-interactive --time=01:00:00 --account=<allocation A> --job-name=impress_f19 delta_gpu_run.sh`,
  from `examples/small_molecule_binding/`.
- Pre-flight: clean `git status`; `p1_in`…`p32_in` each hold `ALR.params`, `ALR.smiles` and
  `ALR_binder_design.json` (smb 9); project inodes 1.43M of 2.55M (smb 18); no other job
  writing under `logs/`.

## Pass criteria

Scored with the F1/F18 method: per node-h counted from minute 10.

| Check | Pass | Confirms |
|---|---|---|
| Startup | runner reaches `Active: 32 pipelines`; no `TypeError` from `submit_new_pipelines()` | the new gate accepts a declared task on a real engine |
| Adaptive routing | every adaptive TaskQueued has `backend=local` and label `p<N>:adaptive`; adaptive share ≤ 0.31 % of wall clock (F18) | F19's declared path, and its fix for the pass-through label gap |
| Telemetry handle | `impress.LocalStage` count 1:1 with each tool stage's completions | F17 injection unchanged |
| Labels | 100 % of tasks labelled `p<N>:<stage>` or `p<N>:adaptive` | PR 1 labels unchanged |
| Failures | 0 `TaskFailed`. An smb 16 recurrence counts against smb 16/22, not F19 | — |
| Throughput | rfd3 and boltz per node-h over min 10–60 within 10 % of 337.1 / 108.0 (`22927576`). Also record silences > 15 s between completions | no regression from the `async def` callback |
| Storage | ~31 files per tool task (run dir plus session dir) | unchanged from F18 |

## After

- Add a Result section with the numbers against each criterion.
- Set F19 to "confirmed on `<job>`"; F14's row can then be deleted with F19's when PR 1 merges.
- Add a row to the smb CLAUDE.md revision table.
- If it passes, push and merge PR 1, then delete the F1, F14, F17, F18 and F19 rows.

<a id="result"></a>
## Result — job `23062773` (scored 2026-10-20)

gpub001, 17:12:47 → 18:12:52, `TIMEOUT` 1:00:05 at the limit as planned. Scored with a script
that reproduces `22927576`'s published figures exactly (337.1 / 108.0 / 1043.8 per node-h,
0.31 % adaptive share, the same two stalls). Sources: `logs/23062773/telemetry/*.jsonl`,
`logs/23062773/nvsmi.csv`, `impress_23062773.out`.

**Verdict: F19's own criteria pass; throughput is unscored because 11 of 32 pipelines were killed
by backend faults.** A rerun was submitted for throughput (see [Rerun](#rerun)).

| Check | `23062773` | Reference `22927576` | Verdict |
|---|---|---|---|
| Startup | all 32 pipelines started; no `TypeError` from `submit_new_pipelines()` | — | pass |
| Adaptive routing | 1604 of 1604 adaptive TaskQueued on `local`, all labelled `p<N>:adaptive`; 0.28 % of wall clock, p50 0.002 s, p99 0.055 s, max 0.482 s | 0.31 %, p99 0.041 s | pass |
| Telemetry handle | 1604 `impress.LocalStage` = 1604 tool completions feeding an analysis (rfd3 247, mpnn 779, packmin 240, fastrelax 181, filter_shape 82, boltz 75) | 1:1 | pass |
| Labels | 3239 of 3239 tasks labelled | 4118 of 4118 | pass |
| Failures | **11 `TaskFailed`, all tool tasks on `compute`, none adaptive** (below) | 0 | fail on the letter; none attributable to F19 |
| Throughput, per node-h, min 10–60 | rfd3 244.9, boltz 79.6, mpnn 837.2 | 337.1 / 108.0 / 1043.8 | **not scoreable**: only 21 pipelines alive after min 25 |
| Throughput, per live pipeline-h, min 10–60 | rfd3 10.32, boltz 3.35, mpnn 35.27 (19.7 live pipeline-h) | 10.54 / 3.37 / 32.62 (26.7) | within noise (−2 % / −1 % / +8 %) |
| Completion stalls > 15 s after min 10 | 3 (20 s at min 24.9, 16 s, 22 s) | 2 (24 s, 17 s) | no large stall |
| Storage | 46,997 run + 3,278 session files for 1635 tool tasks = **30.7/task**; 2.5 GB | 31.0 | pass |

The telemetry's TaskCreated/TaskStarted/TaskCompleted events name `compute` for the adaptive
tasks while TaskQueued/TaskSubmitted name `local`. `22927576` shows the identical split (2043 of
2043), so this is asyncflow's lifecycle-event mislabel (F13), not a routing change.

### The 11 failures

Two kinds, both in the backend's task-completion path, both before any adaptive call for the
failed stage:

- **Two isolated false failures (smb 16 shape), min 9.1 and 10.4.** The tool succeeded and the
  backend still reported `TaskFailed` with no reason; the pipeline then died with
  `'NoneType' object is not subscriptable` (smb 15).
  - `p25:mpnn` had written all 40 backbones, packed models and `seqs/binder.fa` by 17:21:40, with
    empty stderr; the failure arrived 105 s later.
  - `p15:boltz` was reported failed at 17:22:10 *while still running*: it wrote
    `boltz_input_model_0.pdb` and its confidence files at 17:22:39. This ended the run's longest
    silence (38.6 s, just before the window opened).
  - First occurrences on mpnn and boltz; earlier smb 16 events were all rfd3.
- **One burst of the Dragon `ProcessGroup manager is not in state State.DEAD` fault, min
  24.9–25.5,** killing 9 pipelines (7 fastrelax, 1 boltz, 1 mpnn; two of those surfaced as the
  `NoneType` error instead). This is the fault characterised as smb 26 on branch
  `smb-nonadaptive-benchmark` (not yet on this branch's smb BACKLOG), now its fifth run.

Other measurements: seff CPU 51.9 %, memory 73.1 % of 240 GB.

**F19 is confirmed on Dragon for routing, labels and telemetry.** Throughput per live pipeline
matches F18, but the node-h criterion needs a run that keeps its pipelines.

<a id="rerun"></a>
## Rerun

Job `23065238` submitted 2026-10-20, identical shape, from `22a1f82` (code unchanged; only plans
differ), to score the throughput criterion.
