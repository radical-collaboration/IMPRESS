# Discontinuous Scaffolds Workflow

A three-stage protein design campaign within the [IMPRESS](../../README.md) framework. The pipeline generates backbone structures, predicts sequences, and folds them — applying quality thresholds at each stage to route failing models into adaptive branch pipelines while passing models advance.

## Running the workflow

```shell
python run_discontinuous_scaffolds.py
```

Edit the path and threshold constants at the top of `run_discontinuous_scaffolds.py` before running. To run locally (without HPC), swap the backend in `run_discontinuous_scaffolds()`:

```python
# Local (testing)
backend = await LocalExecutionBackend(ThreadPoolExecutor())

# HPC (default)
backend = await DragonExecutionBackendV3()
```

---

## Pipeline steps

| Step | Name | Tool | Resource | Script |
|------|------|------|----------|--------|
| 1 | `backbone_gen` | RFDiffusion3 via `apptainer exec` | GPU | `step1_backbone_gen.sh` |
| 2 | `backbone_post` | `cif_to_pdb.py` | CPU | `step2_backbone_post.sh` |
| 3 | `backbone_analysis` | `analysis_backbone.py` + `plot_backbone_analysis.py` | CPU | `step3_backbone_analysis.sh` |
| 4 | `seq_pred` | LigandMPNN `run.py` | CPU | `step4_seq_pred.sh` |
| 5 | `seq_post` | `split_seqs.py` | CPU | `step5_seq_post.sh` |
| 6 | `seq_analysis` | `analysis_sequence.py` + `plot_sequence_analysis.py` | CPU | `step6_seq_analysis.sh` |
| 7 | `fold_pred` | Chai-lab `chai_batch.py` | GPU | `step7_fold_pred.sh` |
| 8 | `pipeline_analysis` | `analysis.py` + `plot_campaign.py` | CPU | `step8_pipeline_analysis.sh` |

---

## Three-stage execution flow

The eight steps are grouped into three stages. After each stage a local async task reads the analysis CSV and classifies each binding-motif model as passing or failing against the configured thresholds. The result is passed to `adaptive_decision()`, which either continues the pipeline, terminates it, or spawns a branch.

```
┌──────────────────────────────────────────────────────────┐
│ BACKBONE STAGE                                           │
│  Step 1: backbone_gen   (RFDiffusion3, GPU)              │
│  Step 2: backbone_post  (cif→pdb, CPU)                   │
│  Step 3: backbone_analysis (metrics CSV, CPU)            │
│  → check_backbone_results()  [local task]                │
│  → adaptive_decision()       [adaptive step]             │
│       passing models ──────────────────────────────────► │
│       failing models → spawn backbone-start branch       │
└──────────────────────────────────────────────────────────┘
                          │ passing models
                          ▼
┌──────────────────────────────────────────────────────────┐
│ SEQUENCE STAGE                                           │
│  Step 4: seq_pred       (LigandMPNN, CPU)                │
│  Step 5: seq_post       (split_seqs, CPU)                │
│  Step 6: seq_analysis   (metrics CSV, CPU)               │
│  → check_seq_results()       [local task]                │
│  → adaptive_decision()       [adaptive step]             │
│       passing models ──────────────────────────────────► │
│       failing models → spawn sequence-start branch       │
└──────────────────────────────────────────────────────────┘
                          │ passing models
                          ▼
┌──────────────────────────────────────────────────────────┐
│ FOLD STAGE                                               │
│  Step 7: fold_pred      (Chai-lab, GPU)                  │
│  Step 8: pipeline_analysis (final CSV + plots, CPU)      │
│  → check_fold_results()      [local task]                │
│       classifies by rmsd_threshold (best motif_rmsd)     │
│  → adaptive_decision()                                   │
│       passing models ──────────────────────────────────► │
│       failing models → spawn partial-diffusion branch    │
│       pipeline terminates (next_step = STEP_DONE)        │
└──────────────────────────────────────────────────────────┘
```

Branch pipelines are full `DiscontinuousScaffoldsPipeline` instances that re-enter the workflow at the stage where their models failed. Branches follow the same three-stage flow and can themselves spawn further branches.

---

## Adaptive branching

`adaptive_decision()` in `run_discontinuous_scaffolds.py` is called after each stage completes. It reads `pipeline.state['last_analysis_step']` (`'backbone'`, `'sequence'`, or `'fold'`) to decide what to do next.

### After the backbone stage

