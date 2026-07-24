# Discontinuous Scaffolds

Location: [`examples/discontinuous_scaffolds/`](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/discontinuous_scaffolds)

A three-stage protein design campaign targeting the MCSA-41 benchmark
enzyme active sites. The pipeline generates backbone structures with
discontinuous binding-motif scaffolds, predicts sequences, and folds them —
applying quality thresholds at each stage to route failing models into
adaptive branch pipelines while passing models advance, including a
geometry-aware hybrid-scaffold redesign loop when folds don't recapitulate
the target motif.

## Inputs

All arguments are passed as kwargs to `DiscontinuousScaffoldsPipeline`.

### Path arguments

| Argument | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Root directory for all task outputs |
| `scripts_path` | `DEFAULT_SCRIPTS_PATH` | Directory containing the step shell scripts |
| `foundry_sif_path` | `DEFAULT_FOUNDRY_SIF` | Apptainer/Singularity image containing RFDiffusion3 |
| `mpnn_dir` | `DEFAULT_MPNN_DIR` | Path to the LigandMPNN installation |

### Pipeline input arguments

| Argument | Default | Description |
|---|---|---|
| `rfd_input_filepath` | `DEFAULT_RFD_INPUT` | RFDiffusion3 input JSON (per-model `input`, `ligand`, `contig`, `select_fixed_atoms`) |
| `lmpnn_pdb_multi_json` / `lmpnn_fixed_res_json` | auto-generated | LigandMPNN batch JSONs; generated from `rfd_input_filepath` at pipeline init if not provided |
| `island_counts_csv` | `None` | Reference CSV of residue-island counts, used in backbone/sequence analysis |
| `mcsa_pdb_dir` | `None` | Directory of reference PDBs for RMSD comparison in the final analysis |
| `rmsd_threshold` | `1.5` | RMSD threshold (Å) for Step 8 analysis and anchor-residue classification |
| `diffusion_batch_size` | `10` | Structures per RFDiffusion3 batch |
| `lmpnn_num_batches` | `4` | LigandMPNN sequence batches generated per model |

### Threshold arguments

All threshold arguments are `(lower, upper)` tuples or `None` (either bound
may be `None` for an open interval); `None` disables the threshold
entirely.

| Stage | Argument | CSV column |
|---|---|---|
| Backbone | `backbone_rog_bounds` | `radius_of_gyration` |
| Backbone | `backbone_ala_bounds` | `alanine_content` |
| Backbone | `backbone_gly_bounds` | `glycine_content` |
| Backbone | `backbone_helix_bounds` | `helix_fraction` |
| Backbone | `backbone_sheet_bounds` | `sheet_fraction` |
| Backbone | `backbone_lig_dist_bounds` | `n_clashing.ligand_min_distance` |
| Sequence | `seq_ligand_conf_bounds` | `ligand_confidence` |
| Sequence | `seq_overall_conf_bounds` | `overall_confidence` |

Benchmark input files live under `scripts/`: `mcsa_41-{1..41}.json` (one
per protein), `mcsa_41_rfd3.json` (all-in-one), `mcsa_41_one.json`
(single-entry test file).

## Pipeline Stages

| Step | Name | Tool | Resource |
|---|---|---|---|
| 1 | `backbone_gen` | RFDiffusion3 via `apptainer exec` | GPU |
| 2 | `backbone_post` | `cif_to_pdb.py` | CPU |
| 3 | `backbone_analysis` | `analysis_backbone.py` + `plot_backbone_analysis.py` | CPU |
| 4 | `seq_pred` | LigandMPNN `run.py` | CPU |
| 5 | `seq_post` | `split_seqs.py` | CPU |
| 6 | `seq_analysis` | `analysis_sequence.py` + `plot_sequence_analysis.py` | CPU |
| 7 | `fold_pred` | Chai-lab `chai_batch.py` | GPU |
| 8 | `pipeline_analysis` | `analysis.py` + `plot_campaign.py` | CPU |

These eight steps are grouped into three stages: **backbone** (1–3),
**sequence** (4–6), **fold** (7–8).

## Adaptive Flow

