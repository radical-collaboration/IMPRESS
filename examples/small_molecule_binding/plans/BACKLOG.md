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
| 1 | `adaptive_decision()` blocked the event loop; uncached `_read_fasta_seq` made it O(ensemble) Lustre reads | **critical** | **fixed, unvalidated at scale** | [adaptive-callback-serialization](2026-09-30-adaptive-callback-serialization.md) |
| 2 | Dragon `flow.shutdown()` teardown hang — no watchdog, wall limit is the only backstop | high | open | [dragon-teardown-watchdog](2026-09-30-dragon-teardown-watchdog.md) |
| 3 | `fastrelax` passes only 58% — the real scientific bottleneck, 510 failures / 833 backbone escalations | medium | open, needs decision | [fastrelax-pass-rate](2026-09-30-fastrelax-pass-rate.md) |
| 4 | `fold_min_ligand_iptm` gate is disabled; data supports enabling at 0.7 | low | open, needs decision | [ligand-iptm-gate](2026-09-30-ligand-iptm-gate.md) |
| 5 | `README.md` still documents `IMPRESS_TEST_MODE` and the `PROD`/`TEST` pair, both removed by PR #64 | low | open | — (doc-only; noted in CLAUDE.md 2026-09-28 row) |
| 6 | Tool stages delegated to asyncflow/rhapsody (per-task env; `mpnn` off the primary's GPUs; adaptive callback on a `local` backend; `rfd3`/`boltz` capped 2026-10-05) | medium | **2-node smoke (`22670942`), 4-node 1 h (`22675825`, 13.1 rfd3/pipeline/h) and post-merge gate (`22684833`) passed, all 0 failures; throughput gate past hour 2 open** | [backend-delegation](2026-10-04-backend-delegation.md) |
| 7 | Dragon Batch pool workers and managers busy-spin when idle (~21–25 cores/node; primary 3.8% idle on `22670942`); pool size hardcoded `num_cpus // 2` = 32/node | high | open, upstream; local pool-shrink workaround drafted, not applied | [upstream/dragon-batch-idle-spin](upstream/dragon-batch-idle-spin.md) |
| 8 | asyncflow telemetry: Started/Completed/Failed carry the default backend's name; `node_id` never set on task events, so placement can't be read from the trace | medium | open, upstream | [upstream/asyncflow-telemetry-backend-and-node-id](upstream/asyncflow-telemetry-backend-and-node-id.md) |
| 9 | `delta_gpu_run.sh` caps pipelines by counting `p*_in` dirs, never checks their contents; `p2_in`–`p8_in` held only `ALR.smiles` and 7/8 pipelines died on `22669434`. Its "byte-identical, verified by checksum" comment is stale | low | open (dirs restored from `p1_in`; the `/work/nvme` copy of all 32 verified identical; no pre-flight check yet) | — |
| 10 | Every GPU tool runs on GPU 0: Dragon process tasks get no `gpu_affinity`, so all see `CUDA_VISIBLE_DEVICES=0,1,2,3` and pick `cuda:0`. GPUs 1–3 were 0% on both nodes of `22684833`, and the ~10–15% "mean GPU" of every campaign is one busy GPU averaged over four | **high** | open, diagnosed; candidate fix is a per-task `gpu_affinity`/`CUDA_VISIBLE_DEVICES` | [gpu0-only](2026-10-05-gpu0-only.md) |
| 11 | `delta_env_setup.sh` (as merged from main) does not build a working venv today. Unpinned resolution pulled `numpy 2.5.3` etc. against boltz 2.2.1's pins. boltz's dependencies are incomplete (13 missing, e.g. `lightning-utilities`), so the boltz CLI and its cache warm-up fail; the verify step only checks `import boltz`. LigandMPNN needs `ml_collections`. The PyRosetta installer uses the first `pip` on `PATH` | medium | worked around for `$WORK_DIR/ve/small_mol` with a 203-pin constraints file from the old venv (`$WORK_DIR/ve/small_mol.constraints.txt`) plus the missing packages; script fix still needed, here and on main | — |

## Item 1 status detail

Fixed on branch `scaling-wide`:

- `small_molecule_binding.py` — `_read_fasta_seq` memoised (`_FASTA_SEQ_CACHE`);
  `_parse_pdb_ca_coords` `lru_cache` raised 512 → 4096.
- `run_small_molecule_binding.py` — `adaptive_decision()` split into an `async` wrapper that
  `await asyncio.to_thread(...)`s a synchronous `_adaptive_decision_sync()` body. Since superseded
  by item 6: the callback now runs as `flow.function_task(backend="local")` on a thread-pool
  rhapsody backend rather than via `asyncio.to_thread`.

Validated offline: 12/12 adaptive branch cases produce identical `(next_step, seq_retry_count,
rfd3_input_pdb)` cached vs uncached; the event loop now ticks during a cold 1200-entry decision
(it did not before). **Not yet validated at scale** — needs the acceptance test in the doc.

## Conventions

- Cite the job ID and the archived artifact path for every claim, the way the CLAUDE.md
  revision-history rows do. A finding without a job number behind it does not belong here.
- "needs decision" means the data is in hand and a human has to pick a threshold — do not
  silently change a gate that alters which designs pass.