| Condition | Action |
|-----------|--------|
| All models fail | Set `next_step = STEP_DONE`; pipeline terminates |
| All models pass | Set `next_step = STEP_SEQ_PRED`; continue with full inputs |
| Mixed pass/fail | Set `next_step = STEP_SEQ_PRED`; filter main pipeline's LMPNN JSONs to passing models; spawn backbone-start branch for failing models |

When a backbone-start branch is spawned:
- `start_step = STEP_BACKBONE_GEN` — branch runs all three stages
- `rfd_input_filepath` — filtered to the failing models only via `_filter_rfd_json_by_models()`, which also rewrites any relative `"input"` paths to absolute paths
- `lmpnn_pdb_multi_json` / `lmpnn_fixed_res_json` — auto-generated for the branch from the filtered `rfd_input_filepath` (same mechanism as the root pipeline)

The main pipeline's `current_lmpnn_pdb_multi_json` and `current_lmpnn_fixed_res_json` are updated to filtered JSONs so Step 4 only processes passing backbone models.

### After the sequence stage

| Condition | Action |
|-----------|--------|
| All models fail | Set `next_step = STEP_DONE`; pipeline terminates |
| All models pass | Set `next_step = STEP_FOLD_PRED`; continue with full sequence directory |
| Mixed pass/fail | Set `next_step = STEP_FOLD_PRED`; create symlink directory of passing `.fa` files; spawn sequence-start branch for failing models |

When a sequence-start branch is spawned:
- `start_step = STEP_SEQ_PRED` — branch skips backbone generation
- `lmpnn_pdb_multi_json` / `lmpnn_fixed_res_json` — filtered to the failing models only
- `initial_state = {'pdb_dir': pipeline.state['pdb_dir']}` — pre-seeds the PDB directory that Step 4 would normally receive from Step 2

The main pipeline's `current_seqs_split_dir` is updated to a symlink directory containing only the passing sequences.

### After the fold stage

| Condition | Action |
|-----------|--------|
| All models pass | Set `next_step = STEP_DONE`; pipeline terminates |
| All models fail | Spawn partial-diffusion branch; set `next_step = STEP_DONE` |
| Mixed pass/fail | Spawn partial-diffusion branch for failing models; set `next_step = STEP_DONE` |

When a partial-diffusion branch is spawned:
- `adaptive_decision()` serializes `pipeline.state['best_fold']` to `{base}/{branch_id}/best_fold.json`
- `scripts/parse_partial_diffusion.py` is run to produce `partial.json` — a filtered RFDiffusion input spec with `"input"` set to each failing model's best predicted structure directory and `"partial_t": 10` added
- A new backbone-start branch (`start_step = STEP_BACKBONE_GEN`) is spawned using `partial.json` as `rfd_input_filepath`
- `pipeline.branch_ct` is incremented; the new branch's `branch_id` is `f"b{pipeline.branch_ct}"`

The pipeline always terminates after the fold stage (`next_step = STEP_DONE`) regardless of pass/fail results.

### Branch naming

Branch IDs are derived from a `branch_ct` integer attribute on the pipeline instance. The root pipeline defaults to `branch_ct=0` → `branch_id='b0'`. When a fold branch is spawned, `pipeline.branch_ct` is incremented on the parent and the new branch receives that value (e.g. `branch_ct=1` → `branch_id='b1'`). Backbone and sequence branches use a separate `_next_branch_id()` helper. Branch pipelines are named `{pipeline.name}_{branch_id}`.

---

## Configuration arguments

All arguments are passed as kwargs to `DiscontinuousScaffoldsPipeline` (via `PipelineSetup.kwargs` in `run_discontinuous_scaffolds.py`).

### Path arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `base_path` | `str` | `os.getcwd()` | Root directory for all task outputs |
| `scripts_path` | `str` | `DEFAULT_SCRIPTS_PATH` | Directory containing the step shell scripts |
| `foundry_sif_path` | `str` | `DEFAULT_FOUNDRY_SIF` | Path to the Singularity/Apptainer container image |
| `mpnn_dir` | `str` | `DEFAULT_MPNN_DIR` | Path to the LigandMPNN installation |

### Pipeline input arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `rfd_input_filepath` | `str` | `DEFAULT_RFD_INPUT` | RFDiffusion3 input JSON file |
| `lmpnn_pdb_multi_json` | `str` | auto-generated | LigandMPNN batch PDB JSON (maps model names to PDB paths); auto-generated from `rfd_input_filepath` by `generate_lmpnn_jsons()` at pipeline init if not provided |
| `lmpnn_fixed_res_json` | `str` | auto-generated | LigandMPNN fixed residues JSON; auto-generated from `rfd_input_filepath` by `generate_lmpnn_jsons()` at pipeline init if not provided |
| `island_counts_csv` | `str` | `None` | Island counts reference CSV (used in backbone and sequence analysis) |
| `mcsa_pdb_dir` | `str` | `None` | Directory of reference MCSA PDB files for RMSD comparison in final analysis |
| `rmsd_threshold` | `float` | `1.5` | RMSD threshold (Å) used in Step 8 final analysis |
| `diffusion_batch_size` | `int` | `10` | Number of structures per RFDiffusion3 batch |

