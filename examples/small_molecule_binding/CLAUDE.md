# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-04-06 | 3390b61 | change log added |
| 2026-09-01 | —      | RunConfig dataclass; PROD/TEST named configs replace flat if/else constants |
| 2026-09-09 | —      | Replaced broken RFD3 `scaffoldguided.target_pdb` scaffold feedback with real RFD3 partial-diffusion guidance (`partial.input`/`partial_t`); replaced AlphaFold2/ColabFold fold-validation step with Boltz-2 (protein+ligand co-folding) |
| 2026-09-09 | —      | Fixed `analysis_sequence()` silently never comparing MPNN candidates (it only ever read each `.fa` file's first line — the un-designed template record — since real LigandMPNN writes multiple candidates into one file, not one file per candidate); now parses every candidate record and picks the true highest-confidence one |
| 2026-09-09 | —      | Added a metric-agnostic non-improvement short-circuit to `fastrelax`/`interface` retry logic — escalates to a new backbone (`STEP_RFD3`) as soon as a retry fails to improve on the previous attempt, instead of always exhausting 5 resequencing retries on backbones that real data showed never recover |
| 2026-09-09 | —      | Fixed guided-RFD3 ligand atom-name mismatch that crashed 4/4 pipelines in a real production run (job `21916521`) on their first guided-backbone-feedback attempt: `_normalize_ligand_id()` only rewrote the Boltz co-folded PDB's ligand *residue* name, not its Boltz-assigned *atom* names, so `select_exposed`/`select_buried` (copied verbatim from the base spec, keyed by canonical `.params` atom names) never matched and RFD3's validator rejected every guided run. New `_infer_ligand_atom_mapping()`/`_normalize_ligand_atom_names()` establish atom correspondence via element+connectivity graph isomorphism (rdkit) with a Kabsch-RMSD tie-break; `_write_guided_rfd3_json()` now also verifies atom-name coverage before writing. Adds an `rdkit` runtime dependency |
| 2026-09-09 | —      | Fixed a second guided-RFD3 crash found in a real production run (job `21928556`, 3/3 pipelines that reached guided feedback crashed on their very first attempt): `_write_guided_rfd3_json()` copied the base spec's `partial.length` field verbatim into the guided JSON, but RFD3's `DesignInputSpecification` validator rejects `length` outright whenever `partial.input`/`partial_t` (partial diffusion) are set (`ValidationError: ... Length argument must not be provided during partial diffusion`) — length is inferred from the input structure in that mode. `_write_guided_rfd3_json()` now drops `length` from the guided spec |
| 2026-09-26 | —      | Scaled the Delta allocation up, and fixed two latent blockers found while doing it. `delta_gpu_run.sh`: `--cpus-per-task` 16→64 and `--time` 4h→48h — the three prior PROD runs all died at TIMEOUT and `seff` showed 97.7-98.1% CPU efficiency on 16 cores while using only 29% of memory, and since billing is `max(cpu*31.25, mem/8, gpu*500)` under `MAX_TRES` the extra 48 cores cost nothing (the gpu term already sets the bill at 2000); also `--mem` 220G→240G (`RealMemory` 257637MB less `MemSpecLimit` 8450 = 249187MB ceiling) and an explicit `--account`. **Blocker 1:** `CUDA_HOME`/`MPI_LIB`/`FAB_LIB` were hardcoded to CUDA 25.3 / mpich 8.1.32 / libfabric 1.22.0, all removed by Delta's Cray PE upgrade — inert under `dragon -s` (no transport agent is started) but `dragon -m` dlopens libdfabric out of `FAB_LIB` and hangs with almost no diagnostic; now autodetected with an existence check, since `dragon-config add` does not validate the path it stores. **Blocker 2:** the `--mail-user=<your e-mail>` placeholder made `sbatch` parse `e-mail>` as a directive (`Invalid directive found in batch script`), so the script could not be submitted at all. Also: `dragon-config -c` before `add` (it appends, so a stale path would survive), `SLURM_OVERLAP=1` (Dragon's own srun steps lack `--overlap`), refuse the node-local `/tmp` foundry extraction when `--nodes>1`, corrected three `${SCRATCH}/${USER}` defaults that expanded to a doubled `$USER/$USER`, and added `OMP_NUM_THREADS`/`OMP_WAIT_POLICY` (nothing set a thread cap anywhere, so each of N concurrent head-node subprocesses grabbed all 64 cores). New `IMPRESS_N_PIPELINES` env var scales pipeline count with the allocation, capped at the number of `p{i}_in` dirs that exist. `scripts/boltz.sh`: added the `VIRTUAL_ENV` guard `fastrelax.sh`/`packmin.sh`/`filter_shape.sh` already carry — it is one of only two tasks dispatched to Dragon and resolves `boltz`/`python` purely via inherited PATH, which is what breaks on a remote node. Note GPU placement is deliberately NOT pinned here; per "Execution backends" below that is the backend's responsibility |
| 2026-09-27 | —      | Multi-node scale-up on Delta (4 nodes / 16 pipelines, job `22491438`, 98% per-pipeline scaling efficiency vs the 2-node baseline). **`dragon -m` does not work on Delta**: its slurm backend launcher builds `srun --nodelist=` from `gethostname()`, which returns FQDNs here while Slurm's `NodeName` is short (`gpub039`), so the step is unsatisfiable (`Requested node configuration is not available`) and the job hangs to the wall clock — confirmed job `22456499`; `--hostlist` is not a workaround, `SlurmWLM.__init__` accepts `_hostlist` and never uses it. `delta_gpu_run.sh` now follows `ARCHIVE-run_impress.slurm` for `SLURM_NNODES>1`: `dragon-network-config --output-to-yaml` into a per-job dir, then `dragon -w ssh --network-config <yaml> -t tcp` — ssh builds no `--nodelist` (and Delta sets `HostbasedAuthentication`/`EnableSSHKeysign` cluster-wide, so no user keys are needed), while `-t tcp` avoids the HSTA/OFI `libdfabric` dlopen. **Run config now travels as argv, not environment**: `dragon -w ssh` forwards only `BASE_ENV_VARNAMES` (`PATH`, `PYTHONPATH`, `LD_LIBRARY_PATH`, `PYTHONSTARTUP`, `VIRTUAL_ENV`, `DRAGON_*`), so `IMPRESS_TEST_MODE`/`IMPRESS_N_PIPELINES`/`IMPRESS_WORK_DIR`/`OMP_NUM_THREADS` were silently dropped and job `22466127` ran PROD defaults despite `IMPRESS_TEST_MODE=1`. `run_small_molecule_binding.py` takes `--n-pipelines`/`--work-dir` (CLI > env > config default) and sets `OMP_NUM_THREADS` and friends in `os.environ` itself, sized from `sched_getaffinity` so it respects the cgroup. Note `MPNN_DIR`/`BOLTZ_CACHE`/`FOUNDRY_SIF_PATH`/`SCRATCH` survive that hop **only** because `~/.bashrc` exports them — do not rely on that for new settings. `IMPRESS_WORK_DIR` is now scoped per job (`logs/${SLURM_JOB_ID}`): `taskcount` restarts at 1 each run, so a shared work dir silently overwrites the previous run's task dirs |
| 2026-09-27 | —      | **First 4-node production campaign (job `22491438`) completed**: 16/16 pipelines reached the `max_tasks=300` budget in 6h41m, 552 passing folds, 0 OOM/tracebacks/task failures. Scaling measured at **98% per-pipeline efficiency** vs the 2-node baseline (11.46 vs 11.69 rfd3/pipeline/h; 3.9x job-wide for 4x pipelines), with per-node CPULoad balanced at 26-40 of 64 and the primary no busier than the rest — so the "11 of 13 tasks are `local_task=True` and pinned to the primary node" ceiling is real but **not binding at 16 pipelines**. **New defect: the Dragon teardown hangs.** After `[MANAGER] All pipelines finished. Exiting.` and `Shutting down Dragon backend` at 22:23:11, `flow.shutdown()` never returned; the job sat for exactly 60 minutes and had to be `scancel`led, ending `State=CANCELLED` at `Elapsed=07:41:11` with `=== ... pipeline done ===` never printed. That burned **~64 GPU-hours (37% of the job's billed total) for zero output**, and the burn rate doubles to 32 GPU-h per hung hour at 8 nodes. Since there is no resume and no watchdog, the SLURM wall limit is the only backstop — so future runs should right-size `--time` (a 48h request lets an unattended hang bill the whole remainder) and bound `flow.shutdown()` in code so the job self-terminates once the work is provably complete |
| 2026-09-28 | —      | Merged `main` (PR #64, `adbd249`, "Remove IMPRESS_TEST_MODE") into this branch. That PR deleted the `TEST` `RunConfig`, the `cfg = TEST if ... else PROD` conditional and the `IMPRESS_TEST_MODE` export — the same three regions this branch had rewritten so run config could travel as argv over `dragon -w ssh`, so neither file auto-merged. Resolved in `main`'s favour on *whether* test mode exists (it does not: `--test-mode` dropped from the argparse and from `RUNNER_ARGS`, `cfg = PROD` unconditionally) and in this branch's favour on everything else — the `--n-pipelines`/`--work-dir` argv plumbing and the `sched_getaffinity` thread caps are load-bearing for multi-node and orthogonal to the flag. One consequence worth noting: the `cfg is PROD` guard on `IMPRESS_N_PIPELINES` existed only to stop the pipeline count overriding the fixed-size `TEST` config, so with `TEST` gone it is vacuous and was removed. `README.md` still documents `IMPRESS_TEST_MODE` and the `PROD`/`TEST` pair — that staleness came in with PR #64 itself and is left for a separate change rather than widened into this branch's diff |
| 2026-09-28 | —      | **Telemetry wired for all 13 tasks.** Enabling asyncflow telemetry is three lines on `ImpressManager`, but the `protein_binding` reference wiring copied verbatim yields a trace that answers nothing: (a) `auto_register_task(local_task=True)` returns the raw coroutine and never reaches asyncflow, so only `rfd3`/`boltz` emit lifecycle events while the other 11 stages — the ones that run on the primary node — are invisible; (b) executable tasks are labelled `shlex.split(cmd)[0]`, i.e. always `bash` (**3486/3486** in the reference), so even those two are indistinguishable. Fixed with an `impress.LocalStage` custom event plus a `_timed_local` decorator on all 11 local stages (additive — converting them to `flow.function_task` is not drop-in, since they mutate `self.state`/`self.taskcount` in-process and the `OMP_NUM_THREADS` cap depends on them being subprocesses of the runner) and `workflow_id=` at the two Dragon call sites. Config deviates from the reference deliberately: `checkpoint_path` derived from the resolved `work_dir` (a relative path resolves against `$SCRATCH`, not the source tree, and this inherits per-job scoping), `resource_poll_interval=15.0` (5.0 made ResourceUpdate 69% of the reference file), `checkpoint_interval=300.0` (omitted upstream, so a wall-clock kill loses the 128KB-buffered file), and `stop()` in `finally` before `flow.shutdown()` (upstream has it in `try` and loses the file on any error). **Note the overlap with `origin/update_usecases/telemetry`** (`b8035a4`), which solves the same local-task blindness at the framework level via `wrap_local_task` in a new `src/impress/utils/telemetry.py`. That branch is not in `main` and does not apply to it — it predates PR #60's lifecycle rework and still calls `ImpressManager(execution_backend=...)`/`DragonExecutionBackendV3` — so this example-side wiring is what works against `main` today. If it ever lands, drop `_timed_local` rather than running both, or every local stage emits twice |
| 2026-09-28 | —      | **Stage 4 prepared: 8 nodes / 32 pipelines (not submitted).** `scripts/rfd3.sh` `dump_trajectories=False` — the per-step `*_noisy_*`/`*_denoised_*` files are 11.85 MB of each 11.92 MB rfd3 output dir (99.4% of rfd3's footprint, ~88% of a whole campaign's), and dropping them takes the campaign from ~30 GB to ~3.8 GB. Safe two ways: a repo-wide grep for `traj` outside the flag returns no hits, and `analysis_backbone` builds its candidate list from `.json` files containing `_model_` then derives the structure via `.replace('.json', '.cif.gz')` — trajectory files ship no `.json`, so they are structurally unreachable by that selection. `delta_gpu_run.sh` `--time` 48h→**12h**: the wall limit is the only backstop against the Dragon teardown hang recorded above, and at 8 nodes a hang bills 32 GPU-h per idle hour, so 48h would expose ~1536 GPU-h versus 384 at 12h. Sized as ~6.8h measured compute (unchanged by width — each pipeline independently accumulates its own `max_tasks` entries) + ~1h teardown + slack down to ~62% of baseline throughput; `sbatch --test-only` returns an identical queue start estimate for 8/12/16/24/48h, so shortening costs nothing, and not below 12h because there is no checkpoint and a TIMEOUT loses all in-memory ensemble state. `p17_in`…`p32_in` created (all 32 checksum-identical, gitignored) so 8 nodes yields 32 pipelines with zero idle GPUs. **Correction to the 2026-09-27 row's load analysis:** the Dragon primary is **not** the batch node — `dragon-network-config` marks `gpub068` `is_primary`, and it was the busiest node (39.7/64 = 62%), ~10 cores above the others, which is the `local_task` load. A naive doubling to 32 pipelines projects to ~124%, i.e. oversubscribed, with `OMP_NUM_THREADS` already at its floor of 1. Always check `is_primary` before reading a load figure |
| 2026-09-30 | —      | **Stage 4 ran and exposed the real scaling ceiling: the manager, not the nodes.** Job `22534628` (8 nodes / 32 pipelines) hit `TIMEOUT` at `Elapsed=12:00:10` with only 1 of 32 pipelines reaching `max_tasks=300` (mean 227.6). Throughput ran at **105% of the 4-node baseline for the first two hours**, then collapsed to 14-15% and never recovered (4.24 rfd3/pipeline/h over the run, 37% of the 11.46 baseline); mean GPU utilisation fell 11.1% → **0.7%** while per-node CPULoad held 26-34 of 64 — the hardware was *idle*, so this was starvation. Root cause: `adaptive_decision()` was declared `async def` with **zero `await` in its 220-line body**, so each call blocked the single event loop shared by all 32 pipelines (dispatch, subprocess reaping, Dragon completions). What made each call expensive is that `_ensemble_selective_avg()` invokes `sim_fn` once per prior entry and `_seq_identity`→`_read_fasta_seq` was **uncached** — ~540 blocking Lustre opens per decision at ensemble 270, O(entries²) over a run, against ~245k small files. `_parse_pdb_ca_coords` was already `@lru_cache`'d, which is precisely why `backbone`/`fold` cost ~0 while `sequence` took 4.93 of 4.98 adaptive hours. Adaptive occupancy of manager wall clock went **3.4% at 16 pipelines → 67.1% at 32** (73-95% for the last nine hours) with p99 per-call 1.36s → 56.0s while the *median* stayed flat — a tail explosion, i.e. a serial server crossing saturation, not a gradual slowdown. Diagnostic that rules out the filesystem: in hour 4 every stage's median inflated together (mpnn 23x, packmin 41x, filter_shape 32x, boltz 32x) with GPUs at 0.7% — only a blocked loop that cannot reap completions does that. Fixed both halves: `_read_fasta_seq` memoised via `_FASTA_SEQ_CACHE` (path-keyed, sound because `taskcount` makes every path write-once; negative results deliberately not cached), `_parse_pdb_ca_coords` `lru_cache` 512→4096 (the manager is one process shared by all pipelines, so the working set is entries × n_pipelines), and `adaptive_decision()` split into an `async` wrapper that `await asyncio.to_thread(_adaptive_decision_sync, ...)`. Verified 12/12 adaptive branch cases identical cached vs uncached, and the loop now ticks during a cold 1200-entry decision. **Cost of the defect: 0.666 GPU-h per passing fold vs the baseline's 0.194 — 2x the hardware for 1.05x the output.** Science was unaffected and is the best recorded: 624 folds, 577 passing (92.5%), median `complex_plddt` 93.3 / `ligand_iptm` 0.870, **392 (62.8%) high-quality on both axes across 31 of 32 pipelines**, zero tracebacks/OOM/task failures in 63,589 log lines. **Correction to the 2026-09-28 row:** its ~124% primary-node oversubscription projection did *not* materialise — `gpub068` ran 34.68/64, only ~4 cores above the mean. Open items tracked in `plans/BACKLOG.md` |
| 2026-10-04 | —      | **Compute delegation handed back to asyncflow/rhapsody.** Since `d8c1b4b`, 11 of 13 stages had been `local_task=True`. Five of them (`mpnn`, `packmin`, `fastrelax`, `filter_shape`, `filter_energy`) spawned their own `asyncio.create_subprocess_shell` children on the Dragon primary node, which forced the runner to set process-wide thread caps (`sched_getaffinity // (2*n_pipelines)`) and left `mpnn` — a CUDA tool — running unscheduled on the primary node's GPUs. All five are now asyncflow executable tasks on the default `compute` backend, following the existing `rfd3`/`boltz` pattern. Each gets its thread caps as a per-task `task_description` env (see "Execution backends"); the runner's `os.environ` block is gone. `adaptive_decision` now runs as `flow.function_task(backend="local")` on a thread-pool `ConcurrentExecutionBackend` instead of `asyncio.to_thread`, so it is bounded by the backend and visible in telemetry. Supersedes the 2026-09-28 note that conversion was "not drop-in": `taskcount`/`state` bookkeeping stays in the coroutine, which runs in-process before dispatch. Kept: the `--n-pipelines`/`--work-dir` argv plumbing (a `dragon -w ssh` launcher limit, not compute delegation) and the `_read_fasta_seq` memo. `mpnn.sh`/`filter_energy.sh` gain the `VIRTUAL_ENV` guard, now that they can run off the primary. Verified offline against the real stack: per-task caps reach each tool while the runner's env has none; logs are at the old paths; failures raise with the log tail; 144/144 adaptive decisions ran as `backend=local` tasks. **Not yet run on Delta**; acceptance test in `plans/2026-10-04-backend-delegation.md` |
| 2026-10-05 | —      | **Delegation validated on Delta; `rfd3`/`boltz` capped.** Smoke job `22670942` (2 nodes, 8 pipelines, `gpuA40x4-interactive`, 1 h, `TIMEOUT` as expected): **0 task failures**. Completed: mpnn 337, packmin 108, fastrelax 82, filter_shape 32, rfd3 101, boltz 29, adaptive 689 on `local`. 24/29 folds passed; ~13 rfd3/pipeline/h, a first-hour figure only. Per-node `/proc` sampling on `22669434` confirmed the converted stages run on the **non-primary** node too, with per-task caps intact after the `dragon -w ssh` hop. Telemetry cannot show this, because `node_id` is null on task events. That run was effectively 1 pipeline: `p2_in`–`p8_in` held only `ALR.smiles` (mtime 2026-09-30 12:56), so p2–p8 died on their first `rfd3`. The dirs were restored from `p1_in`, and the launcher's lack of a contents check is BACKLOG item 9. Found during the run: uncapped `boltz` (~3,030% CPU) and `rfd3` (~680%) oversubscribed the primary (3.8% idle). Both now get `GPU_TOOL_THREADS=8`. Also found: Dragon Batch's idle pool workers and managers spin ~21–25 cores per node, and asyncflow mislabels the backend on post-submit events. Both are written up for upstream in `plans/upstream/` (BACKLOG items 7–8) |
| 2026-10-05 | `ebfc0cb` | **Merged `origin/main`; moved to main's `WORK_DIR=/work/nvme` layout; 4-node and post-merge gate runs passed.** **Merge:** PR #67 (`SCRATCH`→`WORK_DIR`, apptainer bind fix, `boltz: command not found` fix) and PR #68 (docs; `src/impress` changes are docstrings only). Three conflicts were resolved: `delta_gpu_run.sh` keeps this branch's multi-node/argv/autodetect logic with main's `WORK_DIR` defaults (main's re-hardcoded `CUDA_HOME`/`MPI_LIB`/`FAB_LIB` were dropped in favour of the autodetect); `boltz.sh` keeps both the venv re-activation guard and main's `BOLTZ_VENV` PATH prepend; `rfd3.sh` uses main's `WORK_DIR` bind. **Layout:** working copy, inputs, `LigandMPNN`, `.cache/boltz`, `.foundry`, `foundry.sif` and a new venv `ve/small_mol` all live under `$WORK_DIR`. `~/.bashrc` now exports `WORK_DIR` and points `MPNN_DIR`/`BOLTZ_CACHE`/`FOUNDRY_SIF_PATH`/`FOUNDRY_CHECKPOINT_DIRS` there (backup `~/.bashrc.bak-2026-10-05`). The `/work/hdd` checkout, data and `~/ve/impress` are left intact. **Venv:** `delta_env_setup.sh` did not build a working environment (BACKLOG 11: unpinned drift, incomplete boltz dependencies, missing `ml_collections`, PyRosetta installer using the first `pip` on `PATH`); it was rebuilt against a 203-pin constraints file taken from the old venv, so the stack is unchanged (asyncflow 0.5.1, rhapsody 0.5.0, dragonhpc 0.14.1). **Runs:** `22675825` (4 nodes, 16 pipelines, 1 h): 0 failures, 13.1 rfd3/pipeline/h (~100% first-hour scaling from 2 to 4 nodes), 71/79 folds. `22684833` (post-merge gate, 2 nodes, from `/work/nvme`): 0 failures, all stages, 13.1 rfd3/pipeline/h, 27/29 folds; remote placement inferred from GPU 0 activity on the non-primary, not sampled. **Finding:** every GPU tool runs on GPU 0, so 3 of 4 GPUs per node are idle (BACKLOG 10) |
| 2026-10-06 | — | **GPU tools spread over all 4 GPUs (BACKLOG 10 done).** **Cause** (from the installed Dragon 0.14.1 source): a Batch process task with no `gpu_affinity` resolves to every GPU on its node, local services sets `CUDA_VISIBLE_DEVICES=0,1,2,3`, and rfd3, boltz and LigandMPNN all take the first device. **Fix:** the runner gives pipeline `pN` one device, `(N-1) % gpus`. `_tool_task_description(..., gpu=True)` passes it to mpnn/rfd3/boltz as `process_template["policy"] = Policy(gpu_affinity=[g])`, or as `CUDA_VISIBLE_DEVICES` on the Concurrent backend. A template-env `CUDA_VISIBLE_DEVICES` does not work under Dragon, because local services overwrites it from the policy layout. Batch still picks the node. **Verified on `22692293`** (2 nodes, 8 pipelines, 1 h; vs `22684833`): `/proc` shows one device per tool process; every GPU is used (8–15% mean each, against 0% on GPUs 1–3 before); 0 failures. rfd3 completions rose 99→117 (+18%; median 94→74 s), boltz 29→37 (+28%), folds passed 33/37. **Notes:** Batch's first wave put odd pipelines on one node and even on the other, so each node briefly used only 2 GPUs; placement mixed within minutes. Each node's GPUs sum to ~40–50%, so the GPUs are no longer the limit. A first attempt (`22692267`) crashed because `gpu_index` was set after `super().__init__()`, which registers the tasks. Slurm called that crash `COMPLETED`, because the launcher's final `echo` masks the exit status (BACKLOG 12). Upstream ask: `plans/upstream/dragon-batch-no-gpu-accounting.md` |

## Context

This directory is an **example workflow** within the larger [IMPRESS framework](https://github.com/radical-collaboration/IMPRESS) (Integrated Machine-learning for PRotEin Structures at Scale). IMPRESS is an HPC framework for protein inverse design using Foundation Models.

The framework package lives at `../../` (two levels up). Install it with:
```shell
cd ../../
pip install .
```

## Running the Pipeline

```shell
python run_small_molecule_binding.py
```

Before running on HPC, edit the path constants at the top of `run_small_molecule_binding.py` and the `__init__` kwargs in `SmallMoleculeBindingPipeline` (`foundry_sif_path`, `boltz_cache_path`, `mpnn_dir`, `ligand_params`, etc.) to match the target system.

## Architecture

### Two-file structure

- **`small_molecule_binding.py`** — defines `SmallMoleculeBindingPipeline(ImpressBasePipeline)`, all step constants, ensemble utility functions (`_ca_rmsd`, `_seq_identity`, `_ensemble_selective_avg`), and the inner `_run_refine_cycle()` loop. All pipeline tasks (HPC and local analysis) are registered via `@self.auto_register_task()` inside `_register_real_tasks()`. The `run()` method drives a state-machine loop; `_run_refine_cycle()` handles the MPNN+PackMin inner loop with per-cycle sequence retry support.

- **`run_small_molecule_binding.py`** — entry point. Defines the `RunConfig` dataclass and the single `PROD` instance (the `TEST` config and `IMPRESS_TEST_MODE` were retired upstream by PR #64); parses `--n-pipelines`/`--work-dir` from argv; defines the `adaptive_decision()` callback; creates the execution backend and the `WorkflowEngine`, injects the engine into an `ImpressManager`, and launches via `manager.start(pipeline_setups=[...])` inside a `try`/`finally` that calls `await flow.shutdown()`. The caller owns the engine end to end -- `ImpressManager` never creates or shuts it down.

### Step constants (state-machine constants in `small_molecule_binding.py`)

| Constant | Value | Meaning |
|---|---|---|
| `STEP_DONE` | 0 | pipeline complete |
| `STEP_RFD3` | 1 | backbone diffusion |
| `STEP_MPNN` | 2 | MPNN + PackMin refinement cycle |
| `STEP_FASTRELAX` | 3 | Rosetta FastRelax |
| `STEP_INTERFACE` | 4 | filter_shape (PyRosetta, gates fold prediction) |
| `STEP_AF2` | 5 | fold prediction — backed by Boltz-2 co-folding (constant name kept as `STEP_AF2` for compatibility; it no longer runs AlphaFold2) |
| `STEP_RETRY_SEQ` | 6 | internal: retry sequence prediction without backbone restart |

### Pipeline tasks and scripts

| Task (registered name) | Type | Script / Tool | Resource |
|---|---|---|---|
| `rfd3` | HPC | `scripts/rfd3.sh` (RFDiffusion3 via `apptainer exec`) | GPU |
| `analysis_backbone` | local | reads JSON metrics from `rfd3` output dir | CPU |
| `mpnn` | HPC | `scripts/mpnn.sh` → `mpnn_run.py` (LigandMPNN) | GPU when visible (LigandMPNN `run.py` selects CUDA if available) |
| `analysis_sequence` | local | parses every record in MPNN's `seqs/*.fa` output (LigandMPNN writes one file per input structure containing a template record plus `batch_size` designed candidates — not one candidate per file) and selects the highest-`overall_confidence` candidate | CPU |
| `packmin` | HPC | `scripts/packmin.sh` → `scripts/packmin.py` (PyRosetta pack+minimize) | CPU |
| `analysis_packmin` | local | reads `_packmin_score.json` from packmin output | CPU |
| `fastrelax` | HPC | `scripts/fastrelax.sh` → `scripts/fastrelax.py` (Rosetta FastRelax) | CPU |
| `analysis_fastrelax` | local | reads `.fasc` score file from fastrelax output | CPU |
| `filter_shape` | HPC | `scripts/filter_shape.sh` → `scripts/filter_shape.py` (PyRosetta shape complementarity) | CPU |
| `analysis_interface` | local | reads `shape_complementarity_values.txt` | CPU |
| `boltz` (dispatched from the `STEP_AF2` state, whose constant name is kept for compatibility) | HPC | `scripts/boltz.sh` (Boltz-2, pip-installed CLI, co-folds protein+ligand — no container) | GPU |
| `analysis_fold` | local | reads Boltz `confidence_*.json` files under `predictions/boltz_input/` | CPU |
| `filter_energy` | HPC | `scripts/filter_energy.sh` → `scripts/filter_energy.py` (ligand energy filter) | CPU |

### State-machine execution flow

The pipeline runs as a `while self.next_step != STEP_DONE` loop. After each stage, `run_adaptive_step()` calls `adaptive_decision()` to set `pipeline.next_step`.

```
STEP_RFD3  →  analysis_backbone  →  adaptive_decision()
STEP_MPNN  →  _run_refine_cycle():
                  for each cycle:
                      mpnn  →  analysis_sequence  →  adaptive_decision()
                      packmin  →  analysis_packmin  →  adaptive_decision()
STEP_FASTRELAX  →  analysis_fastrelax  →  adaptive_decision()
STEP_INTERFACE  →  analysis_interface  →  adaptive_decision()
STEP_AF2        →  analysis_fold       →  adaptive_decision()
```

After a successful fold, `adaptive_decision()` always returns to `STEP_RFD3` for the next backbone generation. The pipeline terminates when `max_tasks` ensemble entries have been accumulated or `STEP_DONE` is set.

### MPNN + PackMin inner refinement cycle

`_run_refine_cycle()` runs `num_refine_cycles` (default 3) iterations of MPNN→PackMin:
- **Cycle 0**: MPNN generates `mpnn_ensemble_size` (default 10) sequence candidates from `best_backbone_path`.
- **Cycles 1+**: MPNN generates a single candidate from the current `best_packed_pdb`.
- PackMin is skipped on the last cycle; the best-scoring packed PDB advances to FastRelax.
- If `analysis_sequence` triggers `STEP_RETRY_SEQ`, MPNN is re-run for the same cycle (up to 3 retries before escalating to `STEP_RFD3`).

### Adaptive decision logic

`adaptive_decision()` in `run_small_molecule_binding.py` uses ensemble history and pairwise similarity to decide next steps:

| Stage | Pass condition | Pass action | Fail action |
|---|---|---|---|
| `backbone` | no ligand clashes, `max_ca_deviation < threshold`, sufficient secondary structure | `STEP_MPNN` (with ensemble similarity gating) | `STEP_RFD3` |
| `sequence` | ensemble similarity check (sequence identity) | `STEP_MPNN` | `STEP_RETRY_SEQ` (up to 3x), then `STEP_RFD3` |
| `packmin` | always passes | `STEP_MPNN` | — |
| `fastrelax` | interaction energy, total score, fa_rep below thresholds | `STEP_INTERFACE` | `STEP_MPNN`, unless none of the failing metrics improved vs. the previous attempt on this backbone (see below), then `STEP_RFD3` |
| `interface` | shape complementarity `max_sc >= interface_min_sc` | `STEP_AF2` | `STEP_MPNN`, unless `max_sc` didn't improve vs. the previous attempt (see below), then `STEP_RFD3`; `STEP_RFD3` regardless after 5x (safety cap) |
| `fold` | Boltz `complex_plddt * 100 >= fold_min_plddt`, and (if set) `ligand_iptm >= fold_min_ligand_iptm` | sets `rfd3_input_pdb` for guided backbone → `STEP_RFD3` | clears `rfd3_input_pdb` → `STEP_RFD3` |

### fastrelax / interface non-improvement short-circuit

`fastrelax` and `interface` failures used to always retry via `STEP_MPNN` up to a flat 5x cap before escalating to `STEP_RFD3`. Real HPC data showed this was frequently wasteful: a backbone whose fastrelax metrics (some combination of `interact`/`total_score`/`fa_rep`) or interface shape complementarity are failing for backbone-level structural reasons (packing, energetics, surface complementarity) doesn't improve no matter which MPNN-designed sequence is tried — only regenerating the backbone (`STEP_RFD3`) can help, so burning through all 5 resequencing attempts wastes significant HPC time (confirmed: ~15-20 min per doomed backbone). Observed on a single real run (job `21913252`): three distinct failure-mode combinations across `p3`'s first three backbones (`interact`+`total_score`-only, `fa_rep`-only, and interface shape-complementarity), each flat/non-improving across every attempt, zero eventual recoveries.

Both branches now use `_stage_metrics_improving()` (small_molecule_binding.py) to compare the current failure's metrics against the previous attempt on the *same* backbone (tracked in `fastrelax_prev_metrics`/`interface_prev_metrics`, reset whenever a new backbone starts). A metric counts as "improved" if its gap to threshold shrank by more than 5% of the previous gap; metrics already passing on the previous attempt aren't considered. If **none** of the currently-failing metrics improved, the pipeline escalates straight to `STEP_RFD3` instead of retrying — effectively a retry cap of 1 (the very first attempt always gets one retry, since there's nothing to compare against yet; the second non-improving attempt escalates). The original 5x counter (`fastrelax_fail_count`/`interface_fail_count`) remains as an outer safety net.

### Ensemble-guided backbone feedback

After a successful fold prediction, `adaptive_decision()` computes CA-RMSD between the current Boltz model and all prior fold ensemble entries. If the selective average score (for structurally similar models) exceeds the overall average, the current Boltz model is fed back as `rfd3_input_pdb`.

RFD3 has no `scaffoldguided.*`-style CLI override (that was a leftover from an older RFDiffusion version and doesn't exist in RFD3 — the pipeline's `rfd3()` task no longer attempts one). Guidance is expressed entirely through RFD3's `InputSpecification` JSON, via **partial diffusion**: the `partial.input` field points at a real structure and `partial.partial_t` (Å of noise added before re-denoising; `rfd3_partial_t` kwarg, default `10.0`) controls how closely the result stays to it.

When `rfd3_input_pdb` is set, `rfd3()`:
1. Reads the ligand's literal residue name from `ligand_params`'s `NAME` record via `_ligand_resname_from_params()` — this is **not** always the params filename stem (e.g. `ALR.params`'s `NAME` is `A:R`, not `ALR`; the colon is a deliberate workaround for RFD3 misresolving the bare `"ALR"` literal — never hardcode or "clean up" this value).
2. Calls `_normalize_ligand_id()` to rewrite the Boltz model's ligand HETATM residue *name* (via gemmi, no coordinate transform — Boltz already places the ligand correctly relative to the protein it just co-folded) to match that literal, writing `{taskdir}/in/guided_scaffold.pdb`.
3. Calls `_normalize_ligand_atom_names()` to rewrite that same PDB's ligand *atom* names to the canonical `.params` names (see "Guided-RFD3 ligand atom-name mapping" below) — Boltz assigns its own arbitrary atom names during co-folding, unrelated to the params file, so this is a separate fix from step 2.
4. Calls `_write_guided_rfd3_json()` to copy the base `ALR_binder_design.json`'s `ligand`/`select_exposed`/`select_buried` fields verbatim (dropping `length` — RFD3's validator rejects it during partial diffusion, since length is inferred from the input structure) into a new spec with `input` pointed at the normalized PDB and `partial_t` set, writing `{taskdir}/in/guided_binder_design.json` — after first verifying every `select_exposed`/`select_buried` atom name is actually present in the normalized PDB.
5. Passes that guided JSON (instead of the base one) as `rfd3.sh`'s `inputs=` argument. If any of steps 2–4 fails (no ligand found in the Boltz model, no full atom-name mapping found, or the coverage check fails), falls back to the base, unguided JSON rather than erroring.

### Guided-RFD3 ligand atom-name mapping

Boltz-2's co-folded ligand output uses its own arbitrary atom names (e.g. `C41`, `O24`, ...) that have nothing to do with the canonical names in the ligand's `.params` file (e.g. `C18`, `O3`, ...). Since `select_exposed`/`select_buried` are copied verbatim from the base spec and are keyed by those canonical names, a guided PDB with unrenamed atoms fails RFD3's own input validation (`ComponentValidationError: Number of atoms must be a multiple of the requested names`) — this was the confirmed root cause of a real production run (job `21916521`) crashing all 4 pipeline instances on their first guided-feedback attempt.

`_infer_ligand_atom_mapping()` establishes the correspondence via element + heavy-atom-connectivity graph isomorphism (rdkit), ignoring bond order throughout (the `.params` format has none):
- **Reference graph**: heavy atoms + bonds parsed directly from the `.params` file's `ATOM`/`BOND` records (`_params_heavy_atom_graph()`) — exact, no perception needed. Reference *coordinates* come from the real, correctly-named structure the base spec's own `partial.input` already points at (`_resolve_reference_pdb_path()`) — no synthetic conformer is built.
- **Query graph**: the Boltz ligand's connectivity, perceived from 3D distances via `rdkit.Chem.rdDetermineBonds.DetermineConnectivity()` (Boltz's output carries no CONECT records for the ligand).
- **Isomorphism + tie-break**: `GetSubstructMatches()` enumerates every graph-valid atom correspondence; local topological symmetry (e.g. a sulfonate's three interchangeable terminal oxygens) can yield more than one. Each candidate is Kabsch-superposed (reusing `_kabsch_rmsd()`) against the reference coordinates, and the lowest-RMSD mapping wins — grounded in real geometry rather than an arbitrary tiebreak. When more than one isomorphism exists, the best-vs-next-best RMSD gap is logged.

This is **not a generic guarantee for every future ligand**: it's only provably safe for a ligand whose "sides" (whatever `select_exposed`/`select_buried` partition into) aren't themselves graph-isomorphic to each other — true for `ALR` (a monocyclic benzene-sulfonate ring isn't isomorphic to a fused naphthalene-sulfonate ring), but not checked automatically for `IND`/`RED`/`IAI` or any future ligand. Run `scripts/check_ligand_atom_mapping.py` against a new ligand's `.params` + reference PDB before trusting guided feedback with it.

`_write_guided_rfd3_json()` adds a final defensive check: before writing, it verifies every `select_exposed`/`select_buried` atom name is present in the (now atom-renamed) guided PDB, returning `False` (fail safe, fall back to unguided) rather than reproducing RFD3's rejection in a new form if not.

`scripts/check_ligand_atom_mapping.py` validates this mapping logic against real crash artifacts rather than synthetic test data: the job-`21916521` `guided_scaffold.pdb` files under `logs/p{1..4}/*_rfd3/in/`, with the committed `p1_in/ALR.params` + `p1_in/input_pdbs/scaffold-with-ALR.pdb` as ground truth. **Those crash artifacts are not committed** — `logs/` is gitignored — so on a fresh checkout every check skips and the tool reports `INCONCLUSIVE` (exit 2), not `PASS`. Pass `--base-path <completed run's output tree>` to actually exercise it. `scripts/validate_run.py`'s check 8 (`check_guided_ligand_atom_names`) regression-tests the same invariant against any completed run's output tree.

Ensemble similarity utilities (all in `small_molecule_binding.py`):
- `_ca_rmsd(path1, path2)` — Kabsch-aligned CA RMSD between two PDB files
- `_kabsch_rmsd(coords1, coords2)` — the underlying generic Kabsch-alignment RMSD, also reused by `_infer_ligand_atom_mapping()`'s isomorphism tie-break
- `_seq_identity(fasta1, fasta2)` — fraction matching residues over shorter sequence
- `_ensemble_selective_avg(current, prior, sim_fn, similar_if_low)` — returns `(overall_avg, selective_avg, has_data)` for scores of entries whose similarity is on the "similar" side of the mean pairwise similarity

**Both file readers behind these are memoised, and that is load-bearing, not an optimisation.**
`_ensemble_selective_avg()` calls `sim_fn` once per prior ensemble entry, so an uncached reader makes
every adaptive decision cost O(ensemble) blocking Lustre opens — and since `adaptive_decision()` runs
in the single manager process shared by all pipelines, that stalls the whole job, not one pipeline.
An uncached `_read_fasta_seq` is exactly what capped job `22534628` at 37% of baseline throughput
(see the 2026-09-30 revision row). `_parse_pdb_ca_coords` uses `@lru_cache(maxsize=4096)`;
`_read_fasta_seq` uses the module-level `_FASTA_SEQ_CACHE` dict, keyed on path alone — sound because
`taskcount` increments for every HPC task, so no output path is ever written twice. Negative results
are deliberately not cached, so a transiently missing file does not pin the failure for the run.
**If you add a new similarity metric, cache its reader the same way**, and size any `lru_cache` for
(ensemble entries × n_pipelines), not for one pipeline.

`adaptive_decision()`'s body (`_adaptive_decision_sync`) is entirely synchronous. The runner
therefore registers it as `flow.function_task(backend="local")`, a rhapsody
`ConcurrentExecutionBackend` over a `ThreadPoolExecutor`, rather than calling it on the event loop.
Keep it that way: run directly on the loop, any I/O it acquires blocks dispatch for every pipeline
at once. It must stay a **thread** pool, because the body mutates the live `pipeline.state`, and a
process pool would mutate a pickled copy.

### Quality thresholds (configurable)

| Kwarg | Default | Metric |
|---|---|---|
| `backbone_max_ca_deviation` | 2.0 | max CA deviation (Å) from target |
| `backbone_min_ss_fraction` | 0.2 | minimum helix+sheet fraction |
| `fastrelax_max_interact` | 0.0 | interaction energy (REU) |
| `fastrelax_max_total_score` | 0.0 | total Rosetta score (REU) |
| `fastrelax_max_fa_rep` | 150.0 | fa_rep repulsion energy (REU) |
| `interface_min_sc` | 0.5 | minimum shape complementarity score |
| `fold_min_plddt` | 70.0 | minimum Boltz `complex_plddt` (rescaled ×100, so this stays on the same 0–100 scale as the old AlphaFold2 pLDDT) |
| `fold_min_ligand_iptm` | `None` | minimum Boltz `ligand_iptm` (protein-ligand interface confidence, 0–1 scale); `None` disables this gate — a new capability plain AlphaFold2 couldn't provide since it never folded the ligand |
| `max_tasks` | 300 | maximum ensemble entries before stopping |

Also configurable, not a pass/fail threshold: `rfd3_partial_t` (default `10.0`, Å of noise added during RFD3 partial diffusion — see "Ensemble-guided backbone feedback" below).

The `PROD` config in `run_small_molecule_binding.py` overrides these class defaults at `PipelineSetup` construction (e.g. `backbone_max_ca_deviation=1.0`, `fastrelax_max_interact=-8.0`, `fold_min_plddt=75.0`).

### Output directory structure

Each HPC task creates its working directory as `{base_path}/{name}/{taskcount}_{taskname}/in` and `.../out`. `taskcount` is a flat integer incremented for every HPC task (local analysis tasks do not increment it).

```
{base_path}/
  {name}_in/           # pipeline inputs (ALR_binder_design.json, ligand .params, etc.)
  {name}/
    1_rfd3/out/          # RFDiffusion3 outputs (.cif.gz + .json per model)
    2_mpnn/out/          # LigandMPNN outputs (seqs/*.fa, packed/*.pdb)
    3_packmin/out/       # packed+minimized PDB + _packmin_score.json
    4_mpnn/out/          # cycle 1 MPNN ...
    ...
    N_fastrelax/out/     # FastRelax PDB + .fasc score file
    N+1_filter_shape/out/
    N+2_boltz/out/boltz_results_boltz_input/predictions/boltz_input/  # Boltz-2 PDBs + confidence_*.json
                                                                       # (boltz nests its own out_dir/boltz_results_<stem>/ automatically)
```

Mock mode (`mock=True`, `mock.py`) mirrors this same `{base_path}/{name}/{taskcount}_{taskname}/...` layout with hardcoded fixture outputs, so the two modes stay directly comparable.

MPNN copies the input backbone to a short fixed filename (`binder.cif.gz` or `binder.<ext>`) in `{taskdir}/in/` each cycle to avoid 255-character filename limits in fold-prediction result archives.

### Inter-step state passing

Steps communicate via `self.state`:

**Set by HPC task wrappers / local analysis tasks:**
- `best_backbone_path` — path to best `.cif.gz` from `rfd3` (set by `analysis_backbone`)
- `best_packed_pdb` — path to best packed PDB (set by `analysis_sequence`, updated by `packmin`)
- `last_seq_fasta` — path to best FASTA from MPNN (set by `analysis_sequence`)
- `best_fold_model` — path to best Boltz-2 co-folded PDB (protein+ligand; set by `analysis_fold`)
- `last_analysis_step` — `'backbone'` / `'sequence'` / `'packmin'` / `'fastrelax'` / `'interface'` / `'fold'`
- `last_analysis_metrics` — dict with `pass` bool and step-specific score fields
- `ensemble` — list of `(etype, score, input_path, output_path)` tuples

**Set by `adaptive_decision`:**
- `rfd3_input_pdb` — if set, the Boltz co-folded model `rfd3()` normalizes and feeds into RFD3 as partial-diffusion `input` (see "Ensemble-guided backbone feedback")
- `seq_retry_count` — retry counter for sequence stage (reset on new backbone or successful sequence)
- `interface_fail_count` — retry counter for interface stage (reset on pass or after 5 failures)
- `fastrelax_prev_metrics` / `interface_prev_metrics` — the previous attempt's `last_analysis_metrics` for the current backbone, used by the non-improvement short-circuit (see above); `None` when there's no prior attempt to compare against, reset on pass or new backbone

**Set at run start (`setdefault`):**
- `ensemble` — initialized to `[]`
- `rfd3_input_pdb` — initialized to `None`
- `seq_retry_count` — initialized to `0`
- `last_seq_fasta` — initialized to `None`
- `fastrelax_prev_metrics` / `interface_prev_metrics` — initialized to `None`

### Execution backends

`run_small_molecule_binding.py` builds one `WorkflowEngine` over two named rhapsody backends, and asyncflow routes each task by name:

- **`compute`** (the default): `DragonExecutionBackend` for HPC production runs (`IMPRESS_BACKEND=dragon`, the default), or `ConcurrentExecutionBackend(ProcessPoolExecutor())` with any other value, for single-node/non-Dragon development. **Every stage that runs an external tool** goes here: `rfd3`, `mpnn`, `packmin`, `fastrelax`, `filter_shape`, `boltz`, and `filter_energy`.
- **`local`**: `ConcurrentExecutionBackend(ThreadPoolExecutor(n_pipelines))`, for Python callbacks that must see the live pipeline objects. Today that is only `adaptive_decision`.

Only the six pure-Python `analysis_*` stages remain `local_task=True`. They run in-process and are timed by `_timed_local`.

Each tool stage's coroutine does the in-process bookkeeping (`taskcount`, task dirs, input prep) and **returns the command**; the backend runs it. Output still lands in `{taskdir}/<stage>.log`, via `scripts/run_logged.sh`.

**Thread caps are per task, not process-wide.** `_tool_task_description()` supplies `OMP_NUM_THREADS` and friends, plus `OMP_WAIT_POLICY=PASSIVE`, as a `task_description` default on **every** tool stage: `ROSETTA_THREADS=1` (packmin/fastrelax/filter_shape/filter_energy), `MPNN_THREADS=4`, `GPU_TOOL_THREADS=8` (rfd3, boltz). `rfd3.sh` runs `apptainer exec` without `--cleanenv`, so the caps reach the container. A new tool stage must get one too: uncapped `boltz` took ~30 cores of the primary on `22670942`. The two backends treat `env` differently, so only the active backend's key is sent:
- The concurrent backend's `env` *replaces* the environment, so it is merged over `os.environ`.
- Dragon's `process_template.env` is *merged* into the target node's environment by local services, so only the delta is sent.

Do not reintroduce caps via the runner's `os.environ`: a Dragon task on another node never sees it.

GPU placement goes through the backend's per-task interface, but the device is chosen here, because Dragon Batch does no GPU accounting. A process task with no `gpu_affinity` is given every GPU on its node (`CUDA_VISIBLE_DEVICES=0,1,2,3`), and every GPU tool then runs on GPU 0. On `22684833`, GPU 0 averaged ~50% and GPUs 1–3 exactly 0%, so an older "mean GPU ~10–15%" figure is one busy GPU averaged over four. The runner now gives pipeline `pN` one device, `gpus[(N-1) % len(gpus)]` (logged as a `[GPU]` line). `_tool_task_description(..., gpu=True)` passes it to mpnn/rfd3/boltz:
- **Dragon:** `process_template["policy"] = Policy(gpu_affinity=[g])`. A `CUDA_VISIBLE_DEVICES` in the template env does **not** work under Dragon, because local services overwrites it from the policy layout.
- **Concurrent:** `CUDA_VISIBLE_DEVICES` in the env.

Batch still picks the node, so two same-numbered pipelines can share a GPU. See BACKLOG item 10, `plans/2026-10-05-gpu0-only.md` and `plans/upstream/dragon-batch-no-gpu-accounting.md`.

**Multi-node runs need `WORK_DIR` (and the tool paths) exported from `~/.bashrc`.** Under `dragon -w ssh`, a task on a remote node sees only Dragon's `BASE_ENV_VARNAMES` plus what the ssh login shell's `~/.bashrc` exports, never the batch script's environment. `rfd3.sh` binds `$WORK_DIR` into the container and silently drops the bind if it is unset.

**Reading node load under Dragon.** Dragon Batch's pool workers (32 per node, hardcoded `num_cpus // 2`) and its managers busy-spin when idle, about 21–25 cores per node, whatever the workload. A node's CPULoad is therefore not a measure of tool work. See `plans/upstream/dragon-batch-idle-spin.md`.

**Reading telemetry.** Task events carry no `node_id`, and Started/Completed/Failed are labelled with the default backend's name even for `local` tasks; only TaskQueued/TaskSubmitted are correct. To find where a task ran, sample `/proc` on each node. See `plans/upstream/asyncflow-telemetry-backend-and-node-id.md`.

### Pipeline inputs

Each pipeline instance (named e.g. `p1`) expects a `{name}_in/` directory containing:
- `ALR_binder_design.json` — RFDiffusion3 input spec (contig, ligand, scaffold args)
- `<ligand_name>.params` — Rosetta ligand params file (default `ALR.params`)
- `<ligand_name>.smiles` — ligand SMILES string, read by the `boltz` task to build its co-folding input; derive it once with `scripts/derive_ligand_smiles.py <ligand>.params <reference>.pdb` (RDKit bond-order perception from the params file's exact connectivity + the reference structure's 3D coordinates — there is no SMILES in a Rosetta `.params` file itself)
- Optionally `common_filenames.txt` — used by `filter_energy` for cross-filtering

`rdkit` is a runtime dependency (installed by `delta_env_setup.sh`'s Step 10, pinned `2024.9.6`) used both by the offline `derive_ligand_smiles.py` tool above and, per-cycle, by `rfd3()`'s guided-backbone-feedback atom-name mapping (see "Guided-RFD3 ligand atom-name mapping" above). `scripts/check_ligand_atom_mapping.py` and `scripts/validate_run.py` (check 8) validate that mapping against real fixtures/completed runs, respectively.
