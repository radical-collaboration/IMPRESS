# GPU saturation: pipelines-per-GPU ladder, staggered start, GPU logger

**Status:** ladder done (2026-10-06/07). The GPUs saturate at about **8 pipelines per GPU**. The 8-node production-scale follow-up is job `22747xxx` (see the end of this doc).
**Evidence:** jobs `22714785`, `22714866`, `22716150`, `22717753`, `22718758`; reference `22692293`.

## Why

The 32-pipeline scale gate (`22701168`, one pipeline per GPU) left the GPUs at 9.4–15.3 %. A running GPU tool uses only ~20 % of an A40, because apptainer start, model load and CPU pre/post-processing dominate. So the only lever that leaves the science config untouched is more concurrent pipelines per GPU.

## Ladder

Each rung is 1 node, 1 hour, on `gpuA40x4-interactive`. With `(N-1) % 4`, every GPU gets exactly k pipelines. Rates are per node-hour, counted from minute 10 so the staggered start does not penalize high k.

| Pipelines per GPU | Job | rfd3/node-h | boltz/node-h | mpnn/node-h | rfd3/pipeline-h | rfd3 median | GPU busy (mean) | GPU mem peak | Host RAM peak | CPU mean / max | Task failures | Folds passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `22692293` (2 nodes, per node) | 57.8 | 18.3 | 198 | 14.5 | 74 s | 11 % | – | 27 % | 51 / 65 % | 0 | 33/37 |
| 2 | `22716150` | 104.6 | 37.3 | 369 | 13.1 | 78 s | 23 % | 10 GB | 28 % | 48 / 57 % | 0 | 24/32 |
| 4 | `22714866` (no stagger) | 183.3 | 44.6 | 638 | 11.5 | 82 s | 39 % | 20 GB | 61 % | 43 / 68 % | 2 | 41/45 |
| 6 | `22717753` | 255.8 | 65.2 | 927 | 10.7 | 96 s | 60 % | 25 GB | 50 % | 58 / 66 % | 0 | 50/64 |
| **8** | `22718758` | **315.5** | **94.3** | 1073 | 9.9 | 110 s | **74 %** | 32 GB | 62 % | 68 / 83 % | 0 | 75/85 |
| 8 (no stagger) | `22714785` | **`OUT_OF_MEMORY` after 2 min** (host RAM 237 of 240 GB) | | | | | | | | | | |

**At k = 8, per GPU** (`nvsmi.csv`, after minute 10):
- median sample 99–100 %;
- at 100 % for **55–63 % of the time**;
- mean 70–76 %.

At k = 6 the same GPUs were at 100 % for only 35–45 % of the time.

**Reading:**
- **Per-node throughput rises to k = 8** (5.5× rfd3, 5.2× boltz vs k = 1), with diminishing steps: +75 % for 2→4, +40 % for 4→6, +23 % for 6→8.
- **The limit is the GPU.** At k = 8 the GPUs are pegged most of the time, and the rfd3 median rose 74 → 110 s from queueing on the GPU. Other resources had room: CPU 68 % mean, host RAM 62 %, GPU memory 32 of 48 GB. Beyond k = 8 we expect ≲ 10–15 % more.
- **Cost:** ~0.048 GPU-h per passing fold at k = 8, against 0.160 at k = 1 (`22701168`).
- **Quality:** the fold pass rate varied 75–91 % with no trend in k; that looks like noise at these counts.
- **Operating point:** 6–8 pipelines per GPU. Per-pipeline rates fall below the scale gate's 11 rfd3/pipeline-h from k ≈ 6. That gate should be stated per node (≥ 4 × 11 = 44 rfd3/node-h) when pipelines share GPUs.
- **The manager stayed idle at k = 8:**
  - the adaptive callback took ≤ 0.4 % of wall clock;
  - in-process analysis stages took 0.28 % of the event loop.

## Fix 1: staggered start (`run_small_molecule_binding.py`, `small_molecule_binding.py`)

**Problem:** every pipeline starts with rfd3, and a running rfd3 holds **~9.5 GB of host RAM for its whole run**.
- At 16 pipelines (`22714866`), host RAM went 13 % → 61 % within 45 s, held until ~130 s, then fell to 12–15 %. It peaked at ≤ 45 % for the rest of the hour.
- At 32 pipelines the first wave alone exceeds the 240 GB `--mem`, so `22714785` was OOM-killed at 2 minutes.

**Fix:**
- The runner gives pipeline `pN` `start_delay = ((N-1) // slots) * START_STAGGER_S`, where:
  - `slots` = GPUs per node × nodes (`_n_nodes()`; `System().nnodes` under Dragon);
  - `START_STAGGER_S = 60`.
- `SmallMoleculeBindingPipeline.run()` sleeps `start_delay` before its first stage, logging `start delayed Ns (staggered start)`.
- Effect: at one pipeline per GPU every delay is 0, so normal runs are unchanged. At k pipelines per GPU, the starts come in k groups, one pipeline per GPU each, 60 s apart.
- The runner logs the schedule as a `[GPU] staggered start (...)` line.

**Result:** host RAM peaked at 28 / 50 / 62 % at k = 2 / 6 / 8, with no OOM. Measured throughput excludes the first 10 minutes. The ramp costs (k-1) minutes once per run.

## Fix 2: GPU usage logger (`delta_gpu_run.sh`)

Telemetry records `gpu_percent` but not GPU memory, and GPU memory is what limits packing tools onto a GPU.

- The launcher starts `nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits -l 10` in the background, writing to `${IMPRESS_WORK_DIR}/nvsmi.csv`, and stops it after the run.
- On an early exit or `TIMEOUT`, Slurm reaps it with the job.
- It runs on the batch node only, so a multi-node job logs just that node.
- Where there is no GPU driver (e.g. the login node), the error lands in the CSV and the script continues.
- Its utilization agrees with telemetry's `gpu_percent`: k = 4 GPU 0 was 46.8 % (nvsmi) vs 49.4 % (telemetry).

## Other findings

- **rfd3 reported failed after writing its outputs.** On `22714866`, p7 and p15 (both on GPU 2): the captured stderr shows inference finished and all 4 models were written, yet the task was `TaskFailed`, `error_type=unknown`. `rfd3.sh` does nothing after `apptainer exec`. Not seen again in the staggered runs (k = 2/6/8: 0 failures). Possibly linked to the unstaggered memory spike; not confirmed.
- **A failed stage kills its pipeline.** Both pipelines above then died with `'NoneType' object is not subscriptable`, and GPU 2 ran half-loaded for the rest of the hour. Tracked in BACKLOG.

## Follow-up: 8 nodes, 8 pipelines per GPU, 4 h

Production-scale check of the operating point:
- 256 pipelines on 8 nodes (`p1_in` … `p256_in`; p33–p256 copied from `p1_in`);
- `gpuA40x4`, 4 h, `<allocation A>`;
- stagger: 8 groups of 32, so a 7-minute ramp.

**Risks to watch:**
- **Dragon placement:** Batch picks nodes, so per-node load can be uneven, and with it per-node host RAM.
- **Dragon's worker pool:** 32 per node × 8 = 256, exactly one per pipeline.
- **The primary:** it carries all 256 pipelines' in-process analysis and adaptive work. That projects to ~8 % of the event loop each.
- **nvsmi:** logs only the batch node.