### Branching control arguments

These are set automatically by `adaptive_decision()` when spawning branch pipelines. You generally do not set them on the root pipeline.

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `branch_id` | `str` | `'b0'` | Namespace prefix for this pipeline's output directories |
| `start_step` | `int` | `STEP_BACKBONE_GEN` (1) | First step to execute; earlier stages are skipped |
| `initial_state` | `dict` | `None` | Pre-seeds `self.state` before `run()` starts; used by sequence-start branches to inject `pdb_dir` |

### Threshold arguments

All threshold arguments are `tuple[float | None, float | None] | None`. A value of `None` disables the threshold entirely. A bound of `None` within a tuple leaves that side of the interval open (e.g., `(0.5, None)` means "at least 0.5, no upper limit").

**Backbone thresholds** — evaluated against the backbone analysis CSV after Step 3:

| Argument | CSV column | Description |
|----------|-----------|-------------|
| `backbone_rog_bounds` | `radius_of_gyration` | Radius of gyration of the generated backbone (Å) |
| `backbone_ala_bounds` | `alanine_content` | Fraction of alanine residues in the backbone |
| `backbone_gly_bounds` | `glycine_content` | Fraction of glycine residues in the backbone |
| `backbone_helix_bounds` | `helix_fraction` | Fraction of residues in helical secondary structure |
| `backbone_sheet_bounds` | `sheet_fraction` | Fraction of residues in beta-sheet secondary structure |
| `backbone_lig_dist_bounds` | `n_clashing.ligand_min_distance` | Minimum distance between backbone atoms and the ligand (Å); use a lower bound to require a minimum clearance |

**Sequence thresholds** — evaluated against the sequence analysis CSV after Step 6:

| Argument | CSV column | Description |
|----------|-----------|-------------|
| `seq_ligand_conf_bounds` | `ligand_confidence` | LigandMPNN confidence score for the ligand-binding region (0–1) |
| `seq_overall_conf_bounds` | `overall_confidence` | LigandMPNN overall sequence confidence score (0–1) |

All threshold arguments default to `None` (no filtering). Example values:

```python
backbone_rog_bounds      = (5.0, 25.0)   # keep structures with Rg between 5–25 Å
backbone_lig_dist_bounds = (2.0, None)   # require at least 2 Å clearance from ligand
seq_ligand_conf_bounds   = (0.5, 1.0)    # require ligand confidence ≥ 0.5
```

### Threshold filtering logic

A model **passes** a stage if at least one of its rows in the analysis CSV satisfies **all** active thresholds simultaneously. A model **fails** if no such row exists.

- If no thresholds are active (all `None`), all models pass and no branches are spawned.
- Either bound of a tuple can be `None` (open interval).
- Rows with `NaN` for a threshold metric are treated as failing that metric.

This logic is implemented in `_identify_passing_models(df, model_col, thresholds)` in `discontinuous_scaffolds.py`.

---

## State dictionary

`self.state` is a plain dict on each `DiscontinuousScaffoldsPipeline` instance. Keys are set by pipeline task methods, local check tasks, and `adaptive_decision()`.

### Set by pipeline task methods

| Key | Set by | Read by | Description |
|-----|--------|---------|-------------|
| `rfd3_out_dir` | Step 1 (`backbone_gen`) | Step 2 | Output directory containing RFDiffusion3 CIF files |
| `pdb_dir` | Step 2 (`backbone_post`) | Steps 3, 4; branch `initial_state` | Directory containing converted PDB files |
| `backbone_analysis_csv` | Step 3 (`backbone_analysis`) | `check_backbone_results` | Path to backbone quality metrics CSV |
| `backbone_analysis_out_dir` | Step 3 | — | Directory containing backbone analysis plots |
| `lmpnn_out_dir` | Step 4 (`seq_pred`) | Step 5 | LigandMPNN output directory |
| `seqs_split_dir` | Step 5 (`seq_post`) | Steps 6, 7; `adaptive_decision` | Directory of split `.fa` sequence files |
| `seq_analysis_csv` | Step 6 (`seq_analysis`) | `check_seq_results` | Path to sequence quality metrics CSV |
| `seq_analysis_out_dir` | Step 6 | — | Directory containing sequence analysis plots |
| `chai_out_dir` | Step 7 (`fold_pred`) | Step 8 | Chai-lab output directory |
| `analysis_csv` | Step 8 (`pipeline_analysis`) | — | Path to final campaign analysis CSV |
| `analysis_out_dir` | Step 8 | — | Directory containing campaign plots |

