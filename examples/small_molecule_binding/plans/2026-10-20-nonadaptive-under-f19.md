# Pass-through routing under F19 (smb 23 re-run)

**Status:** planned, not yet submitted · **Branch:** `smb-benchmark-f19` (merge `d571de2` of
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
- Add the job to `RUNS.md`.
