# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-04-06 | 3390b61 | change log added |

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

Before running on HPC, edit the path constants at the top of `run_small_molecule_binding.py` and the `__init__` kwargs in `SmallMoleculeBindingPipeline` (`foundry_sif_path`, `colabfold_path`, `mpnn_dir`, `ligand_params`, etc.) to match the target system.

## Architecture

### Two-file structure

- **`small_molecule_binding.py`** — defines `SmallMoleculeBindingPipeline(ImpressBasePipeline)`, all step constants, ensemble utility functions (`_ca_rmsd`, `_seq_identity`, `_ensemble_selective_avg`), and the inner `_run_refine_cycle()` loop. All pipeline tasks (HPC and local analysis) are registered via `@self.auto_register_task()` inside `_register_real_tasks()`. The `run()` method drives a state-machine loop; `_run_refine_cycle()` handles the MPNN+PackMin inner loop with per-cycle sequence retry support.

- **`run_small_molecule_binding.py`** — entry point. Sets threshold constants, defines the `adaptive_decision()` callback, creates an `ImpressManager`, and launches via `manager.start(pipeline_setups=[...])`.

### Step constants (state-machine constants in `small_molecule_binding.py`)

| Constant | Value | Meaning |
|---|---|---|
| `STEP_DONE` | 0 | pipeline complete |
| `STEP_RFD3` | 1 | backbone diffusion |
| `STEP_MPNN` | 2 | MPNN + PackMin refinement cycle |
| `STEP_FASTRELAX` | 3 | Rosetta FastRelax |
| `STEP_INTERFACE` | 4 | filter_shape (PyRosetta, gates AF2) |
| `STEP_AF2` | 5 | fold prediction |
| `STEP_RETRY_SEQ` | 6 | internal: retry sequence prediction without backbone restart |

### Pipeline tasks and scripts

| Task (registered name) | Type | Script / Tool | Resource |
|---|---|---|---|
| `rfd3` | HPC | `scripts/rfd3.sh` (RFDiffusion3 via `apptainer exec`) | GPU |
| `analysis_backbone` | local | reads JSON metrics from `rfd3` output dir | CPU |
| `mpnn` | HPC | `scripts/mpnn.sh` → `scripts/mpnn_wrapper.sh` (LigandMPNN) | CPU |
| `analysis_sequence` | local | reads `.fa` headers from MPNN `seqs/` output | CPU |
| `packmin` | HPC | `scripts/packmin.sh` → `scripts/packmin.py` (PyRosetta pack+minimize) | CPU |
| `analysis_packmin` | local | reads `_packmin_score.json` from packmin output | CPU |
| `fastrelax` | HPC | `scripts/fastrelax.sh` → `scripts/fastrelax.py` (Rosetta FastRelax) | CPU |
| `analysis_fastrelax` | local | reads `.fasc` score file from fastrelax output | CPU |
| `filter_shape` | HPC | `scripts/filter_shape.sh` → `scripts/filter_shape.py` (PyRosetta shape complementarity) | CPU |
| `analysis_interface` | local | reads `shape_complementarity_values.txt` | CPU |
| `af2` | HPC | `scripts/af2.sh` (ColabFold/LocalColabFold) | GPU |
| `analysis_fold` | local | reads ColabFold `_scores.json` files | CPU |
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
| `fastrelax` | interaction energy, total score, fa_rep below thresholds | `STEP_INTERFACE` | `STEP_MPNN` |
| `interface` | shape complementarity `max_sc >= interface_min_sc` | `STEP_AF2` | `STEP_MPNN` (up to 5x), then `STEP_RFD3` |
| `fold` | mean pLDDT `>= fold_min_plddt` | sets `rfd3_input_pdb` for guided backbone → `STEP_RFD3` | clears `rfd3_input_pdb` → `STEP_RFD3` |

### Ensemble-guided backbone feedback

After a successful fold prediction, `adaptive_decision()` computes CA-RMSD between the current AF2 model and all prior fold ensemble entries. If the selective average score (for structurally similar models) exceeds the overall average, the current AF2 model is fed back as `rfd3_input_pdb` for the next RFDiffusion run (`scaffoldguided.target_pdb`), biasing the next backbone toward successful structural motifs.

Ensemble similarity utilities (all in `small_molecule_binding.py`):
- `_ca_rmsd(path1, path2)` — Kabsch-aligned CA RMSD between two PDB files
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
| `fold_min_plddt` | 70.0 | minimum mean pLDDT |
| `max_tasks` | 300 | maximum ensemble entries before stopping |

Threshold constants in `run_small_molecule_binding.py` override these defaults at `PipelineSetup` construction.

### Output directory structure

Each HPC task creates its working directory as `{base_path}/{taskcount}_{taskname}/in` and `.../out`. `taskcount` is a flat integer incremented for every HPC task (local analysis tasks do not increment it).

```
{base_path}/
  {name}_in/           # pipeline inputs (ALR_binder_design.json, ligand .params, etc.)
  1_rfd3/out/          # RFDiffusion3 outputs (.cif.gz + .json per model)
  2_mpnn/out/          # LigandMPNN outputs (seqs/*.fa, packed/*.pdb)
  3_packmin/out/       # packed+minimized PDB + _packmin_score.json
  4_mpnn/out/          # cycle 1 MPNN ...
  ...
  N_fastrelax/out/     # FastRelax PDB + .fasc score file
  N+1_filter_shape/out/
  N+2_alphafold/out/
```

MPNN copies the input backbone to a short fixed filename (`binder.cif.gz` or `binder.<ext>`) in `{taskdir}/in/` each cycle to avoid 255-character filename limits in AF2 result archives.

### Inter-step state passing

Steps communicate via `self.state`:

**Set by HPC task wrappers / local analysis tasks:**
- `best_backbone_path` — path to best `.cif.gz` from `rfd3` (set by `analysis_backbone`)
- `best_packed_pdb` — path to best packed PDB (set by `analysis_sequence`, updated by `packmin`)
- `last_seq_fasta` — path to best FASTA from MPNN (set by `analysis_sequence`)
- `best_af2_model` — path to best AF2 PDB (set by `analysis_fold`)
- `last_analysis_step` — `'backbone'` / `'sequence'` / `'packmin'` / `'fastrelax'` / `'interface'` / `'fold'`
- `last_analysis_metrics` — dict with `pass` bool and step-specific score fields
- `ensemble` — list of `(etype, score, input_path, output_path)` tuples

**Set by `adaptive_decision`:**
- `rfd3_input_pdb` — if set, passed to `rfd3` as `scaffoldguided.target_pdb` for guided diffusion
- `seq_retry_count` — retry counter for sequence stage (reset on new backbone or successful sequence)
- `interface_fail_count` — retry counter for interface stage (reset on pass or after 5 failures)

**Set at run start (`setdefault`):**
- `ensemble` — initialized to `[]`
- `rfd3_input_pdb` — initialized to `None`
- `seq_retry_count` — initialized to `0`
- `last_seq_fasta` — initialized to `None`

### Execution backends

`run_small_molecule_binding.py` has `LocalExecutionBackend(ProcessPoolExecutor())` active by default. `DragonExecutionBackendV3()` is commented out — swap it in for HPC production runs.

### Pipeline inputs

Each pipeline instance (named e.g. `p1`) expects a `{name}_in/` directory containing:
- `ALR_binder_design.json` — RFDiffusion3 input spec (contig, ligand, scaffold args)
- `<ligand_name>.params` — Rosetta ligand params file (default `ALR.params`)
- Optionally `common_filenames.txt` — used by `filter_energy` for cross-filtering