```
BACKBONE STAGE (steps 1-3) --> check_backbone_results() --> adaptive_decision()
    passing models -----------------------------------------------> continue
    failing models --> spawn backbone-start branch
                          |
                    SEQUENCE STAGE (steps 4-6) --> check_seq_results() --> adaptive_decision()
                        passing models ------------------------------------> continue
                        failing models --> spawn sequence-start branch
                                              |
                                        FOLD STAGE (steps 7-8) --> check_fold_results() --> adaptive_decision()
                                            passing models -----------------------------------> done
                                            failing models --> spawn redesign-scaffold branch
                                            pipeline terminates (next_step = STEP_DONE)
```

A model **passes** a stage if at least one of its analysis-CSV rows
satisfies **all** active thresholds simultaneously; it **fails** if no such
row exists. If no thresholds are configured, every model passes and no
branches are spawned (`_identify_passing_models()`).

### After the backbone / sequence stages

| Condition | Action |
|---|---|
| All models fail | `next_step = STEP_DONE`; pipeline terminates |
| All models pass | Continue to the next stage with the full input set |
| Mixed pass/fail | Filter the current pipeline's inputs to passing models; spawn a branch pipeline (`start_step` = the failed stage) for the failing models |

Backbone branches receive an `rfd_input_filepath` filtered to the failing
models (with relative `"input"` paths rewritten to absolute). Sequence
branches receive filtered LigandMPNN JSONs and a symlinked directory of
passing `.fa` files, plus `initial_state={'pdb_dir': ...}` to seed the state
a skipped backbone stage would normally have produced.

### After the fold stage — redesign loop

The pipeline always terminates after the fold stage
(`next_step = STEP_DONE`), but if any models fail `rmsd_threshold`, a
**redesign-scaffold branch** may be spawned first. Two stopping conditions
prevent runaway redesign loops — if either is true, no branch is spawned:

| Constant | Default | Condition |
|---|---|---|
| `MAX_REDESIGN_DEPTH` | `3` | This lineage has already been redesigned this many times |
| `MIN_RMSD_IMPROVEMENT` | `0.10 Å` | RMSD hasn't improved enough since the last redesign |

If neither condition triggers, `adaptive_decision()` serializes the best
fold per model, then runs `scripts/create_redesign.py` to build a **hybrid
scaffold**: well-predicted anchor motif regions (Kabsch-aligned from the
best Chai-1 output) are combined with poorly-predicted motif residues taken
directly from the reference PDB (renumbered starting at 900); the contig
string and fixed-atom spec are rewritten to match. A new backbone-start
branch is then spawned from this `redesign.json`, carrying
`redesign_depth + 1` and the current best RMSD forward.

### Branch naming

| Branch type | `branch_id` format | Example |
|---|---|---|
| Root pipeline | `{pipeline_name}_0` | `disco_p26_0` |
| Backbone/sequence branch | `{pipeline_name}_{n}` | `disco_p26_1` |
| Fold redesign branch | `{pipeline_name}_R` | `disco_p26_R` |
| Second redesign of a redesign | `{original_name}_R_R` | `disco_p26_R_R` |

## Output Structure

```
{base_path}/
  disco_p26_0/                     # root pipeline
    1_backbone_gen/out/
    2_backbone_post/out/
    3_backbone_analysis/out/
    filtered_lmpnn_pdb.json         # if a backbone branch was spawned
    4_seq_pred/out/
    5_seq_post/out/
    6_seq_analysis/out/
    filtered_seqs_split/            # if a sequence branch was spawned
    7_fold_pred/out/
    8_pipeline_analysis/out/
    best_fold.json                  # if a fold branch was spawned
  disco_p26_R/                     # redesign branch
    redesign.json
    M0024_1nzy/redesign_scaffold.cif
    1_backbone_gen/out/
    ...
```

The `branch_id` prefix isolates each branch's outputs from the root
pipeline and from sibling branches.

## Running It

```bash
cd examples/discontinuous_scaffolds
python run_discontinuous_scaffolds.py
```

Edit the path and threshold constants at the top of
`run_discontinuous_scaffolds.py` before running; one
`DiscontinuousScaffoldsPipeline` is launched per benchmark input file.
`DragonExecutionBackendV3()` is active by default (HPC); swap in
`LocalExecutionBackend(ThreadPoolExecutor())` for local testing.
