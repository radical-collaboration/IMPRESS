# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

This directory is an **example workflow** within the larger [IMPRESS framework](https://github.com/radical-collaboration/IMPRESS) (Integrated Machine-learning for PRotEin Structures at Scale). IMPRESS is an HPC framework for protein inverse design using Foundation Models.

The framework package lives at `../../` (two levels up). Install it with:
```shell
cd ../../
pip install .
```

## Running the Pipeline

```shell
python run_discontinuous_scaffolds.py
```

Before running on HPC, edit the path constants at the top of `run_discontinuous_scaffolds.py` (`SCRIPTS_PATH`, `FOUNDRY_SIF_PATH`, `MPNN_DIR`, `RFD_INPUT_FILEPATH`, `ISLAND_COUNTS_CSV`, `MCSA_PDB_DIR`, etc.) to match the target system. LMPNN JSONs (`lmpnn_pdb_multi_json`, `lmpnn_fixed_res_json`) are auto-generated from `rfd_input_filepath` by `generate_lmpnn_jsons()` at pipeline init and do not need to be set manually.

## Architecture

### Two-file structure

- **`discontinuous_scaffolds.py`** — defines `DiscontinuousScaffoldsPipeline(ImpressBasePipeline)`, the `_identify_passing_models()` helper, the `generate_lmpnn_jsons()` function (auto-generates LMPNN batch and fixed-residue JSONs from the RFD input at pipeline init), and all step constants. All eight pipeline steps plus three local analysis-check tasks are registered via `@self.auto_register_task()` inside `register_pipeline_tasks()`. The `run()` method drives a linear three-stage execution flow with an adaptive checkpoint after each stage.

- **`run_discontinuous_scaffolds.py`** — entry point. Sets path/parameter constants, threshold constants, defines the `adaptive_decision()` callback and its helper functions (`_filter_json_by_models`, `_filter_rfd_json_by_models`, `_create_filtered_seqs_dir`, `_next_branch_id`, `_shared_pipeline_kwargs`), creates an `ImpressManager`, and launches via `manager.start(pipeline_setups=[...])`.

### Eight pipeline steps (state-machine constants in `discontinuous_scaffolds.py`)

| Constant | Value | Tool | Resource |
|---|---|---|---|
| `STEP_BACKBONE_GEN` | 1 | RFDiffusion3 via `apptainer exec` | GPU |
| `STEP_BACKBONE_POST` | 2 | `cif_to_pdb.py` | CPU |
| `STEP_BACKBONE_ANALYSIS` | 3 | `analysis_backbone.py` + `plot_backbone_analysis.py` | CPU |
| `STEP_SEQ_PRED` | 4 | LigandMPNN `run.py` | CPU |
| `STEP_SEQ_POST` | 5 | `split_seqs.py` | CPU |
| `STEP_SEQ_ANALYSIS` | 6 | `analysis_sequence.py` + `plot_sequence_analysis.py` | CPU |
| `STEP_FOLD_PRED` | 7 | Chai-lab `chai_batch.py` | GPU |
| `STEP_ANALYSIS` | 8 | `analysis.py` + `plot_campaign.py` | CPU | computes `motif_rmsd` and anchor residue/sequence classification per Chai-1 output |

### Three-stage execution flow with adaptive checkpoints

The eight steps are grouped into three process stages. After each stage a local analysis-check task reads the output CSV and classifies each binding motif model as passing or failing against the configured thresholds. Then `run_adaptive_step()` calls `adaptive_decision()`.

```
Backbone stage (steps 1–3)  →  check_backbone_results()  →  adaptive_decision()
Sequence stage (steps 4–6)  →  check_seq_results()        →  adaptive_decision()
Fold stage     (steps 7–8)  →  check_fold_results()        →  adaptive_decision()
```

`adaptive_decision()` reads `pipeline.state['last_analysis_step']` to determine which stage just completed, then sets `pipeline.next_step`:
- `STEP_SEQ_PRED` — continue to the sequence stage (after backbone adaptive)
- `STEP_FOLD_PRED` — continue to the fold stage (after sequence adaptive)
- `STEP_DONE` — terminate the current pipeline (all models failed, or fold stage complete)

`check_fold_results()` reads the final analysis CSV, finds each model's best fold row (lowest `motif_rmsd`), and classifies models against `rmsd_threshold`. It sets `best_fold` (dict of `{model_name: {motif_rmsd, run_dir, seed, chai1_model_idx, anchor_residues, anchor_sequences, anchor_ref_residues}}`), `passing_fold_models`, and `failing_fold_models` in `pipeline.state`. The anchor fields come from the new anchor classification columns written by `analysis.py`.

### Adaptive branching for failing models

When a model fails the threshold battery for the current stage, `adaptive_decision()`:
1. Filters the **current pipeline's** downstream inputs to only the passing models (updated LMPNN JSONs and `rfd_input_filepath` after backbone; filtered `seqs_split_dir` symlink directory after sequence).
2. Spawns a **branch pipeline** for the failing models, starting at the stage where they failed, via `pipeline.submit_child_pipeline_request(...)`.

**Backbone branches** receive a `rfd_input_filepath` filtered to the failing models via `_filter_rfd_json_by_models()`, which also rewrites any relative `"input"` paths to absolute paths.

**Sequence branches** receive filtered LMPNN JSONs and a symlink `seqs_split_dir`.

**Fold branches** (redesign scaffold) are spawned when models fail the `rmsd_threshold` after folding. `adaptive_decision()`:
1. Serializes `pipeline.state['best_fold']` to `{base}/{branch_id}/best_fold.json`.
2. Runs `scripts/create_redesign.py` to produce `redesign.json` and per-model `redesign_scaffold.cif` files. The scaffold is a hybrid structure: well-predicted anchor sequence regions (identified from the `anchor_sequences` field in the analysis CSV, Kabsch-aligned to the reference frame) are taken from the best Chai-1 CIF output; poorly-predicted motif residues are taken from the original reference PDB (renumbered starting at 900). The contig string and `select_fixed_atoms` in `redesign.json` are rewritten to match the new residue numbering.
3. Spawns a new backbone-start branch (`start_step=STEP_BACKBONE_GEN`) using `redesign.json` as `rfd_input_filepath`. LMPNN JSONs are auto-generated from `redesign.json` at branch init via `generate_lmpnn_jsons()`.

Branch pipelines are full `DiscontinuousScaffoldsPipeline` instances configured with:
- `start_step` — skips earlier stages (`STEP_BACKBONE_GEN`, `STEP_SEQ_PRED`, or `STEP_FOLD_PRED`)
- `branch_id` — derived from `branch_ct` counter (e.g. `b1`, `b2`); fold branches increment `pipeline.branch_ct` directly
- `initial_state` — pre-seeds `self.state` for stages that would normally be set by earlier steps (e.g. `pdb_dir` for a sequence-start branch)
- All shared path/threshold kwargs inherited via `_shared_pipeline_kwargs()`

### Passing / failing model classification

`_identify_passing_models(df, model_col, thresholds)` (module-level helper in `discontinuous_scaffolds.py`) applies threshold filtering:
- A model **passes** if at least one of its rows satisfies **all** active thresholds simultaneously (full battery).
- A model **fails** if no such row exists.
- If no thresholds are active (all bounds are `None`), all models pass and no branches are spawned.

Thresholds are `(lower, upper)` tuples or `None`. Either bound can be `None` (open interval). Configured as kwargs on `DiscontinuousScaffoldsPipeline` and as constants in `run_discontinuous_scaffolds.py`:

| Stage | Threshold kwarg | CSV column |
|---|---|---|
| Backbone | `backbone_rog_bounds` | `radius_of_gyration` |
| Backbone | `backbone_ala_bounds` | `alanine_content` |
| Backbone | `backbone_gly_bounds` | `glycine_content` |
| Backbone | `backbone_helix_bounds` | `helix_fraction` |
| Backbone | `backbone_sheet_bounds` | `sheet_fraction` |
| Backbone | `backbone_lig_dist_bounds` | `n_clashing.ligand_min_distance` |
| Sequence | `seq_ligand_conf_bounds` | `ligand_confidence` |
| Sequence | `seq_overall_conf_bounds` | `overall_confidence` |

### Output directory structure

Each task creates its working directory as `{base_path}/{branch_id}/{taskcount}_{taskname}/in` and `.../out`. The `branch_id` prefix means outputs from a branch pipeline are isolated from both the originating pipeline and sibling branches:

```
{base_path}/
  b0/                        # root pipeline
    1_backbone_gen/out/
    2_backbone_post/out/
    ...
    filtered_lmpnn_pdb.json  # created by adaptive/backbone if models fail
    filtered_seqs_split/     # created by adaptive/sequence if models fail
    best_fold.json           # created by adaptive/fold if models fail rmsd_threshold
  b1/                        # redesign branch for failing fold models
    redesign.json            # updated RFD input (new contig + select_fixed_atoms)
    M0024_1nzy/
      redesign_scaffold.cif  # hybrid structure: anchor regions from chai + ref residues at 900+
    1_backbone_gen/out/
    ...
  b2/                        # sequence-start branch (branch_ct incremented per branch)
    4_seq_pred/out/
    ...
```

### Inter-step state passing

Steps communicate through `self.state`:

**Set by pipeline tasks:**
- `rfd3_out_dir` → `pdb_dir` (step 1 → step 2)
- `pdb_dir` → backbone analysis (step 2 → step 3)
- `pdb_dir` → seq pred (step 2 → step 4; via `lmpnn_pdb_multi_json`)
- `lmpnn_out_dir` → `seqs_split_dir` (step 4 → step 5)
- `seqs_split_dir` → seq analysis (step 5 → step 6)
- `seqs_split_dir` → fold pred (step 5 → step 7)
- `chai_out_dir` → pipeline analysis (step 7 → step 8)

**Set by local check tasks:**
- `last_analysis_step` — `'backbone'` / `'sequence'` / `'fold'` (read by `adaptive_decision`)
- `passing_backbone_models`, `failing_backbone_models` — lists of model name strings
- `passing_seq_models`, `failing_seq_models` — lists of model name strings
- `best_fold` — dict of `{model_name: {motif_rmsd, run_dir, seed, chai1_model_idx, anchor_residues, anchor_sequences, anchor_ref_residues}}` for the best fold per model (set by `check_fold_results`)
- `passing_fold_models`, `failing_fold_models` — lists of model name strings classified by `rmsd_threshold`

**Set by `adaptive_decision`:**
- `current_lmpnn_pdb_multi_json` — filtered LMPNN PDB JSON for passing backbone models (used by `seq_pred` if present)
- `current_lmpnn_fixed_res_json` — filtered fixed-residue JSON for passing backbone models
- `current_seqs_split_dir` — symlink dir of FA files for passing sequence models (used by `fold_pred` if present)
- `redesign_spec` — path to `redesign.json` produced by `create_redesign.py` for failing fold models

**Set at run start:**
- `run_count` — initialized to 0 via `setdefault`

**Injected via `initial_state` kwarg (branch pipelines only):**
- `pdb_dir` — required for sequence-start branches (skips steps 1–3)

### Anchor residue classification (`scripts/analysis.py`)

`analysis.py` (Step 8) computes a per-atom backbone displacement for each motif residue in each Chai-1 output, alongside the overall `motif_rmsd`. Three new columns are written to `campaign_analysis.csv`:

| Column | Format | Description |
|---|---|---|
| `anchor_residues` | `"A64,A86"` | Motif residues whose backbone atoms all have displacement < `rmsd_threshold` |
| `anchor_sequences` | `"50-76"` | Chai-1 sequence position ranges spanning consecutive anchor residues (≥2 in a row) |
| `anchor_ref_residues` | `"A64-A86"` | Corresponding reference structure residue ranges for each anchor sequence |

Key functions:
- `compute_motif_rmsd()` — now returns `(rmsd, motif_displacements)` where `motif_displacements = {res_key: {atom_name: Å, "refid": res_key}}`
- `compute_anchor_info(displacements, rmsd_threshold, contig_str, select_fixed_atoms)` — classifies anchor residues and finds consecutive runs; returns `(anchor_residues, anchor_sequences, anchor_ref_ranges)`

`analysis.py` accepts `--rmsd-threshold` (default 1.5); `step8_pipeline_analysis.sh` passes `$rmsd_threshold` through to it.

### Redesign scaffold generation (`scripts/create_redesign.py`)

Called by `adaptive_decision()` when fold models fail `rmsd_threshold`. For each failing model:

1. **Kabsch alignment** — align the best Chai-1 CIF backbone to the reference PDB frame using anchor motif residues as correspondence points.
2. **Anchor sequence extraction** — keep residues at chai sequence positions `[chai_start, chai_end]` (from `anchor_sequences` field), apply the Kabsch transform to place them in the reference coordinate frame.
3. **Non-anchor reference residues** — remove reference residues that fall within `anchor_ref_residues` spans; renumber remaining protein residues starting at 900.
4. **Combined structure** — merge the aligned anchor sequence and the renumbered non-anchor reference residues (plus the reference ligand) into `{branch_dir}/{model_name}/redesign_scaffold.cif`.
5. **Contig rewrite** — consecutive anchor residues in the original contig are collapsed to `A{chai_start}-{chai_end}`; non-anchor residues become `A900`, `A901`, etc.
6. **`select_fixed_atoms` rewrite** — anchor residue keys are renamed to their chai sequence positions; non-anchor residue keys are renamed to match the 900+ numbering; ligand keys are unchanged.
7. **`redesign.json`** — one entry per failing model with updated `"input"`, `"contig"`, and `"select_fixed_atoms"`.

### Execution backends

`run_discontinuous_scaffolds.py` has `DragonExecutionBackendV3()` active by default (HPC). Switch to the commented-out `LocalExecutionBackend(ThreadPoolExecutor())` for local testing.

### Benchmark data

`rfd3_benchmark/` contains two JSON formats for the MCSa-41 protein benchmark:
- `mcsa_41.json` — simplified format (protein ID → RFDiffusion command string)
- `mcsa_41_rfd3.json` — structured format with `input`, `ligand`, `contig`, `select_fixed_atoms` per protein
