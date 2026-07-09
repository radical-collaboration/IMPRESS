# Protein Binding Pipeline

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-04-08 | 09de233 | Initial README rewrite; CLAUDE.md added |
| 2026-04-09 | 25224fa | Boltz logging + FASTA validation in s4_boltz.sh; s4_post_exec task added |
| 2026-04-09 | d46a051 | protein_binding_run.py added (LLM-adaptive runner) |
| 2026-04-18 | 758d868 | Fix post-exec staging cp paths |

---

An IMPRESS pipeline for iterative computational design of PDZ-domain protein binders against a target peptide. Starting from a set of input PDZ PDB structures, the pipeline runs ProteinMPNN sequence design → structure prediction (Boltz or AF2) → pLDDT/PTM scoring in a loop. An adaptive decision function compares per-pass scores and spawns child pipelines for proteins whose predicted quality degrades, trying the next-ranked MPNN sequence instead.

---

## Pipeline Overview

```
s1 (mpnn) ──► s2 (rank seqs) ──► s3 (write FASTA) ──► s4 (structure predict × N, parallel)
                                                                          │
                                                              s4_post_exec (stage files × N, parallel)
                                                                          │
                                                                   s5 (pLDDT extract)
                                                                          │
                                                               adaptive_decision()
                                                    ┌──────────────────┴──────────────────┐
                                             score improved                          score degraded
                                          (keep in pipeline)             (spawn child pipeline, seq_rank+1)
                                                    │
                                            passes += 1 (up to max_passes)
```

Each `adaptive_decision()` call (defined in `run_protein_binding.py`) reads the per-pass CSV, compares current vs. previous pLDDT scores, and decides whether to continue or offload degraded proteins to a new child pipeline.

---

## Transformation Tasks

### `s1` — ProteinMPNN Sequence Design
Designs amino acid sequences for the input PDZ structures using ProteinMPNN.

- **Pass 1**: designs Chain A from PDB files in `<name>_in/`
- **Pass 2+**: redesigns Chain B from best-model PDBs output by the previous pass
- **Script**: `scripts/s1_mpnn.sh` → `mpnn_wrapper.py`
- **HPC**: 1 GPU per rank

### `s2` — Sequence Ranking (local)
Parses the MPNN FASTA output from `s1`, ranks sequences by MPNN score (lower = better), and stores them in `pipeline.iter_seqs` keyed by structure name.

### `s3` — FASTA Preparation (local)
Writes one paired FASTA file per structure for the structure predictor:
- `>pdz|protein`: the designed sequence at rank `seq_rank` from `iter_seqs`
- `>pep|protein`: the hardcoded target peptide `EGYQDYEPEA`

- **Output**: `af/fasta/<structure_name>.fa`

### `s4` — Structure Prediction
Predicts the dimer structure for each (designed sequence, peptide) FASTA. All per-structure tasks are launched in parallel with `asyncio.gather`.

- **Default tool**: Boltz (`scripts/s4_boltz.sh`) using MSA server
- **Alternative**: ColabFold/AF2 (`scripts/s4_alphafold.sh`) — commented out in code
- **Output**: `af/prediction/dimer_models/<name>/boltz_results_<name>/predictions/<name>/` (PDB + PAE files)
- **HPC**: 1 GPU per rank

### `s4_post_exec` — File Staging (HPC)
Copies the best-model outputs from the Boltz prediction directory into the canonical locations consumed by `s5`. Runs in parallel alongside each `s4` task via a second `asyncio.gather`.

- `cp <models_path>/<name>_model_0.pdb → af/prediction/best_models/<name>.pdb`
- `cp <models_path>/confidence_<name>_model_0.json → af/prediction/best_ptm/<name>.json`
- `cp <models_path>/<name>_model_0.pdb → af/prediction/best_models/<name>.pdb` (MPNN input for pass 2+)

### `s5` — pLDDT Extraction
Extracts per-structure quality scores from the structure prediction outputs and writes a per-pass CSV.

- **Script**: `scripts/s5_plddt_extract.sh` → `plddt_extract_pipeline.py` (PyRosetta + BioPandas)
- **Input**: `af/prediction/best_models/` (PDB files), `af/prediction/best_ptm/` (JSON files)
- **Output**: `af_stats_<name>_pass_<passes>.csv` staged back to the client
- **Scores extracted**:

