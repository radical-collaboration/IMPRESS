# Small Molecule Binding Pipeline

An IMPRESS pipeline for iterative computational design of protein binders against a small molecule ligand. Starting from a ligand-containing target structure, the pipeline runs backbone diffusion → sequence design → energy minimization → structural validation → fold prediction in a loop, using an ensemble-based adaptive routing function to direct the search toward productive regions of structure-sequence space.

---

## Pipeline Overview

```
rfd3 ──► analysis_backbone ──► [adaptive]
                                    │ pass
                                    ▼
                              mpnn (×N batches)
                              analysis_sequence ──► [adaptive]
                                    │ pass / RETRY_SEQ (up to 3×)
                                    ▼
                              packmin
                              analysis_packmin ──► [adaptive]
                                    │ (cycles 0..num_refine_cycles-2)
                                    ▼
                              fastrelax
                              analysis_fastrelax ──► [adaptive]
                                    │ pass
                                    ▼
                              filter_shape
                              analysis_interface ──► [adaptive]
                                    │ pass
                                    ▼
                              af2
                              analysis_fold ──► [adaptive] ──► rfd3 (loop)
```

Each `[adaptive]` call invokes `adaptive_decision` (defined in `run_small_molecule_binding.py`), which reads the analysis metrics and the growing ensemble history to decide the next step. The pipeline loops until the task budget is exhausted (`max_tasks` ensemble entries).

---

## Transformation Tasks

### `rfd3` — Backbone Diffusion
Generates a new protein backbone scaffold conditioned on the ligand binding site using RFdiffusion3 (via Apptainer). On the first iteration or after a failed fold, generation starts from scratch. After a successful fold that lands in a high-scoring neighbourhood (see adaptive rules below), the previous fold decoy is passed as `scaffoldguided.target_pdb=<path>` to bias sampling toward that region.

- **Input**: `<pipeline_name>_in/ALR_binder_design.json` (diffusion config), optionally a scaffold PDB from the previous fold
- **Output**: `<N>_rfd3/out/<model>.cif.gz` + `<model>.json` (per-model metrics)
- **HPC**: 1 GPU per rank

### `mpnn` + `analysis_sequence` — Sequence Design
Runs LigandMPNN to design amino acid sequences for the current backbone. On cycle 0, `mpnn_ensemble_size` independent sequence batches are generated from the backbone; on subsequent cycles within the same refinement loop, 1 batch is generated from the best packed structure so far. Side-chain packing is performed alongside sequence design.

- **Input**: backbone PDB (cycle 0) or best packed PDB (cycle > 0); optional `fixed_residues.txt`
- **Output**: `<N>_mpnn/out/seqs/*.fa` (FASTA with confidence scores in header), `<N>_mpnn/out/packed/*.pdb` (packed structures)
- **Scores extracted**: `overall_confidence` (0–1), `ligand_confidence` (0–1) from FASTA header

### `packmin` + `analysis_packmin` — Side-Chain Pack & Minimize
PyRosetta script that repacks side chains and performs energy minimization on the best-confidence sequence. Used between MPNN cycles to propagate structural improvements.

- **Input**: best packed PDB from previous MPNN step; ligand `.params` file
- **Output**: `<N>_packmin/out/<stem>_minimized.pdb`, `<stem>_minimized_packmin_score.json`
- **Scores extracted**: `total_score` (REU, Rosetta Energy Units)

### `fastrelax` + `analysis_fastrelax` — Rosetta FastRelax
Full backbone + side-chain relaxation of the best packed structure using Rosetta FastRelax (1 round). Gates progression to interface analysis.

- **Input**: best packed PDB; ligand `.params` file
- **Output**: `<N>_fastrelax/out/<stem>_relaxed_0001.pdb`, `<stem>_relaxed.fasc`
- **Scores extracted**: `total_score` (REU), `interaction_energy` (REU, protein–ligand interaction), `fa_rep` (REU, Lennard-Jones repulsion), `rmsd` (Å, deviation from input)

