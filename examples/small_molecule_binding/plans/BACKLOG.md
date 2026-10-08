# Small-molecule binding — backlog tracker

Open work items for this example, newest evidence first. One line per item; details live in
the linked doc. Keep `Status` current and delete rows once the fix lands **and** a campaign
confirms it.

Source of most entries below: the 8-node / 32-pipeline campaign **job `22534628`**
(2026-09-29 23:23:40 → 2026-09-30 11:23:50, `State=TIMEOUT`, `Elapsed=12:00:10`).
Run artifacts archived at
`<hdd work dir>/impress-data-after-fixes/smb_8node/small_molecule_binding/`.

| # | Item | Severity | Status | Doc |
|---|---|---|---|---|
| 2 | Dragon `flow.shutdown()` teardown hang — no watchdog, wall limit is the only backstop | high | open | [dragon-teardown-watchdog](2026-09-30-dragon-teardown-watchdog.md) |
| 3 | `fastrelax` passes only 58% — the real scientific bottleneck, 510 failures / 833 backbone escalations | medium | open, needs decision | [fastrelax-pass-rate](2026-09-30-fastrelax-pass-rate.md) |
| 4 | `fold_min_ligand_iptm` gate is disabled; data supports enabling at 0.7 | low | open, needs decision | [ligand-iptm-gate](2026-09-30-ligand-iptm-gate.md) |
| 5 | `README.md` still documents `IMPRESS_TEST_MODE` and the `PROD`/`TEST` pair, both removed by PR #64 | low | open | — (doc-only; noted in CLAUDE.md 2026-09-28 row) |
| 7 | Dragon Batch pool workers and managers busy-spin when idle (~21–25 cores/node; primary 3.8% idle on `22670942`); pool size hardcoded `num_cpus // 2` = 32/node | high | open, upstream; local pool-shrink workaround drafted, not applied | [upstream/dragon-batch-idle-spin](upstream/dragon-batch-idle-spin.md) |
| 8 | asyncflow telemetry: Started/Completed/Failed carry the default backend's name; `node_id` never set on task events, so placement can't be read from the trace | medium | open, upstream | [upstream/asyncflow-telemetry-backend-and-node-id](upstream/asyncflow-telemetry-backend-and-node-id.md) |
| 9 | `delta_gpu_run.sh` caps pipelines by counting `p*_in` dirs, never checks their contents; `p2_in`–`p8_in` held only `ALR.smiles` and 7/8 pipelines died on `22669434`. Its "byte-identical, verified by checksum" comment is stale | low | open (dirs restored from `p1_in`; the `/work/nvme` copy of all 32 verified identical; no pre-flight check yet) | — |
| 11 | `delta_env_setup.sh` (as merged from main) does not build a working venv today. Unpinned resolution pulled `numpy 2.5.3` etc. against boltz 2.2.1's pins. boltz's dependencies are incomplete (13 missing, e.g. `lightning-utilities`), so the boltz CLI and its cache warm-up fail; the verify step only checks `import boltz`. LigandMPNN needs `ml_collections`. The PyRosetta installer uses the first `pip` on `PATH` | medium | worked around for `$WORK_DIR/ve/small_mol` with a 203-pin constraints file from the old venv (`$WORK_DIR/ve/small_mol.constraints.txt`) plus the missing packages; script fix still needed, here and on main | — |
| 12 | A crashed runner was recorded by Slurm as `COMPLETED`: job `22692267` died with a traceback 26 s in. **Cause:** `dragon -w ssh` itself exits 0 when the runner raises. `set -e` never fires, and the done banner prints. (The first diagnosis, that the final `echo` masked the status, was wrong: `set -e` would have stopped the script first.) | medium | **fixed, not yet seen on Delta**. The runner writes `ok` / `failed: <exc>` to `<work_dir>/runner_status`; `delta_gpu_run.sh` exits 1 unless it reads `ok`. A missing file also fails for the default runner, and only warns for the others. Tested offline: the real runner with a forced `ValueError` wrote `failed: ...` and exited 1; the launcher check returned the right exit for all 5 status/runner cases | — |
| 14 | Host RAM limits pipelines per node: a running rfd3 holds ~9.5 GB of host RAM. 32 pipelines starting together OOM-killed a node in 2 min (`22714785`) | high | **start fixed:** staggered start (60 s per group of one-pipeline-per-GPU) peaks at 62 % host RAM at 8/GPU (`22718758`). Steady-state rfd3 concurrency is still unbounded; watch `memory_percent` | [gpu-saturation](2026-10-07-gpu-saturation.md) |
| 15 | A failed stage kills its whole pipeline: after a `TaskFailed`, the pipeline dies with `'NoneType' object is not subscriptable` (`22714866` p7/p15) instead of retrying or escalating | medium | open | [gpu-saturation](2026-10-07-gpu-saturation.md) |
| 16 | rfd3 reported `TaskFailed` (`error_type=unknown`) after writing all its outputs (`22714866` p7/p15, both on GPU 2, unstaggered run) | low | open; not seen in the staggered runs (0 failures at 2/6/8 per GPU). Watch for recurrence | [gpu-saturation](2026-10-07-gpu-saturation.md) |
| 17 | Operating point is 6–8 pipelines per GPU (5.5× per-node rfd3 at 8/GPU, GPUs pegged 55–63 % of the time), but `delta_gpu_run.sh` still defaults to 1 per GPU and needs one `p*_in` dir per pipeline. Also restate the per-pipeline throughput gate (11 rfd3/pipeline-h) per node | medium | open; being exercised by the 8-node / 256-pipeline run | [gpu-saturation](2026-10-07-gpu-saturation.md) |
| 18 | mpnn keeps every candidate's `packed/` and `backbones/` PDB (~26 each per task, ~90% of run bytes) but only `best_packed_pdb` is read later. `22726386` lost 174 tasks to the shared inode quota (`Errno 122`) | high | open; blocks the `22726386` rerun | [run-storage-footprint](2026-10-08-run-storage-footprint.md) |
| 19 | No per-job packing: run dirs stay as 20k–400k loose files each after the job ends | medium | open | [run-storage-footprint](2026-10-08-run-storage-footprint.md) |
| 20 | Runner does not exit when every pipeline has failed: `22726386` idled from 03:39 to its 06:59 `TIMEOUT` (~27 node-h), no `runner_status` written. Related to 2 | high | open | [run-storage-footprint](2026-10-08-run-storage-footprint.md) |
| 21 | Job evidence split across the submit dir: `impress_%j.out`, `asyncflow.session.*`, `ddict_orc_*` land outside `IMPRESS_WORK_DIR` | low | open | [run-storage-footprint](2026-10-08-run-storage-footprint.md) |

## Closed 2026-10-06 by the 32-pipeline scale gate (`22701168`; [scale-gate](2026-10-06-scale-gate.md))

- **1** — `adaptive_decision()` blocking the event loop. Adaptive occupancy was 0.96 %, p99 0.071 s, at 32 pipelines over 4 h; `22534628` was 67.1 % / 56.0 s. Doc: [adaptive-callback-serialization](2026-09-30-adaptive-callback-serialization.md).
- **6** — tool stages delegated to asyncflow/rhapsody. 15.71 rfd3/pipeline/h over 4 h (1.37× the 11.46 baseline), no hour lower than 15.16, 0 failures. Doc: [backend-delegation](2026-10-04-backend-delegation.md).
- **10** — GPU tools all on GPU 0. Spread confirmed at 8 nodes: 32/32 GPUs at 9.4–15.3 % mean. Doc: [gpu0-only](2026-10-05-gpu0-only.md).
- **13** — follow-up on job `22701168`. Done; it passed every criterion.

## Conventions

- Cite the job ID and the archived artifact path for every claim, the way the CLAUDE.md
  revision-history rows do. A finding without a job number behind it does not belong here.
- "needs decision" means the data is in hand and a human has to pick a threshold — do not
  silently change a gate that alters which designs pass.
