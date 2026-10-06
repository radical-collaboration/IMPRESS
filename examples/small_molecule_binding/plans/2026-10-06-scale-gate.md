# 32-pipeline throughput gate past hour 2

**Status:** **passed.** Job `22701168` ran 2026-10-06 11:00:17 → 15:00:25 on gpub[073-080] (primary gpub075), `TIMEOUT` 04:00:08, on `<allocation A>`; every criterion met, including hours 3 and 4 · **Closes:** BACKLOG 1 and 6 · **Also measures:** 10 at scale, 7 on the primary

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
| 5 | GPU-hours per passing fold (lower is better; an earlier draft had the units inverted) | ≤ 0.194 | baseline 0.194; `22534628`: 0.666 |
| 6 | Primary-node CPU (`ResourceUpdate` per-node `cpu_percent`; primary from the job's `slurm.yaml`) | not saturated; record it either way | item 7: primary at 3.8 % idle on `22670942` |

**Reading the result:**
- If 1 and 2 pass, close items 1 and 6.
- If 1 fails but 2 passes, the limit is elsewhere. Check 6 (Dragon spin on the primary) first.
- If 3 fails, reopen item 10.

## Results (`22701168`)

Source: `impress_22701168.out` and `logs/22701168/telemetry/*.jsonl`, which covers 3.99 h of the 4.00 h run.

| # | Result | Verdict |
|---|---|---|
| 1 | rfd3/pipeline/h by hour: **15.16, 16.22, 16.28, 15.19** (h3 covers 0.99 h). 2006 rfd3 overall = **15.71**, which is 1.37× the 11.46 baseline. No hour-2 collapse; the h3 dip is under 7% | **pass** |
| 2 | Adaptive occupancy **0.96 %**, p99 **0.071 s**, max 0.79 s, from 13,074 paired `.out` calls. Telemetry durations agree: 0.81 % and 0.059 s over 13,060 calls. `22534628` was 67.1 % / 56.0 s | **pass** |
| 3 | 32/32 GPUs used, mean 9.4–15.3 % each. Per-node hourly means: 9–14 % in h0, 11–13 % in h1, 10–15 % in h2, 9–12 % in h3, so no decay toward ~1 % | **pass** |
| 4 | 0 `TaskFailed`, 0 tracebacks, 0 OOM, 0 `ERROR`; `sacct` `TIMEOUT` 04:00:08 | **pass** |
| 5 | 871 folds, 802 passed (92.1 %). 128.1 GPU-h / 802 = **0.160 GPU-h per passing fold** (baseline 0.194; `22534628` 0.666) | **pass** |
| 6 | Mean CPU over the run: primary gpub075 **62.7 %**, gpub073 57.5 %, others 46.2–47.5 %. Not saturated; the primary carries ~15 points more, from the `local` analysis stages and Dragon's managers (item 7) | recorded |

Stage completions over 4 h: rfd3 2006, boltz 871, mpnn 5928, fastrelax 1527.

**Reading:**
- 1 and 2 pass, so BACKLOG items 1 and 6 close.
- 3 passes at 8 nodes, so item 10 is confirmed at scale.
- The GPUs still sum to only ~45–55 % per node, and the primary has ~37 % CPU headroom. Raising pipelines per node above one per GPU is the obvious next throughput lever. That is not tested here.
- **Not observed:**
  - the `runner_status` launcher check, because `TIMEOUT` kills the job before it;
  - the teardown hang (item 2).

## Not covered by this test

- Item 2 (teardown hang): needs a run that finishes.
- Items 3–4: science decisions.
- Items 5, 9, 11: docs and setup.