### `filter_shape` + `analysis_interface` — Shape Complementarity
PyRosetta script computing shape complementarity (SC) and interface energetics between the designed protein and ligand. Gates progression to fold prediction.

- **Input**: directory of relaxed PDB files from the previous FastRelax step; ligand directory under `<pipeline_name>_in/<ligand_name>`
- **Output**: `<N>_filter_shape/out/shape_complementarity_values.txt` (SC per model), `interface_values.txt` (full interface metrics CSV)
- **Scores extracted**: `max_sc` — maximum SC value across all models in the batch (0–1 scale)

### `af2` + `analysis_fold` — AlphaFold2 Fold Prediction
ColabFold (AlphaFold2 multimer) predicts the fold of the best-confidence sequence to assess structural self-consistency between the diffused backbone and the designed sequence.

- **Input**: FASTA of best-confidence sequence (`state['last_seq_fasta']`)
- **Output**: `<N>_alphafold/out/rank_*.pdb`, `rank_*_scores.json`
- **Scores extracted**: `best_mean_plddt` — mean per-residue pLDDT (0–100) of the highest-scoring ranked model
- **HPC**: 1 GPU per rank

---

## Scores and Quality Thresholds

All thresholds are configurable at pipeline construction time (see [Configurable Parameters](#configurable-parameters)).

| Analysis step | Score | Threshold (default) | Meaning |
|---|---|---|---|
| `backbone` | `ligand_clashes` | must be `== 0` | No ligand atom clashes in backbone |
| `backbone` | `max_ca_deviation` | `< 2.0 Å` | Backbone stays close to diffusion target |
| `backbone` | `ss_fraction` | `> 0.2` | At least 20% secondary structure (helix + sheet) |
| `fastrelax` | `interaction_energy` | `< 0.0 REU` | Favourable protein–ligand interaction energy |
| `fastrelax` | `total_score` | `< 0.0 REU` | Net favourable total Rosetta energy |
| `fastrelax` | `fa_rep` | `< 150.0 REU` | Low steric clash energy after relaxation |
| `interface` | `max_sc` | `>= 0.5` | Shape complementarity at ligand interface |
| `fold` | `best_mean_plddt` | `>= 70.0` | AlphaFold2 confidence in predicted structure |

Sequence analysis (`analysis_sequence`) always sets `pass=True`; routing is handled entirely by the ensemble comparison (see below).

---

## Adaptive Decision Rules

The `adaptive_decision` function in `run_small_molecule_binding.py` runs after every analysis step and sets `pipeline.next_step`. It uses an **ensemble-based selective average** to determine whether the current result is in a productive neighbourhood of the search space.

### Ensemble store

Every analysis task appends a tuple `(type, score, input_path, output_path)` to `pipeline.state['ensemble']`. All entries are kept regardless of pass/fail. The three entry types are:

| Type | Score | Input | Output |
|---|---|---|---|
| `generate backbone` | `ss_fraction` (0–1) | scaffold PDB or `None` | backbone `.cif.gz` |
| `predict sequence` | `overall_confidence` (0–1) | backbone path | FASTA path |
| `fold decoy` | `best_mean_plddt` (0–100) | FASTA path | fold PDB path |

### Selective average check

For a given entry type, the function computes:
1. **`overall_avg`** — mean score across all prior entries of that type
2. **`selective_avg`** — mean score of prior entries whose structural/sequence similarity to the current output is above (or below) the average pairwise similarity

The current result is considered to be in a **productive neighbourhood** when `selective_avg > overall_avg`, i.e. the entries most similar to the current result score better than average.

- **Backbone similarity**: Kabsch-aligned CA-RMSD (lower = more similar). Falls back to simple pass/fail when RMSD data is unavailable (RFdiffusion outputs `.cif.gz`, not `.pdb`).
- **Sequence similarity**: per-position identity fraction (higher = more similar).
- **Fold similarity**: Kabsch-aligned CA-RMSD between ColabFold PDB outputs.

### Step-by-step routing

| After step | Condition | Next step |
|---|---|---|
| `backbone` | quality check failed | `STEP_RFD3` — generate new backbone |
| `backbone` | first attempt (no prior) | `STEP_MPNN` — proceed to sequence design |
| `backbone` | `selective_avg > overall_avg` | `STEP_MPNN` — productive region, continue |
| `backbone` | `selective_avg ≤ overall_avg` | `STEP_RFD3` — unproductive region, retry backbone |
| `backbone` | RMSD unavailable (real mode) | `STEP_MPNN` — fall back to simple pass |
| `sequence` | first attempt (no prior) | `STEP_MPNN` — proceed to packmin |
| `sequence` | `selective_avg > overall_avg` | `STEP_MPNN` (reset retry count) |
| `sequence` | `selective_avg ≤ overall_avg`, retry < 3 | `STEP_RETRY_SEQ` — re-run MPNN same cycle |
| `sequence` | `selective_avg ≤ overall_avg`, retry = 3 | `STEP_RFD3` — abandon backbone, start over |
| `packmin` | always | `STEP_MPNN` — continue refinement cycle |
| `fastrelax` | pass | `STEP_INTERFACE` — run shape complementarity |
| `fastrelax` | fail | `STEP_MPNN` — retry sequence design |
| `interface` | pass | `STEP_AF2` — run fold prediction |
| `interface` | fail | `STEP_MPNN` — retry sequence design |
| `fold` | `selective_avg > overall_avg` | `STEP_RFD3` with `rfd3_input_pdb` set to current fold decoy (guided diffusion) |
| `fold` | otherwise | `STEP_RFD3` with `rfd3_input_pdb = None` (scratch) |

Note: fold analysis never sets `STEP_DONE`. The pipeline terminates exclusively via the task budget check.

---

## User Inputs

Place all input files in `<base_path>/<pipeline_name>_in/` (default: `p1_in/`).

| File | Required | Description |
|---|---|---|
| `ALR_binder_design.json` | Yes | RFdiffusion3 design config (target structure, hotspot residues, diffusion settings) |
| `fixed_residues.txt` | Yes | Space-separated residue indices to hold fixed during MPNN sequence design |
| `<ligand>.params` | Yes | Rosetta ligand parameter file (e.g. `ALR.params`); filename must match `ligand_params` kwarg |
| `<ligand>/` | Yes | Directory containing the ligand PDB/SDF files for shape complementarity analysis (named by `ligand_name`, default `ALR`) |
| `common_filenames.txt` | Yes (filter_energy) | List of accepted filenames for ligand energy filtering |
| `input_pdbs/` | Optional | Target PDB files referenced by the diffusion config |

---

## Configurable Parameters

All parameters are passed as `kwargs` to `PipelineSetup`:

### Paths

| Parameter | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Root directory for all task subdirectories and input files |
| `mpnn_dir` | `/ocean/projects/dmr170002p/hooten/LigandMPNN` | Path to LigandMPNN repository checkout |
| `foundry_sif_path` | `/ocean/projects/dmr170002p/hooten/foundry.sif` | Apptainer SIF image containing RFdiffusion3 |
| `colabfold_path` | `/ocean/projects/dmr170002p/hooten/localcolabfold` | LocalColabFold installation (pixi manifest path) |
| `ligand_params` | `ALR.params` | Ligand parameter filename (relative to `<pipeline_name>_in/`) |

### Pipeline behaviour

| Parameter | Default | Description |
|---|---|---|
| `mock` | `False` | Run with lightweight mock tasks (no HPC tools required) |
| `num_refine_cycles` | `3` | Number of MPNN → PackMin cycles per backbone attempt |
| `mpnn_ensemble_size` | `10` | Number of independent sequence batches on cycle 0 |
| `diffusion_batch_size` | `1` | Number of backbone models to generate per RFdiffusion3 call |
| `max_tasks` | `300` | Total ensemble entries before stopping (counts every backbone, sequence, and fold entry, pass and fail) |

### Quality thresholds

| Parameter | Default | Description |
|---|---|---|
| `backbone_max_ca_deviation` | `2.0` Å | Maximum allowed CA deviation from diffusion target |
| `backbone_min_ss_fraction` | `0.2` | Minimum helix + sheet fraction |
| `fastrelax_max_interact` | `0.0` REU | Maximum protein–ligand interaction energy after relaxation |
| `fastrelax_max_total_score` | `0.0` REU | Maximum total Rosetta score after relaxation |
| `fastrelax_max_fa_rep` | `150.0` REU | Maximum Lennard-Jones repulsion after relaxation |
| `interface_min_sc` | `0.5` | Minimum shape complementarity score |
| `fold_min_plddt` | `70.0` | Minimum mean pLDDT from ColabFold |

---

## Output Structure

Each task creates a numbered directory `<N>_<taskname>/` under `base_path`. The counter `N` increments with every HPC task (rfd3, mpnn, packmin, fastrelax, af2); analysis tasks share the counter with the preceding HPC task.

```
<base_path>/
  <pipeline_name>_in/          # user inputs
  1_rfd3/out/                  # backbone diffusion outputs
  2_mpnn/out/seqs/             # FASTA files with confidence scores
  2_mpnn/out/packed/           # packed PDB structures
  3_packmin/out/               # minimized PDB + score JSON
  ...
  <N>_alphafold/out/           # ColabFold rank PDBs + score JSONs
```

---

## Usage

### Production run (HPC)

Edit the threshold constants and tool paths in `run_small_molecule_binding.py`, then:

```bash
cd examples/small_molecule_binding
python run_small_molecule_binding.py
```

Key variables to set before running:

```python
# run_small_molecule_binding.py
BACKBONE_MAX_CA_DEVIATION = 2.0
BACKBONE_MIN_SS_FRACTION  = 0.2
FASTRELAX_MAX_FA_REP      = 10.0
FASTRELAX_MAX_SCORE       = 0.0
INTERFACE_MIN_SC          = 0.5
FOLD_MIN_PLDDT            = 70.0
```

And in the pipeline kwargs:

```python
"foundry_sif_path": "/path/to/foundry.sif",      # overrides default
"colabfold_path":   "/path/to/localcolabfold",   # overrides default
"mpnn_dir":         "/path/to/LigandMPNN",        # overrides default
"ligand_params":    "YOURLIGAND.params",
"max_tasks":        300,
```

### Mock / dry run (no HPC required)

```bash
cd examples/small_molecule_binding
python run_test_small_molecule_binding.py
```

Mock tasks write placeholder files and hardcode passing metrics, so the full orchestration and adaptive routing logic can be exercised without any external tools. The mock run terminates after 100 ensemble entries (`max_tasks=100`).

---

## Hard-coded Values

The following values are embedded in the code and not exposed as constructor kwargs:

| Location | Value | Description |
|---|---|---|
| `mpnn` task | `--seed 111` | Fixed random seed for LigandMPNN |
| `mpnn` task | `--temperature 0.1` | Sampling temperature for sequence design |
| `mpnn` task | `--number_of_packs_per_design 1` | Side-chain packs per sequence |
| `af2` task | `--random-seed 999` | Fixed random seed for ColabFold |
| `af2` task | `--model-type alphafold2 --rank multimer` | AlphaFold2 multimer ranking |
| `fastrelax` task | `-n 1` | One FastRelax round |
| `_parse_pdb_ca_coords` | `lru_cache(maxsize=512)` | Max cached PDB files for RMSD re-use |
| `adaptive_decision` | retry count `>= 3` | Retries before abandoning backbone on sequence plateau |
| `PYROSETTA_PRE_EXEC` | `source /anvil/scratch/x-mason/env_pyrosetta` | PyRosetta environment activation (Anvil-specific) |
| `AF2_PRE_EXEC` | CUDA + pixi PATH setup | GPU environment for ColabFold (Anvil-specific) |
