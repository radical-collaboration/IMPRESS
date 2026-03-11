# impress-flowgentic (example)

A self-contained example of an adaptive, agentic protein binder design pipeline built on
[LangGraph](https://github.com/langchain-ai/langgraph) and RADICAL AsyncFlow. It mirrors
the behavior of the IMPRESS HPC workflow but runs locally with deterministic mocks in
place of ProteinMPNN and AlphaFold.

---

## Purpose

The pipeline automates iterative protein binder design for PDZ-domain targets. Given a
set of input backbone structures it:

1. Predicts candidate backbones
2. Designs amino-acid sequences for each backbone
3. Folds the best candidate together with the target peptide
4. Scores the fold (PAE, pLDDT, pTM)
5. Decides—after every pass—whether to spawn a child pipeline that tries the next-ranked
   sequence on any targets that are degrading

All compute-intensive steps are replaced with deterministic mocks so the full adaptive
logic can be exercised without GPU resources.

---

## Directory layout

```
impress-flowgentic/
├── impress_flowgentic/
│   ├── __init__.py          # public API exports
│   ├── base.py              # FlowgenticImpressBasePipeline (ABC, async comms)
│   ├── pipeline.py          # ProteinBindingFlowgenticPipeline + LangGraph pass graph
│   ├── adaptive.py          # adaptive_decision() — child-spawning logic
│   ├── manager.py           # FlowgenticImpressManager — async event loop
│   ├── runner.py            # run_impress_flowgentic() entry point
│   ├── setup.py             # PipelineSetup dataclass
│   ├── state.py             # Pydantic models: PassState, SequenceScore, EnsembleRecord
│   ├── mocks.py             # deterministic stubs for backbone/sequence/fold steps
│   └── io.py                # filesystem helpers + ensemble provenance store
├── scripts/
│   └── run_impress_flowgentic.py   # CLI entry point
└── workspace/               # generated run artifacts (written at runtime)
    ├── af_pipeline_outputs_multi/
    │   └── <pipeline>/
    │       └── af/{fasta,prediction/{best_models,...},mpnn/}
    ├── ensemble/
    │   └── <pipeline>_records.jsonl   # EnsembleRecord provenance log
    └── run_summary.json
```

---

## Adaptive workflow

### Overview

The pipeline runs as a collection of concurrent `asyncio.Task`s managed by
`FlowgenticImpressManager`. Each task drives one `ProteinBindingFlowgenticPipeline`
instance through repeated design passes. After every pass the manager invokes
`adaptive_decision()`, which may spawn new child pipelines for targets that are not
improving.

```
Manager
  │
  ├─ Pipeline p1  ──pass 1──▶ pass 2 ──▶ pass 3 ──▶ …
  │                                │
  │                         adaptive_decision
  │                                │  protein_b degrading
  │                                ▼
  └─ Pipeline p1_sub1 (seq_rank+1, inherits protein_b)
```

### Per-pass LangGraph graph

Each pass is a `StateGraph(PassState)` with analysis-gated routing:

```
START
  └─▶ prepare_pass
        │
        ├─ [skip_design=True] ──────────────────────────────────┐
        │                                                        │
        └─ [skip_design=False]                                   │
              └─▶ mock_backbone_prediction                       │
                    └─▶ analyze_backbone                         │
                          └─▶ mock_sequence_prediction           │
                                └─▶ analyze_sequence             │
                                      └─▶ mock_fold_prediction ◀─┘
                                              └─▶ analyze_fold
                                                      └─▶ END
```

**Node responsibilities:**

| Node | What it does |
|---|---|
| `prepare_pass` | Logs pass metadata; sets `skip_design=True` on child's first pass (sequences already chosen) |
| `mock_backbone_prediction` | Generates mock backbone structures for each active target; writes provenance `EnsembleRecord`s |
| `analyze_backbone` | Inspects backbone scores; routes to `mock_sequence_prediction` (currently weight=1.0) |
| `mock_sequence_prediction` | Runs mock ProteinMPNN; writes ranked `.fa` files; parses back into `iter_seqs` |
| `analyze_sequence` | Selects sequence at `seq_rank`; writes `af/fasta/<target>.fa`; routes to fold (weight=1.0) |
| `mock_fold_prediction` | Runs mock AlphaFold multimer for all FASTA targets concurrently (`asyncio.gather`) |
| `analyze_fold` | Computes mock PAE/pLDDT/pTM metrics; writes per-pass CSV; updates `current_scores` and `score_history`; routes to END (weight=1.0) |

The routing weights (`BACKBONE_ROUTING_PROBS`, `SEQUENCE_ROUTING_PROBS`,
`FOLD_ROUTING_PROBS`) are all currently set to 1.0 for a deterministic forward pass, but
the conditional-edge infrastructure supports probabilistic loops for iterative refinement
within a single pass.

### Adaptive decision logic (`adaptive.py`)

After pass ≥ 2, `adaptive_decision()` checks each target's score trajectory:

```
if current_score > previous_score + degradation_threshold:
    → target is degrading
```

If any targets are degrading **and** the sub-pipeline depth limit has not been reached
**and** there are higher-ranked sequences still to try:

1. A new directory scaffold (`<parent>_sub<N>`) is created.
2. The best-model PDB is copied into the child's `_in/` directory.
3. A `PipelineSetup` is submitted via `pipeline.submit_child_pipeline_request()` with
   `seq_rank + 1`, `is_child=True`, and inherited `score_history`.
4. `pipeline.finalize()` removes the migrated targets from the parent's work set.
5. If the parent has no targets left it sets `kill_parent = True` and exits.

### Manager event loop (`manager.py`)

`FlowgenticImpressManager.start()` runs an `asyncio` loop that:

- Detects when a pipeline signals `invoke_adaptive_step` and fires `adaptive_decision()`
  as a concurrent task without blocking the pipeline.
- Drains each pipeline's child-request mailbox and buffers new `PipelineSetup`s.
- Cancels tasks whose `kill_parent` flag is set.
- Submits buffered child pipelines when space allows.
- Writes `workspace/run_summary.json` when all tasks are complete.

### Provenance tracking

Every design step appends an `EnsembleRecord` to `workspace/ensemble/<pipeline>_records.jsonl`:

```python
EnsembleRecord(
    target      = "protein_a",
    step_index  = 3,
    type        = "sequence",   # backbone | sequence | decoy
    score       = 0.47,
    input_ref   = "path/to/input.pdb",
    output_ref  = "path/to/output.fa",
)
```

This provides a full trajectory of every backbone, sequence, and fold decision across
all passes and child pipelines.

### Configuration knobs (`runner.py`)

| Parameter | Default | Meaning |
|---|---|---|
| `max_passes` | 4 | Maximum design iterations per pipeline |
| `num_seqs` | 6 | Sequence candidates generated per target per pass |
| `seq_rank` | 0 (parent), +1/child | Which ranked sequence to pass to AlphaFold |
| `max_sub_pipelines` | 3 | Maximum child-spawning depth |
| `degradation_threshold` | 0.12 | PAE increase that triggers child spawning |

---

## Running

```bash
cd examples/impress-flowgentic
python scripts/run_impress_flowgentic.py
```

Artifacts are written under `workspace/`. The mock score generator causes `protein_b` to
degrade on the parent pipeline, triggering a child pipeline `p1_sub1` that inherits
`protein_b` and tries `seq_rank=1`.

---

## Comparison with `/home/mason/exdrive/rad/impress-flowgentic`

The upstream repository at `/home/mason/exdrive/rad/impress-flowgentic` is the original
implementation from which this example evolved. The table below summarises the key
architectural differences.

| Aspect | upstream (`/rad/impress-flowgentic`) | this example (`feature/agentic_workflow`) |
|---|---|---|
| **Pass graph topology** | Linear 6-node DAG | Analysis-gated 7-node DAG with conditional edges |
| **Backbone prediction** | Absent — ProteinMPNN operates directly on input PDBs | Added: `mock_backbone_prediction` + `analyze_backbone` node |
| **Sequence node** | `mock_mpnn` (generates + writes FASTA) | `mock_sequence_prediction` (same role, now preceded by backbone step) |
| **Fold node** | `build_fasta` + `mock_alphafold` as two separate nodes | `mock_fold_prediction` combines both into one node |
| **Scoring node** | `mock_plddt_extract` | `analyze_fold` (same role, richer state output) |
| **Routing** | Fixed linear edges only | Probabilistic routing tables (`*_ROUTING_PROBS`) + `conditional_edges` |
| **Provenance** | None | `EnsembleRecord` + `trajectory` list in `PassState` + JSONL ensemble store |
| **`state.py`** | `PassState` + `SequenceScore` | Adds `EnsembleRecord`, `current_route`, `trajectory`, `backbone_refs`, `backbone_scores`, `ensemble_store_path` |
| **`mocks.py`** | `_stable_hash` (private) | `stable_hash` (public) + `generate_mock_backbone` |
| **`io.py`** | Directory scaffolding only | Adds `ensure_ensemble_store`, `append_ensemble_records`, `load_ensemble` |
| **`adaptive.py`** | Identical | Identical |
| **`manager.py`** | Identical | Identical |
| **`runner.py`** | Identical | Identical |
| **README** | Present | This file |

### Design philosophy shift

The upstream version treats a design pass as a simple pipeline: MPNN → rank → fold →
score. The example version introduces an **intermediate backbone stage** and wraps every
prediction step in an **analysis node** that can route the graph differently based on
results. This mirrors real computational protein design workflows where backbone geometry
is evaluated before committing to sequence design, and where poor intermediates can be
re-tried within the same pass rather than waiting for the next one.

The probabilistic routing infrastructure (`*_ROUTING_PROBS` dicts) is currently set to
deterministic forward-only weights (all 1.0), making the two implementations behaviorally
equivalent for the mock scenario. The value of the new design is that swapping in a
learned or heuristic routing policy—without restructuring the graph—is straightforward.

The provenance / ensemble-tracking additions (`EnsembleRecord`, JSONL store) address a
gap in the upstream repo: there was no record of which backbone was used for which
sequence design, or how trajectories branched across child pipelines. The example repo
makes the full decision history queryable after a run.
