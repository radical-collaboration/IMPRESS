# Pass-through routing under F19 (smb 23 re-run)

**Status:** **passed** on `23074256` (2026-10-20, gpub002, from `0ad0583`): 1736/1736 callbacks on `local` at 0.22 %; rfd3 271.1 / boltz 262.7 per node-h and 55.5 / 20.4 passing / high-quality folds per GPU-h, all within 10 % of `22967619`. See [Result](#result) · **Branch:** `smb-benchmark-f19` (merge `d571de2` of
`smb-nonadaptive-benchmark` onto `framework-defaults-pr1`) · **Items:** smb 23; framework F7, F19

## Why

The pass-through baseline (`--nonadaptive`, smb 23) was measured on `22967619`, from code that
predates framework F19. F19 makes every `adaptive_fn` a declared asyncflow task and rejects
anything else with `TypeError`. The merge resolved that by:

- choosing the policy first and declaring it with `flow.function_task(backend="local")(policy)`,
  so `--nonadaptive` swaps only the body;
- making `nonadaptive_decision` `async def`, because asyncflow rejects a sync body.

F19 confirmed that path for `adaptive_decision` on `23062773` / `23065238`
([f19-delta-acceptance](../../../plans/2026-10-20-f19-delta-acceptance.md)). This run confirms it
for the pass-through body. It also covers the part of framework F7 that `run_nonadaptive.py`
used to carry, now that the file is gone.

Offline (2026-10-20): pytest 125/125, ruff clean. Mock run (`run_test_small_molecule_binding.py`)
in each mode, 0 errors:
- adaptive: 124 stages / 136 decisions, identical in sequence to `framework-defaults-pr1`'s head;
- `--nonadaptive`: 180 stages / 180 decisions, linear rfd3 → mpnn/packmin ×3 → fastrelax →
  filter_shape → boltz, no retries or guided rfd3;
- `--nonadaptive --selection first`: the same routing, with all 60 selection points logging
  `mode=first`.

## Run

- Shape matches `22967619`: 1 node, 1 h, `gpuA40x4-interactive`, 32 pipelines (8 per GPU),
  account `<allocation A>`, default `max_tasks`, selection `best`.
- `IMPRESS_NONADAPTIVE=1 IMPRESS_N_PIPELINES=32 sbatch --partition=gpuA40x4-interactive --time=01:00:00 --account=<allocation A> --job-name=impress_nonadaptive_f19 delta_gpu_run.sh`
- Pre-flight:
  - clean `git status`;
  - `p1_in`…`p32_in` complete (smb 9);
  - inode and block headroom (smb 18);
  - no other job writing under `logs/`.

## Pass criteria

Scored with `score_run.py` (beside `RUNS.md` in the run archive), which reproduces `22967619`'s
published figures. Per node-h from minute 10.

| Check | Pass | Reference `22967619` |
|---|---|---|
| Startup | `[POLICY] nonadaptive_decision`; no `TypeError` from `submit_new_pipelines()` | same `[POLICY]` line |
| Callback routing | every callback TaskQueued on `local`, labelled `p<N>:adaptive`; share ≤ 0.5 % of wall clock (the F19 bar) | 0.28 % (1774) |
| Failures | 0 `TaskFailed`. smb 16 / smb 26 events are recorded against those items; if they cost more than 3 pipelines, throughput is unscored and the run is repeated | 0 |
| Throughput | rfd3 / boltz per node-h within 10 % | 262.7 / 265.1 |
| Yield | passing and high-quality folds per GPU-h within 10 % | 51.0 / 22.2 |
| Storage | ~30 files per tool task | — |

## After

- Add a Result section.
- Update smb 23 and framework F7.
- Add the job to `RUNS.md` once it is archived.

<a id="result"></a>
## Result — job `23074256` (scored 2026-10-21)

gpub002, 23:47:43 → 00:48:10, `TIMEOUT` 1:00:27 as planned. Scored with `score_run.py`, which
reproduced `22967619` exactly before the run (262.7 / 265.1 per node-h, 50.97 / 22.19 per GPU-h,
0.28 %). Sources: `logs/23074256/telemetry/*.jsonl`, `nvsmi.csv`, `hostmem.csv`,
`impress_23074256.out`.

**Verdict: pass.** The pass-through body runs as a declared task on `local` under F19, with
throughput and yield within 10 % of the pre-F19 baseline.

| Check | `23074256` | Reference `22967619` | Verdict |
|---|---|---|---|
| Startup | `[POLICY] nonadaptive_decision, selection=best, max_tasks=300`; no `TypeError` | same policy | pass |
| Callback routing | 1736 of 1736 TaskQueued on `local`, all `p<N>:adaptive`; 0.22 % of wall clock | 0.28 % (1774) | pass |
| Labels / `LocalStage` | 3504 of 3504 labelled; 1736 `LocalStage` = 1736 callbacks | — | pass |
| Failures | 1: `p25:boltz` at 00:45 (min 57), Dragon `ProcessGroup manager is not in state State.DEAD` (smb 26), a single raise; 31 of 32 pipelines to the end | 0 | under the 3-pipeline limit; counted against smb 26 |
| Throughput, per node-h, min 10–60 | rfd3 **271.1** (+3.2 %), boltz **262.7** (−0.9 %), mpnn 527.7 | 262.7 / 265.1 / 526.5 | pass |
| Yield, per GPU-h | passing **55.5** (+8.8 %), high-quality **20.4** (−8.1 %) | 51.0 / 22.2 | pass |
| Completion stalls > 15 s after min 10 | 2 (18 s, 15 s) | 8 (150 s) | — |
| Storage | 32,464 run + 3,552 session files for 1768 tool tasks = 20.4/task | — | see below |

**Storage, against the ~30/task in the criteria.** That figure came from adaptive runs. Files
per stage are unchanged against adaptive `23065238`: mpnn 48 vs 52, rfd3 7, boltz 11, packmin 3.
Pass-through runs about 2 mpnn per rfd3 instead of about 3, and mpnn is the heavy stage, so the
mix gives fewer files per task. Not a regression.

Other measurements:
- Fold pass rate 83.0 % in the window (185 of 223), against 76.6 %. The pass rate shifted while
  passing folds per GPU-h stayed within 10 %, which reads as run-to-run spread over about 220 folds.
- GPU busy 60–70 % mean (33–46 % at 100 %), against 58–62 %.
- `hostmem.csv` peak 174 GB of 243; seff reports 76 %.

**Not recorded in `RUNS.md`:** that tracker lists archived runs, and none of `23062773`,
`23065238` or this run is archived yet.