### Set by local check tasks

| Key | Set by | Read by | Description |
|-----|--------|---------|-------------|
| `last_analysis_step` | `check_backbone_results` / `check_seq_results` / `check_fold_results` | `adaptive_decision` | `'backbone'`, `'sequence'`, or `'fold'`; routes `adaptive_decision` |
| `passing_backbone_models` | `check_backbone_results` | `adaptive_decision` | List of model name strings that passed all active backbone thresholds |
| `failing_backbone_models` | `check_backbone_results` | `adaptive_decision` | List of model name strings that failed any active backbone threshold |
| `passing_seq_models` | `check_seq_results` | `adaptive_decision` | List of model name strings that passed all active sequence thresholds |
| `failing_seq_models` | `check_seq_results` | `adaptive_decision` | List of model name strings that failed any active sequence threshold |
| `best_fold` | `check_fold_results` | `adaptive_decision` | Dict of `{model_name: {motif_rmsd, run_dir, seed}}` — best fold per model (lowest `motif_rmsd`) |
| `passing_fold_models` | `check_fold_results` | `adaptive_decision` | List of model name strings with `motif_rmsd < rmsd_threshold` |
| `failing_fold_models` | `check_fold_results` | `adaptive_decision` | List of model name strings with `motif_rmsd >= rmsd_threshold` |

### Set by `adaptive_decision()`

| Key | Set by | Read by | Description |
|-----|--------|---------|-------------|
| `current_lmpnn_pdb_multi_json` | `adaptive_decision` (backbone branch) | Step 4 | Filtered LMPNN PDB JSON containing only passing backbone models; replaces `lmpnn_pdb_multi_json` for this pipeline |
| `current_lmpnn_fixed_res_json` | `adaptive_decision` (backbone branch) | Step 4 | Filtered fixed-residue JSON for passing backbone models |
| `current_seqs_split_dir` | `adaptive_decision` (sequence branch) | Step 7 | Symlink directory of `.fa` files for passing sequence models; replaces `seqs_split_dir` for this pipeline |
| `partial_spec` | `adaptive_decision` (fold branch) | — | Path to `partial.json` produced by `parse_partial_diffusion.py`; passed as `rfd_input_filepath` to the partial-diffusion branch |

### Set at pipeline startup

| Key | Set by | Description |
|-----|--------|-------------|
| `run_count` | `run()` (via `setdefault`) | Run counter, initialized to 0 |
| `taskcount` | `run()` | Incremented for each task; used to number output directories |

### Injected via `initial_state` (branch pipelines only)

| Key | Required by | Description |
|-----|-------------|-------------|
| `pdb_dir` | Sequence-start branches (Steps 4–8) | Pre-seeds the PDB directory that Step 2 would normally write; required because backbone stage is skipped |

---

## Output directory structure

Each task creates its working directories under `{base_path}/{branch_id}/{taskcount}_{taskname}/`:

```
{base_path}/
  b0/                              # root pipeline
    1_backbone_gen/
      in/
      out/                         # RFDiffusion3 CIF files
    2_backbone_post/
      in/
      out/                         # converted PDB files
    3_backbone_analysis/
      in/
      out/                         # metrics CSV, plots
    filtered_lmpnn_pdb.json        # created if backbone branch spawned
    filtered_lmpnn_fixed_res.json
    4_seq_pred/
      in/
      out/                         # LigandMPNN sequence files
    5_seq_post/
      in/
      out/                         # split .fa files
    6_seq_analysis/
      in/
      out/                         # metrics CSV, plots
    filtered_seqs_split/           # symlinks; created if sequence branch spawned
    7_fold_pred/
      in/
      out/                         # Chai-lab structure files
    8_pipeline_analysis/
      in/
      out/                         # final CSV, campaign plots
    best_fold.json                 # created if fold branch spawned

  b1/                              # partial-diffusion branch for failing fold models
    partial.json                   # filtered RFD input (input=best chai dir, partial_t=10)
    1_backbone_gen/
    ...

  b2/                              # sequence-start branch (branch_ct incremented per branch)
    4_seq_pred/                    # taskcount continues from branch start_step
    ...
```

The `branch_id` prefix isolates each branch pipeline's outputs from the root pipeline and from sibling branches.