| Column | Description |
|---|---|
| `avg_plddt` | Mean per-residue pLDDT from backbone B-factors (0–100) |
| `ptm` | Max iPTM+PTM from AlphaFold/Boltz JSON (0–1) |
| `avg_pae` | Cross-interface predicted aligned error (Å, lower = better) |

---

## Adaptive Decision Rules

The `adaptive_decision` function in `run_protein_binding.py` runs after each pass and decides whether to continue or spawn a child pipeline.

| Pass | Condition | Action |
|---|---|---|
| Pass 1 | First pass — no prior scores | Save current scores as baseline; continue |
| Pass 2+ | `current_score <= previous_score` (improved or held) | Keep protein in current pipeline |
| Pass 2+ | `current_score > previous_score` (degraded) | Move protein to a new child pipeline (`seq_rank + 1`) |

### Child pipeline spawning

When one or more proteins degrade:
1. A new pipeline named `<parent>_sub<N>` is created (directories set up automatically).
2. The degraded proteins' best-model PDBs are copied to `<new_name>_in/`.
3. The child pipeline inherits `iter_seqs` (ranked sequences) and starts at the same pass number, skipping `s1`/`s2` on its first pass (since sequences were already generated).
4. The child pipeline uses `seq_rank + 1` — the next-best MPNN candidate.
5. Maximum nesting depth: 3 child pipelines (`MAX_SUB_PIPELINES = 3`).
6. If the parent's structure list is emptied after spawning, it sets `kill_parent = True` and terminates.

---

## Configurable Parameters

All parameters are passed as `kwargs` to `ProteinBindingPipeline`:

| Parameter | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Root directory for all inputs and outputs |
| `mpnn_path` | `/ocean/projects/dmr170002p/hooten/ProteinMPNN` | Path to ProteinMPNN installation |
| `max_passes` | `4` | Maximum design → predict iterations per pipeline |
| `num_seqs` | `10` | Number of MPNN sequences to generate per job |
| `seq_rank` | `0` | Index into ranked sequences to fold (0 = best score) |

---

## Output Structure

```
<base_path>/
  <name>_in/                                  # input PDB files (one per target structure)
  af_pipeline_outputs_multi/<name>/
    mpnn/job_1/seqs/                           # pass 1 MPNN FASTA files (one per structure)
    mpnn/job_2/seqs/                           # pass 2 MPNN FASTA files
    af/fasta/                                  # paired FASTAs (designed sequence + peptide)
    af/prediction/best_models/                 # best-model PDB per structure (for s5)
    af/prediction/best_ptm/                    # iPTM+PTM JSON files (for s5)
    af/prediction/dimer_models/<name>/         # full Boltz/AF2 prediction outputs
  af_stats_<name>_pass_<N>.csv               # pLDDT/ptm/pae scores for pass N
```

---

## Hard-coded Values

| Location | Value | Description |
|---|---|---|
| `s3` (`protein_binding.py`) | `"EGYQDYEPEA"` | Fixed target peptide sequence |
| `adaptive_decision` | `MAX_SUB_PIPELINES = 3` | Maximum child pipeline depth |
| `s1` | Chain `"A"` on pass 1, `"B"` on pass 2+ | MPNN chain to redesign |
| `s4_boltz.sh` | `--use_msa_server` | MSA lookup enabled for Boltz predictions |
| `s4_boltz.sh` | `--write_full_pae` | Full PAE matrix written to output |

---

## Usage

### Production run (HPC)

Place input PDB files in `p1_in/`, then edit the path constants in `run_protein_binding.py` (e.g. `mpnn_path`) to match the target system:

```bash
cd examples/protein_binding
python run_protein_binding.py
```

Key variables to set before running:

```python
# in run_protein_binding.py / ProteinBindingPipeline kwargs
"mpnn_path": "/path/to/ProteinMPNN",
"max_passes": 4,
"num_seqs": 10,
```

### Execution backend

`run_protein_binding.py` has `LocalExecutionBackend(ProcessPoolExecutor())` active by default. `DragonExecutionBackendV3()` is commented out — swap it in for HPC production runs.

### LLM-adaptive runner

`protein_binding_run.py` is an alternative entry point that replaces the score-comparison predicate with a Claude LLM call. After each pass it sends the current candidate metrics and the full prior-ensemble distribution to `claude-opus-4-6`, which responds with either `"The current sequence should be refined."` or `"A new sequence should be sampled."` Requires `ANTHROPIC_API_KEY` to be set.
