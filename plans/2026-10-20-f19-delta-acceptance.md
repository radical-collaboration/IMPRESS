# F19 — declared adaptive tasks, acceptance run on Delta

**Status:** submitted as job `23062773` (2026-10-20, from `22a1f82`) · **Branch:** `framework-defaults-pr1` at `22a1f82` · **Blocks:** pushing and merging PR 1 · **Items:** F19

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
