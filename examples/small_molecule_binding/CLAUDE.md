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

- **`run_small_molecule_binding.py`** — entry point. Defines the `RunConfig` dataclass and two named instances (`PROD`, `TEST`); selects between them via `IMPRESS_TEST_MODE`; defines the `adaptive_decision()` callback; creates an `ImpressManager` and launches via `manager.start(pipeline_setups=[...])`.

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
| `mpnn` | HPC | `scripts/mpnn.sh` → `mpnn_run.py` (LigandMPNN) | CPU |
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

`scripts/check_ligand_atom_mapping.py` validates this mapping logic against real fixtures already in the repo (the job-`21916521` crash-artifact `guided_scaffold.pdb` files under `logs/p{1..4}/*_rfd3/in/`, plus `p1_in/ALR.params` + `p1_in/input_pdbs/scaffold-with-ALR.pdb` as ground truth) — not synthetic test data. `scripts/validate_run.py`'s check 8 (`check_guided_ligand_atom_names`) regression-tests the same invariant against any completed run's output tree.

Ensemble similarity utilities (all in `small_molecule_binding.py`):
- `_ca_rmsd(path1, path2)` — Kabsch-aligned CA RMSD between two PDB files
- `_kabsch_rmsd(coords1, coords2)` — the underlying generic Kabsch-alignment RMSD, also reused by `_infer_ligand_atom_mapping()`'s isomorphism tie-break
- `_seq_identity(fasta1, fasta2)` — fraction matching residues over shorter sequence
- `_ensemble_selective_avg(current, prior, sim_fn, similar_if_low)` — returns `(overall_avg, selective_avg, has_data)` for scores of entries whose similarity is on the "similar" side of the mean pairwise similarity

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

The `PROD` config in `run_small_molecule_binding.py` overrides these class defaults at `PipelineSetup` construction (e.g. `backbone_max_ca_deviation=1.0`, `fastrelax_max_interact=-8.0`, `fold_min_plddt=75.0`). The `TEST` config sets inert thresholds (everything passes) and `max_tasks=10` for integration testing.

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

`run_small_molecule_binding.py` uses `DragonExecutionBackend` for HPC production runs. `LocalExecutionBackend(ProcessPoolExecutor())` can be swapped in for local testing.

### Pipeline inputs

Each pipeline instance (named e.g. `p1`) expects a `{name}_in/` directory containing:
- `ALR_binder_design.json` — RFDiffusion3 input spec (contig, ligand, scaffold args)
- `<ligand_name>.params` — Rosetta ligand params file (default `ALR.params`)
- `<ligand_name>.smiles` — ligand SMILES string, read by the `boltz` task to build its co-folding input; derive it once with `scripts/derive_ligand_smiles.py <ligand>.params <reference>.pdb` (RDKit bond-order perception from the params file's exact connectivity + the reference structure's 3D coordinates — there is no SMILES in a Rosetta `.params` file itself)
- Optionally `common_filenames.txt` — used by `filter_energy` for cross-filtering

`rdkit` is a runtime dependency (installed by `delta_env_setup.sh`'s Step 10, pinned `2024.9.6`) used both by the offline `derive_ligand_smiles.py` tool above and, per-cycle, by `rfd3()`'s guided-backbone-feedback atom-name mapping (see "Guided-RFD3 ligand atom-name mapping" above). `scripts/check_ligand_atom_mapping.py` and `scripts/validate_run.py` (check 8) validate that mapping against real fixtures/completed runs, respectively.
