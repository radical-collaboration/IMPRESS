# Protein Binding

Location: [`examples/protein_binding/`](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/protein_binding)

An IMPRESS pipeline for iterative computational design of PDZ-domain
protein binders against a target peptide. Starting from a set of input PDZ
PDB structures, the pipeline runs ProteinMPNN sequence design, structure
prediction (Boltz or AlphaFold2), and pLDDT/PTM scoring in a loop. An
adaptive decision function compares per-pass scores and spawns child
pipelines for proteins whose predicted quality degrades, trying the
next-ranked MPNN sequence instead.

## Inputs

Input PDB structures are placed in `<name>_in/` (e.g. `p1_in/`), one file
per target scaffold.

| Parameter | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Root directory for all inputs and outputs |
| `mpnn_path` | cluster-specific path | Path to a ProteinMPNN installation |
| `max_passes` | `4` | Maximum design/predict iterations per pipeline |
| `num_seqs` | `10` | Number of MPNN sequences generated per job |
| `seq_rank` | `0` | Index into ranked sequences to fold (0 = best score) |

No ligand or `.params` files are needed — this is protein-peptide, not
small-molecule, binder design.

## Pipeline Stages

| Task | Type | Script / Tool | Resource |
|---|---|---|---|
| `s1` | HPC | `scripts/s1_mpnn.sh` → `mpnn_wrapper.py` (ProteinMPNN) | GPU |
| `s2` | local | Parses MPNN FASTA output, ranks by score, populates `iter_seqs` | CPU |
| `s3` | local | Writes a paired FASTA (designed sequence + target peptide) per structure | CPU |
| `s4` | HPC | `scripts/s4_boltz.sh` (Boltz, default) or `scripts/s4_alphafold.sh` (AF2, alternate) | GPU |
| `s4_post_exec` | HPC | Stages best-model PDB, confidence JSON, and next-pass MPNN input | CPU |
| `s5` | HPC | `scripts/s5_plddt_extract.sh` → `plddt_extract_pipeline.py` (PyRosetta + BioPandas) | CPU |

`s1` designs Chain `"A"` on pass 1 and redesigns Chain `"B"` on pass 2+
against the previous pass's best-model PDB. `s4`/`s4_post_exec` run
concurrently across all structures in a pass via `asyncio.gather`. `s5`
writes `avg_plddt`, `ptm` (max iPTM+PTM), and `avg_pae` (cross-interface
predicted aligned error) to a per-pass CSV.

## Adaptive Flow

```
s1 (mpnn) --> s2 (rank seqs) --> s3 (write FASTA) --> s4 (structure predict x N, parallel)
                                                                  |
                                                      s4_post_exec (stage files x N, parallel)
                                                                  |
                                                           s5 (pLDDT extract)
                                                                  |
                                                       adaptive_decision()
                                            +--------------------+--------------------+
                                     score improved                              score degraded
                                  (keep in pipeline)                (spawn child pipeline, seq_rank+1)
                                                                  |
                                                        passes += 1 (up to max_passes)
```

`adaptive_decision()` (defined in `run_protein_binding.py`) runs after each
pass:

| Pass | Condition | Action |
|---|---|---|
| Pass 1 | No prior scores | Save current scores as baseline; continue |
| Pass 2+ | `current_score <= previous_score` (improved or held) | Keep the protein in the current pipeline |
| Pass 2+ | `current_score > previous_score` (degraded) | Move the protein to a new child pipeline at `seq_rank + 1` |

When one or more proteins degrade, a child pipeline named
`<parent>_sub<N>` is created: its input directory is populated with the
degraded proteins' best-model PDBs, and it inherits `iter_seqs` (skipping
`s1`/`s2` on its first pass, since sequences already exist) but uses the
next-best MPNN candidate (`seq_rank + 1`). Nesting is capped at
`MAX_SUB_PIPELINES = 3`. If the parent's tracked protein list is emptied
after spawning, it sets `kill_parent = True` and terminates.

## Output Structure

```
<base_path>/
  <name>_in/                                  # input PDB files
  af_pipeline_outputs_multi/<name>/
    mpnn/job_<N>/seqs/                         # MPNN FASTA files for pass N
    af/fasta/                                  # paired FASTAs (designed + peptide)
    af/prediction/best_models/                 # best-model PDB per structure
    af/prediction/best_ptm/                    # iPTM+PTM JSON files
    af/prediction/dimer_models/<name>/         # full Boltz/AF2 outputs
  af_stats_<name>_pass_<N>.csv                 # per-pass scores
```

## Running It

```bash
cd examples/protein_binding
python run_protein_binding.py
```

Place input PDB files in `p1_in/` first, and edit the path constants (e.g.
`mpnn_path`) to match the target system. `run_protein_binding.py` uses
`LocalExecutionBackend(ProcessPoolExecutor())` by default; swap in
`DragonExecutionBackendV3()` for HPC production runs.

Two alternate entry points are also provided:

- **`run_nonadaptive.py`** — the same 16-pipeline setup with no
  `adaptive_fn`, used as a baseline to measure the benefit of the adaptive
  strategy.
- **`protein_binding_run.py`** — replaces the score-comparison predicate
  with a call to Claude (`claude-opus-4-6`), which compares the current
  candidate's metrics against the full prior-ensemble distribution and
  decides whether to refine the current sequence or sample a new one.
  Requires `ANTHROPIC_API_KEY` to be set.
