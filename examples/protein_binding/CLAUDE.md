# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-04-08 | 09de233 | CLAUDE.md created |
| 2026-04-09 | 25224fa | Boltz logging + FASTA validation in s4_boltz.sh; s4_post_exec task added |
| 2026-04-09 | d46a051 | protein_binding_run.py added (LLM-adaptive runner) |
| 2026-04-18 | 758d868 | Fix post-exec staging cp paths |
| 2026-09-30 | — | s4 is Boltz-2 only; paths moved to env vars; `protein_binding_run.py` removed |

## Context

This directory is an **example workflow** within the larger [IMPRESS framework](https://github.com/radical-collaboration/IMPRESS) (Integrated Machine-learning for PRotEin Structures at Scale). IMPRESS is an HPC framework for protein inverse design using Foundation Models.

The pipeline designs protein binders for PDZ domains against a target peptide (`EGYQDYEPEA`). It iterates over: ProteinMPNN sequence design → structure prediction (Boltz-2) → pLDDT/PTM scoring, with an adaptive function that offloads degraded proteins to child pipelines using the next-ranked MPNN candidate.

The framework package lives at `../../` (two levels up). Install it with:
```shell
cd ../../
pip install .
```

## Running the Pipeline

```shell
python run_protein_binding.py
```

Configuration is entirely through environment variables — no source edits are needed. `MPNN_PATH` is required (the constructor raises `ValueError` without it). `IMPRESS_SCRIPTS_DIR`, `IMPRESS_BASE_DIR`, and `IMPRESS_OUTPUT_DIR` set `base_path`, `input_base_path`, and `output_base_path`; `IMPRESS_BACKEND`, `IMPRESS_N_PIPELINES`, and `IMPRESS_MAX_PASSES` control the run shape. Place input PDB files in `<IMPRESS_BASE_DIR>/prod_in/p1_in/`.

On NCSA Delta, `delta_env_setup.sh` builds the environment (IMPRESS, rhapsody, PyTorch, PyRosetta, a separate Boltz env, pre-computed MSAs) and `sbatch delta_gpu_run.sh` submits the job.

## Architecture

### Runner files

- **`protein_binding.py`** — defines `ProteinBindingPipeline(ImpressBasePipeline)`. Tasks `s1`–`s5` (plus `s4_post_exec`) are registered via `@self.auto_register_task()` inside `register_pipeline_tasks()`. The `run()` method drives a pass loop; `set_up_new_pipeline_dirs()` is called by `adaptive_decision` when spawning a child pipeline. `finalize()` removes proteins moved to a child pipeline from the parent's tracking state.

- **`run_protein_binding.py`** — primary entry point. Defines `adaptive_decision()` (reads CSV, compares scores, spawns child pipelines) and `adaptive_criteria()` (score comparison predicate). Creates an `ImpressManager` and launches via `manager.start(pipeline_setups=[...])`.

- **`run_nonadaptive.py`** — baseline entry point: the same 16 pipelines with no `adaptive_fn`, for measuring what the adaptive strategy buys.

### Pipeline tasks and scripts

| Task | Type | Script / Tool | Resource |
|---|---|---|---|
| `s1` | HPC | `scripts/s1_mpnn.sh` → `mpnn_wrapper.py` (ProteinMPNN) | GPU |
| `s2` | local | parses MPNN FASTA output; ranks by score; populates `iter_seqs` | CPU |
| `s3` | local | writes paired FASTA (designed sequence + peptide) per structure | CPU |
| `s4` | HPC | `scripts/s4_boltz.sh` (Boltz-2) | GPU |
| `s4_post_exec` | local | Python copy of best-model PDB, confidence JSON, and next-pass MPNN PDB from the Boltz output, rewriting chain IDs (`pdz`→`A`, `pep`→`B`) | CPU |
| `s5` | HPC | `scripts/s5_plddt_extract.sh` → `plddt_extract_pipeline.py` (PyRosetta + BioPandas) | CPU |

### Execution flow

The pipeline runs a `while self.passes <= self.max_passes` loop. After `s5`, `run_adaptive_step(wait=True)` calls `adaptive_decision()`. If `kill_parent` is set, the loop exits.

```
while passes <= max_passes:
    if not (is_child and passes == start_pass):
        s1  (ProteinMPNN sequence design)
        s2  (rank sequences)
    s3  (write FASTAs)
    s4             (structure prediction, parallel per structure)  ← asyncio.gather
    s4_post_exec   (stage best-model files, parallel per structure)  ← asyncio.gather
    s5  (pLDDT extraction → CSV)
    adaptive_decision()
    passes += 1
```

Child pipelines skip `s1` and `s2` on their first pass, inheriting `iter_seqs` from the parent.

### Adaptive decision logic

| Condition | Action |
|---|---|
| First pass (no `previous_scores`) | Save current scores; return without changes |
| `current_score <= previous_score` | Protein is improving; keep in current pipeline |
| `current_score > previous_score` | Protein degraded; move to child pipeline (`seq_rank + 1`) |
| `sub_order >= MAX_SUB_PIPELINES` | Max depth reached; do not spawn another child |
| Parent's `fasta_list_2` emptied | Set `kill_parent = True`; parent terminates |

### Child pipeline spawning

`adaptive_decision()` calls `pipeline.submit_child_pipeline_request(new_config)` with:
- `name`: `<parent>_sub<N>` where N = `sub_order + 1`
- `is_child=True`, `start_pass=pipeline.passes` — causes child to skip s1/s2 on first pass
- `seq_rank`: parent's `seq_rank + 1`
- `iter_seqs`: sequences for the degraded proteins only
- `previous_scores`: deep copy of parent's current scores

`pipeline.finalize(sub_iter_seqs)` then removes the moved proteins from the parent's `fasta_list_2` and `current_scores` and updates `previous_scores`.

### Output directory structure

```
<input_base_path>/
  prod_in/<name>_in/                          # input PDB files
<output_base_path>/
  af_pipeline_outputs_multi/<name>/
    mpnn/job_<N>/seqs/                         # MPNN FASTA files for pass N
    af/fasta/                                  # paired FASTAs (designed + peptide)
    af/prediction/best_models/                 # best-model PDB per structure (s5 input)
    af/prediction/best_ptm/                    # iPTM+PTM JSON files (s5 input)
    af/prediction/dimer_models/<name>/         # full Boltz-2 outputs
  af_stats_<name>_pass_<N>.csv               # per-pass scores (output-staged to client)
```

### Inter-step state

Key attributes on the `ProteinBindingPipeline` instance:

| Attribute | Set by | Description |
|---|---|---|
| `iter_seqs` | `s2` | `{structure_name: [[seq, score], ...]}` sorted by score |
| `current_scores` | `adaptive_decision` | `{protein: avg_plddt}` for current pass |
| `previous_scores` | `adaptive_decision` | `{protein: avg_plddt}` from prior pass |
| `fasta_list_2` | `__init__` / `finalize` | List of PDB filenames being tracked |
| `passes` | `run()` | Current pass counter (increments each loop) |
| `seq_rank` | constructor kwarg | Index into ranked sequences to use for folding |
| `sub_order` | constructor kwarg | Depth of this pipeline in the child hierarchy |
| `kill_parent` | `adaptive_decision` | If True, parent exits its pass loop |

### Execution backends

`run_protein_binding.py` selects its backend from `IMPRESS_BACKEND`: `dragon` (the default) uses `rhapsody.backends.DragonExecutionBackend` for multi-node HPC runs, and `local` uses `ConcurrentExecutionBackend(ProcessPoolExecutor())` for single-node development on non-Dragon machines. The runner creates the `WorkflowEngine`, passes it to `ImpressManager`, and shuts it down in a `finally` block.

GPU placement is left to the execution backend — the workflow does not pin tasks to devices.

### Hard-coded values

| Location | Value | Description |
|---|---|---|
| `s3` (`protein_binding.py`) | `"EGYQDYEPEA"` | Fixed target peptide sequence |
| `s3` | `>pdz\|protein` / `>pep\|protein` | FASTA chain labels for Boltz |
| `s1` | Chain `"A"` | Chain to redesign with MPNN (every pass) |
| `adaptive_decision` | `MAX_SUB_PIPELINES = 3` | Maximum child pipeline nesting depth |
| `s4_boltz.sh` | `--use_msa_server` | Opt-in via `BOLTZ_USE_MSA_SERVER=1`; off by default, since compute nodes have no internet. `s3` instead references the MSA cache under `~/boltz/msa_cache` when present, else single-sequence mode |
| `s4_boltz.sh` | `--write_full_pae` | Write full PAE matrix (needed by s5 for avg_pae) |
