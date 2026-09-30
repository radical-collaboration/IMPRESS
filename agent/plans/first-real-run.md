# Stub — the first real campaign on Delta

**Status:** submitted, and it got one stage in. Job 22536706 ran the smoke campaign on
2026-09-29: `rfd3_design` succeeded, `ligandmpnn_design` failed, and the campaign then hung until
the allocation ended (backlog G6). Steps 1-3 below were already DONE for the ALR target. A4 is
closed by what that run wrote; A1 stays open, because no campaign has *completed*. What the run
produced, and what it cost us to learn, is recorded at the bottom.

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

## What the first attempt actually produced (job 22536706)

Answered, off roughly three minutes of real rfd3:

- **The Hydra contract works.** rfd3 ran inside the container, exited 0 and wrote real output. A3
  was verified by reading the CLI's source; it is now verified by execution.
- **The output shape is `*_model_*.cif.gz` beside `*_model_*.json`**, as A4 predicted from the
  reference pipeline. What A4 did *not* predict: our `*.cif.gz` glob was selecting the wrong one of
  them. Trajectories are `.cif.gz` too and `denoised` sorts first, so the backbone handed downstream
  was a 5.7 MB multi-frame trajectory rather than the 19 KB design. Fixed by discovering through the
  sidecar JSON. Full evidence in backlog A4.
- **`dump_trajectories` was still `True`** on that run - it predates the G3 flip - which is the only
  reason the bug was visible at all. The current default hides it.

Still unanswered, and all of it downstream of the one stage that ran: the ledger outcome, artifacts
under `$SCRATCH` (rfd3's landed there correctly), the front's four objectives, the thread-cap lines,
per-tool cost against estimate, and the `replicas: 4` independence check.

**What it cost to learn.** `ligandmpnn_design` failed and we do not know why: its stderr went with
the dropped monitor-loop sweep (backlog G6), and its work dir is empty. The campaign then held the
allocation at `inflight=1` doing nothing until the wall clock ended it. Both halves of that are
now bounded on our side only - `SubprocessError` is pickle-safe, so the *next* failure should
arrive as a FAILED with its stderr attached, but nothing yet bounds a single run's wall clock, so
watch the heartbeat and `scancel` on a stuck `inflight`.

**Before resubmitting:** the rfd3 selection fix and the G6 fix are both code-only and both land
before the next allocation is worth spending. Neither has executed on Delta.
