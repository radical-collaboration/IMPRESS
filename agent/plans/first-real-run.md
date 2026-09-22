# Stub — the first real campaign on Delta

**Status:** blocked on a person. Backlog items A1, A2, A3.

## Problem

The real path has never executed. Everything asserted about RFdiffusion3, LigandMPNN, PyRosetta and
Boltz is registration, validation, type-checking and dry-run. The adapters invoke real binaries and
fail loudly when their environment is absent, but no scientific code has run through this system.

## What has to happen first, in order

1. **Fill in `ligand_smiles`** in `campaigns/delta-small-molecule-smoke.yaml` (and the full campaign).
   It is marked `REQUIRED` and defaults to `""`, which means Boltz models no ligand and nothing
   complains. Set `contig` and `ligand_resname` to match the target while there.
2. **`impress-a preflight`** on a login node. Checks `FOUNDRY_SIF_PATH`, `MPNN_DIR`, `BOLTZ_CACHE`,
   `apptainer` and `boltz` on PATH, and `import pyrosetta` in a subprocess.
3. **Confirm three arguments** against the installed CLIs — the seed flags for LigandMPNN and Boltz,
   RFD3's `seed` config key, and whether `--number_of_batches` is the right knob for `num_seqs`. All
   are marked at their call sites. Getting a seed flag wrong is silent: replicas stop being
   independent draws and nothing reports it.
4. **Smoke first** — `sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml`.
   One cycle, one lineage.

## What to check on the first run

- The `graphs` provenance names the real tools, not `mock_*`. This is the bug that made the smoke
  test necessary in the first place.
- `jobs/ledger.jsonl` shows one submitted → done run with an outcome payload.
- Artifacts exist under `$SCRATCH`, not `/tmp` — the launcher `cd`s to a shared per-job directory and
  adapters inherit it as CWD. A path under the system temp dir means the workdir plumbing regressed,
  and under Dragon multi-node it will surface as a missing file deep inside a science tool.
- The front carries `total_score`, `shape_complementarity`, `complex_plddt`, `ligand_iptm`.
- Estimated vs actual cost per tool — the cost models are literature guesses and gate 5 refuses
  graphs against them. Record the real numbers; this is the only way that gets calibrated.

Then, with `replicas: 4`, confirm the four `DesignNode`s carry **different** metrics. That is the one
check proving the seed work did anything, and it is the invariant most likely to be silently wrong.
