# impress-flowgentic

Recreation of the IMPRESS protein-binding workflow using **LangGraph** (workflow definition) and **Flowgentic** (execution via RADICAL AsyncFlow), with **mocked heavy tools** for AlphaFold and ProteinMPNN.

## Table of Contents

1. [Overview](#overview)
2. [Goals and Scope](#goals-and-scope)
3. [How This Mirrors IMPRESS](#how-this-mirrors-impress)
4. [Architecture](#architecture)
5. [Program Structure](#program-structure)
6. [Workflow Execution Details](#workflow-execution-details)
7. [Mock Tool Behavior](#mock-tool-behavior)
8. [Adaptive Logic](#adaptive-logic)
9. [Run Instructions](#run-instructions)
10. [Expected Artifacts](#expected-artifacts)
11. [Observed Run Results](#observed-run-results)
12. [Troubleshooting](#troubleshooting)
13. [Limitations and Next Steps](#limitations-and-next-steps)

## Overview

`impress-flowgentic` reproduces the behavior of IMPRESS protein-binding pipelines in a local runnable form:

- Multi-pass pipeline execution.
- Sequence design + ranking stage.
- Structure prediction stage per target.
- Score extraction stage (`af_stats_<pipeline>_pass_<n>.csv`).
- Adaptive child-pipeline spawning when targets degrade.

The project intentionally mocks expensive external tools (AlphaFold and MPNN), but keeps their data contracts and output directory conventions so the workflow resembles real IMPRESS execution.

## Goals and Scope

### Goals

- Recreate IMPRESS adaptive pipeline semantics using **Flowgentic + LangGraph**.
- Keep artifact paths and pass-level outputs compatible with IMPRESS expectations.
- Make the whole workflow runnable locally and observable via produced files.

### Non-goals

- Running real AlphaFold.
- Running real ProteinMPNN.
- Integrating HPC scheduler-specific runtime configs.

## How This Mirrors IMPRESS

This implementation follows IMPRESS behavior at three levels:

1. **Manager semantics**
   - Tracks active pipelines, adaptive tasks, and spawned children.
   - Submits child pipelines dynamically.
   - Supports parent termination once work is migrated.

2. **Pipeline semantics**
   - Multi-pass loop with per-pass execution.
   - Child pipelines skip design/ranking on first inherited pass.
   - Pipeline keeps `iter_seqs`, `score_history`, `current_scores`, and pass counters.

3. **Artifact semantics**
   - Produces IMPRESS-like layout under `af_pipeline_outputs_multi/<pipeline>/...`.
   - Produces `af_stats_<pipeline>_pass_<n>.csv` files.
   - Copies migrated targets into `<child>_in/`.

## Architecture

### High-level components

- **FlowgenticImpressManager**
  - Coordinates pipeline lifecycle and adaptive execution.
  - File: `impress_flowgentic/manager.py`

- **ProteinBindingFlowgenticPipeline**
  - Implements pass loop.
  - Compiles/executes LangGraph for each pass.
  - File: `impress_flowgentic/pipeline.py`

- **Adaptive policy**
  - Detects degraded targets and requests child pipeline spawning.
  - File: `impress_flowgentic/adaptive.py`

- **Mock tool layer**
  - Backbone, sequence, and fold prediction simulators with deterministic outputs.
  - File: `impress_flowgentic/mocks.py`

- **I/O helpers**
  - Seeds input PDBs and output directory tree.
  - File: `impress_flowgentic/io.py`

### Per-pass LangGraph

Each pass uses a `StateGraph(PassState)` with nodes wrapped by Flowgentic execution wrappers (`AsyncFlowType.EXECUTION_BLOCK`). Nodes are organized as **data/analysis pairs**:

1. `prepare_pass`
2. `mock_backbone_prediction` → `analyze_backbone`
3. `mock_sequence_prediction` → `analyze_sequence`
4. `mock_fold_prediction` → `analyze_fold`

**Routing** is probabilistic via `_sample_route()`, driven by three hard-coded tables:
`BACKBONE_ROUTING_PROBS`, `SEQUENCE_ROUTING_PROBS`, `FOLD_ROUTING_PROBS`.

Each analysis node writes `current_route` into state; conditional edges read it to determine the next data-transformation node (or `END`). This design supports future multi-path looping within a single pass.

**Default pass flow** (current probability tables set to single-path):

```
prepare_pass
  → mock_backbone_prediction → analyze_backbone
  → mock_sequence_prediction → analyze_sequence
  → mock_fold_prediction     → analyze_fold
  → END
```

**When `skip_design=True`** (child pipeline, first inherited pass):

```
prepare_pass → mock_fold_prediction → analyze_fold → END
```

`current_route` is the key state field: analysis nodes write it, router functions read it.

## Program Structure

```text
impress-flowgentic/
├── impress_flowgentic/
│   ├── __init__.py
│   ├── adaptive.py
│   ├── base.py
│   ├── io.py
│   ├── manager.py
│   ├── mocks.py
│   ├── pipeline.py
│   ├── runner.py
│   ├── setup.py
│   └── state.py
├── scripts/
│   └── run_impress_flowgentic.py
├── workspace/                       # generated run artifacts
│   ├── ensemble/
│   │   ├── p1_records.jsonl
│   │   └── p1_sub1_records.jsonl
│   └── af_pipeline_outputs_multi/
├── pyproject.toml
└── README.md
```

## Workflow Execution Details

1. Runner seeds initial inputs (`p1_in/*.pdb`) and required output directories.
2. Manager starts `p1` pipeline.
3. Pipeline executes pass graph for each pass up to `max_passes`.
4. After each pass, pipeline triggers adaptive step.
5. Adaptive function may spawn child pipeline (`p1_sub1`, etc.) with degraded targets only.
6. Manager continues until all parent/child pipelines complete.
7. Manager writes summary report to `workspace/run_summary.json`.

## Mock Tool Behavior

### Mock Backbone Prediction (`mock_backbone_prediction`)

- Generates a mock backbone structure reference string for each active target.
- Stores results in `backbone_refs` (target → backbone id string).

### Mock Sequence Prediction (`mock_sequence_prediction`)

- Generates candidate sequences per target/pass.
- Writes files compatible with the ranking parser:
  - `.../mpnn/job_<pass>/seqs/<target>.fa`
- Stores results in `iter_seqs` (target → list of `SequenceScore`).

### Mock Fold Prediction (`mock_fold_prediction`)

- Builds FASTA inputs for the top-ranked sequence per target.
- Produces per-target dimer model outputs:
  - `.../af/prediction/dimer_models/<target>/...`
- Copies selected files into:
  - `.../af/prediction/best_models/<target>.pdb`
  - `.../af/prediction/best_ptm/<target>.json`
  - `.../mpnn/job_<pass>/<target>.pdb`

### Analysis nodes (`analyze_backbone`, `analyze_sequence`, `analyze_fold`)

- Each analysis node computes per-target metrics and writes `current_route` to state.
- `analyze_backbone`: scores backbone structures; appends `backbone` records to the in-memory trajectory.
- `analyze_sequence`: ranks sequences from the MPNN output directory; appends `sequence` records.
- `analyze_fold`: computes pLDDT/PAE metrics; writes `workspace/af_stats_<pipeline>_pass_<n>.csv`; appends `decoy` records; **flushes the completed trajectory to the ensemble store** (`workspace/ensemble/<pipeline>_records.jsonl`).

## Ensemble Store

Each pipeline maintains a per-run JSONL file at `workspace/ensemble/<pipeline>_records.jsonl`.

- **Initialized** at pipeline start via `io.ensure_ensemble_store()`; any previous file for that pipeline is cleared.
- **Flushed** after each pass: `analyze_fold` calls `io.append_ensemble_records()` with the full `PassState.trajectory`.
- Each line is one `EnsembleRecord` JSON object with fields:
  - `target` — protein target identifier
  - `step_index` — position in the within-pass trajectory
  - `type` — `backbone` | `sequence` | `decoy`
  - `score` — numeric quality score
  - `input_ref` — output_ref of the preceding step (or `"START"`)
  - `output_ref` — identifier or path for this step's output
  - `pipeline_name` — pipeline that produced the record
  - `pass_index` — pass that produced the record
- Provides a full per-target trajectory across all passes of a run.
- Loadable via `io.load_ensemble(store_path)`.

`PassState` also carries `ensemble_store_path` (set at pipeline init, constant for the lifetime of a pipeline).

## Adaptive Logic

Adaptive policy intentionally mimics IMPRESS-style behavior:

1. Wait until at least pass 2.
2. Compare latest score vs previous score for each target.
3. If degradation exceeds threshold, migrate target to child pipeline.
4. Child pipeline inherits context (`score_history`, pass number, etc.) and increments `seq_rank`.
5. Parent finalizes by removing migrated targets from local work set.
6. Parent may terminate if no targets remain.

## Run Instructions

### Prerequisites

- Python 3.10+.
- `git` available (dependencies are installed from Git repositories).

### Recommended command

```bash
cd /Users/yamirghofran0/STRIDE/impress-flowgentic
uv sync
uv run python scripts/run_impress_flowgentic.py
```

### Alternative

```bash
cd /Users/yamirghofran0/STRIDE/impress-flowgentic
python -m venv .venv
source .venv/bin/activate
pip install .
python scripts/run_impress_flowgentic.py
```

### Optional local-development override

If you want to test against a local Flowgentic checkout instead of Git-installed package versions:

```bash
pip install -e ../flowgentic
```

## Expected Artifacts

After a run, inspect:

- `workspace/run_summary.json`
- `workspace/af_stats_p1_pass_*.csv`
- `workspace/af_stats_p1_sub1_pass_*.csv` (if child spawned)
- `workspace/ensemble/p1_records.jsonl`
- `workspace/ensemble/p1_sub1_records.jsonl` (if child spawned)
- `workspace/p1_in/*.pdb`
- `workspace/p1_sub1_in/*.pdb` (if child spawned)
- `workspace/af_pipeline_outputs_multi/p1/...`
- `workspace/af_pipeline_outputs_multi/p1_sub1/...` (if child spawned)

Typical directory shape:

```text
workspace/
├── ensemble/
│   ├── p1_records.jsonl
│   └── p1_sub1_records.jsonl
├── af_pipeline_outputs_multi/
│   ├── p1/
│   │   ├── af/
│   │   └── mpnn/
│   └── p1_sub1/
│       ├── af/
│       └── mpnn/
├── af_stats_p1_pass_1.csv
├── af_stats_p1_pass_2.csv
├── af_stats_p1_pass_3.csv
├── af_stats_p1_pass_4.csv
├── af_stats_p1_sub1_pass_2.csv
├── af_stats_p1_sub1_pass_3.csv
├── af_stats_p1_sub1_pass_4.csv
├── p1_in/
├── p1_sub1_in/
└── run_summary.json
```

## Observed Run Results

A validated run produced:

- `p1` completed all configured passes.
- One adaptive spawn occurred: `p1 -> p1_sub1` on parent pass 3.
- `p1_sub1` completed inherited passes.
- No pipeline errors reported.

Example summary (`workspace/run_summary.json`):

```json
{
  "completed_pipelines": [
    {"name": "p1", "status": "completed", "passes_executed": 4, "remaining_targets": 1, "error": null},
    {"name": "p1_sub1", "status": "completed", "passes_executed": 4, "remaining_targets": 2, "error": null}
  ],
  "spawn_requests": [
    {"parent": "p1", "child": "p1_sub1", "pass": 3}
  ]
}
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'flowgentic'`

Install project dependencies first:

```bash
uv sync
```

### No child pipeline spawned

Adaptive spawning depends on score trajectories and threshold. Check:

- `degradation_threshold` in `impress_flowgentic/runner.py`
- Generated scores in `workspace/af_stats_*.csv`

### Existing artifacts from previous runs

This workflow reuses `workspace/` paths. If you want a clean run, remove or rename `workspace/` before running.

## Limitations and Next Steps

### Current limitations

- Tools are mocks, not actual AlphaFold/MPNN integrations.
- Runtime currently uses local concurrent backend, not cluster-specific backends.

### Suggested next steps

1. Replace mock sequence prediction (`mock_sequence_prediction`) with a real ProteinMPNN wrapper.
2. Replace mock fold prediction (`mock_fold_prediction`) with a real AlphaFold execution command/staging.
3. Add tests for adaptive branching and artifact contracts.
4. Add optional telemetry artifact generation through Flowgentic introspection APIs.

---

This project is a faithful behavioral prototype of IMPRESS adaptive orchestration, implemented with Flowgentic + LangGraph and ready to evolve into real tool integrations.
