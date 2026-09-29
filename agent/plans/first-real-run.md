# Stub — the first real campaign on Delta

**Status:** blocked on a person actually submitting the job. Steps 1-3 below are DONE for the ALR
target as of this session (verified directly against the installed toolkits on Delta - see backlog
A2, A3, A5). Backlog items A1 (no campaign has executed) and A4 (rfd3 output parsing needs
confirming on a real run) remain.

## Problem

The real path has never executed. Everything asserted about RFdiffusion3, LigandMPNN, PyRosetta and
Boltz is registration, validation, type-checking and dry-run. The adapters invoke real binaries and
fail loudly when their environment is absent, but no scientific code has run through this system.

## What has to happen first, in order

1. **DONE for ALR.** `ligand_smiles`, `contig`/`input_spec_path`, and the LigandMPNN
   `fixed_residues`/Rosetta `ligand_params_path` targets are all filled in on both Delta campaigns,
   borrowed from the original IMPRESS project's small-molecule-binding benchmark (see
   `campaigns/data/alr/`). `_check_ligand_smiles` (`cli/__init__.py`) now fails fast for any *future*
   target that leaves `ligand_smiles` blank, instead of silently modeling no ligand.
2. **`impress-a preflight`** on a login node. Checks `FOUNDRY_SIF_PATH`, `MPNN_DIR`, `BOLTZ_CACHE`,
   `apptainer` and `boltz` on PATH, `import pyrosetta` in a subprocess, and (as of this session)
   `ligand_smiles`. Confirmed passing (except the pre-existing, unrelated `pyrosetta` subprocess
   check, which times out on this login node) for `campaigns/delta-small-molecule-smoke.yaml`.
3. **DONE.** Three arguments were confirmed directly against the installed CLIs this session:
   LigandMPNN's `--seed`/`--number_of_batches` (correct as originally written), Boltz's `--seed`
   (correct), and RFD3's contract (was **wrong**, not just unverified - the whole invocation has
   been rewritten to the real Hydra `key=value` contract; see backlog A3 and `toolkits/rfd3/SKILL.md`).
   Also found in the same pass and fixed: `boltz_predict` was missing the required `--no_kernels`
   flag.
3a. **Re-run `scripts/delta_env_setup.sh` step 11 on a login node** if `impress-a preflight` reports
   `boltz CCD cache` as unmarked. The marker is written only on a *successful* warm-up, and the
   compute nodes have no egress to repair a half-extracted cache themselves (backlog C8).

4. **Smoke first** — `sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml`.
   One cycle, one lineage. Both Delta campaign YAMLs now also set
   `backend_startup_timeout_s: 600` so a Dragon-backend-construction hang (job 22318678; see
   `docs/limitations.md`) fails within minutes instead of consuming the whole allocation.

## What to check on the first run

- `rfd3_design`'s output filenames under `out_dir` match what `RFD3DesignAgent` globs for
  (`*.cif.gz`) - the Hydra contract rewrite is verified against the real CLI's source, but the exact
  output shape (`dump_prediction_metadata_json`/`output_full_json`) was not re-verified against a
  real run (backlog A4).
- The `graphs` provenance names the real tools, not `mock_*`. This is the bug that made the smoke
  test necessary in the first place.
- `jobs/ledger.jsonl` shows one submitted → done run with an outcome payload.
- Artifacts exist under `$SCRATCH`, not `/tmp` — the launcher `cd`s to a shared per-job directory and
  adapters inherit it as CWD. A path under the system temp dir means the workdir plumbing regressed,
  and under Dragon multi-node it will surface as a missing file deep inside a science tool.
- The front carries `total_score`, `shape_complementarity`, `complex_plddt`, `ligand_iptm`.
- The `thread cap` lines at the head of the campaign log divide the *allocation*, not the node. On
  a partial-node allocation `OMP_NUM_THREADS` should be well under the node's core count; if it
  equals it, `sched_getaffinity` is not seeing the cgroup and the Rosetta stages will fight
  (backlog C9).
- `out_dir` holds no `traj/` output and is ~1 MB per design, not ~12 (backlog G3).
- Estimated vs actual cost per tool — the cost models are literature guesses and gate 5 refuses
  graphs against them. Record the real numbers; this is the only way that gets calibrated.

Then, with `replicas: 4`, confirm the four `DesignNode`s carry **different** metrics. That is the one
check proving the seed work did anything, and it is the invariant most likely to be silently wrong.
