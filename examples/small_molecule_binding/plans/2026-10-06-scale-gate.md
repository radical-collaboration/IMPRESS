# Next test: 32-pipeline throughput gate past hour 2

**Status:** submitted 2026-10-06 09:00 as job `22701168` on `<allocation A>` (estimated start 11:00) · **Closes:** BACKLOG 1 and 6 · **Also measures:** 10 at scale, 7 on the primary

## Why this test

Every run since the delegation change has been 1 hour on 8–16 pipelines. The failure that matters happened on `22534628`, with 8 nodes / 32 pipelines, **after hour 2**:
- throughput fell to 14–15% of baseline;
- the adaptive callback took 67% of the manager's wall clock;
- GPU use fell to 0.7%.

The fixes for that (item 1: async adaptive callback + FASTA memo; item 6: delegation) have never been run in that regime. The GPU spread (item 10, `854ecd6`) has also only been seen on 2 nodes for 1 hour.

## Configuration

| | |
|---|---|
| Nodes / pipelines | **8 / 32** (one pipeline per GPU; all 32 `p*_in` present and verified on `/work/nvme`) |
| Partition | `gpuA40x4` (the interactive queue caps at 4 nodes / 1 h) |
| Walltime | **4 h**: two hours past the point where `22534628` collapsed. `max_tasks=300` is not reachable in 4 h (~14 rfd3/pipeline/h), so it ends in `TIMEOUT` and never reaches the teardown hang (item 2) |
| Cost | 32 GPU-h per hour, so 128 GPU-h |
| Code | `854ecd6` + the item 12 fix below |
| Submit | `sbatch --partition=gpuA40x4 --nodes=8 --time=04:00:00 delta_gpu_run.sh` from the clean login shell |

**Queue (`sbatch --test-only`, 2026-10-06):**

| Account | 8 nodes / 4 h | 4 nodes / 4 h |
|---|---|---|
| `<allocation B>` (lower fairshare) | 2026-10-25 | 2026-10-24 |
| `<allocation A>` (higher fairshare) | 2026-10-08 | 2026-10-07 |

## Before submitting

1. **Fix BACKLOG 12 — done.** `dragon` exits 0 when the runner crashes, so the runner now writes `<work_dir>/runner_status`, and `delta_gpu_run.sh` exits 1 unless it reads `ok`. A crash in this unattended run will therefore show as `FAILED` in `sacct`.
2. **Account: `<allocation A>`**, passed as `sbatch --account=<project>-delta-gpu` (overrides the script's `#SBATCH` line).
3. Nothing else changes: same `PROD` config and inputs.

## Measurements and pass criteria

All are taken after the run from `impress_<job>.out` and `logs/<job>/telemetry/*.jsonl`. The start is days out, so there will be no live `/proc` sampling unless someone is around.

| # | Measure | Pass | Reference |
|---|---|---|---|
| 1 | rfd3/pipeline/h, **per hour** (h0–1 … h3–4) | **≥ 11 in every hour, including h2–3 and h3–4** | 11.46 baseline; 12.05 → ~4 after h2 on `22534628`; 14.6 on `22692293` |
| 2 | Adaptive occupancy (paired `Adaptive function started/completed`, summed ÷ span) and p99 per call | **< 10 % and p99 < 2 s** | 3.4 % / 1.36 s at 16 pipelines; 67.1 % / 56.0 s on `22534628` |
| 3 | Per-GPU mean `gpu_percent`, per node per hour | all 32 GPUs non-zero; no decay toward ~1 % | `22692293`: 8–15 % each |
| 4 | Failures | 0 `TaskFailed`, 0 tracebacks, 0 OOM; `sacct` state `TIMEOUT` | — |
| 5 | Passing folds per GPU-hour | ≥ 0.194 | `22534628`: 0.666 GPU-h per passing fold |
| 6 | Primary-node CPU (`ResourceUpdate` per-node `cpu_percent`; primary from the job's `slurm.yaml`) | not saturated; record it either way | item 7: primary at 3.8 % idle on `22670942` |

**Reading the result:**
- If 1 and 2 pass, close items 1 and 6.
- If 1 fails but 2 passes, the limit is elsewhere. Check 6 (Dragon spin on the primary) first.
- If 3 fails, reopen item 10.

## Not covered by this test

- Item 2 (teardown hang): needs a run that finishes.
- Items 3–4: science decisions.
- Items 5, 9, 11: docs and setup.
