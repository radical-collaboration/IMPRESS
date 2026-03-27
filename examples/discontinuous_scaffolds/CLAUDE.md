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

Before running on HPC, edit the path constants at the top of `run_discontinuous_scaffolds.py` (`SCRIPTS_PATH`, `FOUNDRY_SIF_PATH`, `MPNN_DIR`, `RFD_INPUT_FILEPATH`, `LMPNN_PDB_MULTI_JSON`, `LMPNN_FIXED_RES_JSON`, `ISLAND_COUNTS_CSV`, `MCSA_PDB_DIR`, etc.) to match the target system.

## Architecture

### Two-file structure

- **`discontinuous_scaffolds.py`** — defines `DiscontinuousScaffoldsPipeline(ImpressBasePipeline)`. All eight pipeline steps are registered as async task methods inside `register_pipeline_tasks()` using the `@self.auto_register_task()` decorator. The `run()` method drives a `while next_step != STEP_DONE` loop that supports adaptive restarts.

- **`run_discontinuous_scaffolds.py`** — entry point. Sets path/parameter constants, defines the `adaptive_decision()` callback, creates an `ImpressManager`, and launches via `manager.start(pipeline_setups=[...])`.

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
| `STEP_ANALYSIS` | 8 | `analysis.py` + `plot_campaign.py` | CPU |

After step 8 a local `check_analysis_results()` task sets `pipeline.state['analysis_present']`, then `run_adaptive_step()` calls `adaptive_decision()`. If the analysis CSV was produced, the pipeline restarts from step 1 with `run_count` incremented; otherwise it exits.

### Inter-step state passing

Steps communicate through `self.state` (a dict on the pipeline instance):
- `rfd3_out_dir` → `pdb_dir` (step 1→2)
- `pdb_dir` → `backbone_analysis_csv` / `backbone_analysis_out_dir` (step 2→3)
- `pdb_dir` → `lmpnn_out_dir` (step 2→4)
- `lmpnn_out_dir` → `seqs_split_dir` (step 4→5)
- `seqs_split_dir` → `seq_analysis_csv` / `seq_analysis_out_dir` (step 5→6)
- `seqs_split_dir` → `chai_out_dir` (step 5→7)
- `chai_out_dir` → `analysis_csv` / `analysis_out_dir` (step 7→8)

### Execution backends

`run_discontinuous_scaffolds.py` defaults to `LocalExecutionBackend(ThreadPoolExecutor())` for local testing. Switch to `DragonExecutionBackendV3()` for HPC (the commented-out line in `run_discontinuous_scaffolds()`).

### Virtual environment pre-exec

GPU/CPU steps each activate a different venv via `pre_exec` lists (`IMPRESS_PRE_EXEC`, `LIGANDMPNN_PRE_EXEC`, `CHAI_PRE_EXEC`) defined at module level in `discontinuous_scaffolds.py`. These paths are HPC-system-specific and must be updated when deploying.

### Benchmark data

`rfd3_benchmark/` contains two JSON formats for the MCSa-41 protein benchmark:
- `mcsa_41.json` — simplified format (protein ID → RFDiffusion command string)
- `mcsa_41_rfd3.json` — structured format with `input`, `ligand`, `contig`, `select_fixed_atoms` per protein
