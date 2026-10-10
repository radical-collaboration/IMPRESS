# Stub — the first real campaign on Delta

**Status: DONE — a campaign has completed.** Job 22692304 (2026-10-06) ran all six stages to
`6/6 tasks ok` in 2m53s, admitted on the first attempt, every gate passing, terminating with a
one-node front and all four objectives valued. This stub's question is answered; what it asked to
check on the first run is recorded at the bottom, including the items it got wrong. The remaining
unexercised ground moved to backlog A10 (`replicas > 1`) and A11 (cost-model variance).

**Previously:** five of six stages executed. Job 22684607 (2026-10-05) ran
`rfd3_design -> ligandmpnn_design -> packmin -> fastrelax -> filter_shape` to `5/5 tasks ok` in
3m44s. `boltz_predict` has never run: it is truncated off the chain by a budget correction, not by
a failure (backlog A7). No campaign has produced a front. Earlier history below.

**Previously:** submitted twice, one stage in both times. Job 22536706 (2026-09-29) ran `rfd3_design`
to success, then hung on a LigandMPNN failure whose stderr was lost (backlog G6). Job 22669509
(2026-10-04) re-ran it with the G6 and rfd3-selection fixes in place: both held, LigandMPNN failed
*loudly* this time, and its stderr showed it cannot import at all under this venv's numpy (A6).
Steps 1-3 below were already DONE for the ALR target. A4 is closed by what the first run wrote; A1
stays open, because no campaign has *completed*. Both runs are recorded at the bottom.

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
- Artifacts exist under `$WORK_DIR`, not `/tmp` — the launcher `cd`s to a shared per-job directory and
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
under `$WORK_DIR` (rfd3's landed there correctly), the front's four objectives, the thread-cap lines,
per-tool cost against estimate, and the `replicas: 4` independence check.

**What it cost to learn.** `ligandmpnn_design` failed and we do not know why: its stderr went with
the dropped monitor-loop sweep (backlog G6), and its work dir is empty. The campaign then held the
allocation at `inflight=1` doing nothing until the wall clock ended it. Both halves of that are
now bounded on our side only - `SubprocessError` is pickle-safe, so the *next* failure should
arrive as a FAILED with its stderr attached, but nothing yet bounds a single run's wall clock, so
watch the heartbeat and `scancel` on a stuck `inflight`.

**Before resubmitting:** the rfd3 selection fix and the G6 fix are both code-only and both land
before the next allocation is worth spending. Neither has executed on Delta.

## What the second attempt produced (job 22669509)

Both of those fixes executed, and both held.

- **G6 holds.** `ligandmpnn_design` reached `FAILED` with its full stderr attached. No `Critical
  error in monitor loop`, no hang: the executor reaped the run, the ledger took a `failed` outcome
  with a complete payload, the campaign terminated on `max_cycles=1` and Dragon shut down in 1.5s.
  7m28s of campaign inside a 9m35s job.
- **The rfd3 selection fix holds.** `out_dir` held exactly `ALR_binder_design_partial_0_model_0.cif.gz`
  (19,697 B) and its `.json`; `backbone_0.pdb` is **53,784 B**, the real single-model design, against
  5.7 MB of trajectory last time. `num_models=1`, `ss_fraction=0.847` measured on one structure, both
  QC gates pass. Caveat worth stating: `dump_trajectories=False` was in effect, so rfd3 wrote no
  trajectories at all - the adversarial case is covered by the unit test, not by this run.
- **Cost:** 0.25 GPU-h recorded for rfd3 against a 0.5 estimate. The first real number against gate
  5's literature guesses.
- Downstream stages all took `DependencyFailureError` and ran nothing, which is correct.

**What it bought.** LigandMPNN's recovered stderr - the thing job 22536706 destroyed - showed it
dies in `run.py`'s module-level imports: `ml_collections` missing, then `np.int` removed in numpy
1.24. See backlog A6. That also disproved the standing theory that the trajectory had killed it: it
got the right backbone this time and failed anyway, for an unrelated reason.

**Still unanswered**, unchanged from the first attempt and all downstream of stage 2: the four
objectives on a front, artifacts from the Rosetta and Boltz stages, per-tool cost against estimate,
and the `replicas: 4` independence check.

**Before resubmitting again:** run `impress-a preflight` and confirm `ligandmpnn imports` reads
`[ok  ]`. A `[warn]` is a timeout, not a pass - run the shim by hand against `$MPNN_DIR` with
`--help` and require exit 0 before spending a queue slot.

## What the NVMe migration produced (job 22684607)

Same allocation as 22675512 - 1 node, `gpuA100x4-interactive`, 1h - with storage as the only
changed variable, so the two read directly against each other.

| Stage | NVMe | HDD baseline |
|---|---|---|
| `rfd3_design` | 145.7s | 137.2s (unchanged - GPU-bound, not read-bound) |
| `ligandmpnn_design` | **18.1s** | 292.6s |
| `packmin` | **15.9s** | could not finish `import pyrosetta` in 300s |
| `fastrelax` | **25.9s** | never ran |
| `filter_shape` | **10.2s** | never ran |

Campaign 13m42s → 3m44s. First real metrics from the Rosetta stages:

```
rfd3_design        pass   ss_fraction 0.824
ligandmpnn_design  pass   overall_confidence 0.525, ligand_confidence 0.496
packmin            FAIL   total_score +145.3   (gate was <= 0.0 - the gate was wrong)
fastrelax          pass   total_score -322.6, fa_rep 114.1
filter_shape       FAIL   shape_complementarity 0.524  (gate >= 0.55 - a genuine near-miss)
```

**What this run invalidated.** The plan going in was to raise the three Rosetta walltimes to
1800/3600/1200, justified by a 533.8s PyRosetta startup measured on HDD. Every one of those numbers
would have been wrong: measured on NVMe, packmin needs 15.9s against its existing 300s. The
walltimes were never the defect. Gating the change on this test is the only reason that did not
ship.

**Still unanswered**, and all of it downstream of the budget correction that drops boltz: the four
objectives on a front, `boltz_predict` executing at all, per-tool cost for boltz, and the
`replicas: 4` independence check.

**Before the next submission:** confirm the six-stage chain composes with no interlock rejection
(simulate the admission path locally - no allocation needed), and expect `boltz_predict` to run for
the first time.

## The first completed campaign (job 22692304)

```
reaped r0001: 6/6 tasks ok   cost={'gpu_hours': 0.27, 'cpu_hours': 0.06}
terminated: {"reason": "max_cycles=1 reached", "cycles": 1, "front": ["n000001-4101"]}
```

Admitted on `r0001` - the first attempt - with `rejected: None` and
`unproducible_objectives: []`. The two runs before it needed four attempts and lost a stage.

| stage | duration | QC | metrics |
|---|---|---|---|
| `rfd3_design` | 45.0s | pass | `ss_fraction` 0.827 |
| `ligandmpnn_design` | 14.6s | pass | `overall_confidence` 0.448, `ligand_confidence` 0.424 |
| `packmin` | 15.2s | pass | `total_score` +14.8 |
| `fastrelax` | 22.4s | pass | `total_score` -272.0, `fa_rep` 109.4 |
| `filter_shape` | 10.0s | pass | `shape_complementarity` 0.591 |
| `boltz_predict` | 57.8s | pass | `complex_plddt` 0.507, `ligand_iptm` 0.752 |

The node is `suspect`, not `pass`: `executor.py:245` marks a provisional composition pattern, and
it is still rankable. The trust ledger recorded one `clean` run; promotion needs three.

### Against this stub's own checklist

- **`graphs` provenance names the real tools** - yes, all six.
- **`jobs/ledger.jsonl` shows submitted → done with an outcome payload** - yes, `state: done`.
- **Artifacts under the shared filesystem, not `/tmp`** - yes, under `$WORK_DIR` on NVMe.
- **The front carries `total_score`, `shape_complementarity`, `complex_plddt`, `ligand_iptm`** -
  yes, all four, and the node is on the front.
- **Estimated vs actual cost per tool** - measured for all six and the specs corrected. This was
  the checklist item that mattered most and nobody expected: the literature guesses were 6-69x
  over, which is not harmless, because gate 5 and the untrusted-pattern cap REFUSE graphs against
  them. Two runs were spent on chains that had `boltz_predict` truncated off to fit a cap that
  only existed because the numbers were wrong.
- **`out_dir` holds no `traj/` output** - yes, `dump_trajectories=False`.
- **Thread caps divide the allocation** - `OMP_NUM_THREADS 32` on a 64-core node, correct.

### What this stub asked for and got wrong

It said to check that `rfd3_design`'s outputs "match what `RFD3DesignAgent` globs for
(`*.cif.gz`)". They did match, and the glob was still wrong - it was selecting a trajectory. A
checklist that asks whether the code does what it says cannot catch the code saying the wrong
thing; reading the real `out_dir` is what caught it.

It also never asked where any of this was being read from, which turned out to be the single
largest cost in the system (533.8s of PyRosetta startup off HDD).

### Still not done

`replicas: 4` (backlog A10) - the four-lineage independence check this stub calls the invariant
most likely to be silently wrong. It does **not** fit the untrusted-pattern cap today: four
lineages estimate 0.68 gpu-h against 0.60, so the correction would silently shrink it to three.
Running the smoke campaign three times promotes the pattern and removes the cap; at ~3 minutes a
run that is the cheapest route.
