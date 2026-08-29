# Code Review — `examples/protien_binding_usecase/`

**Date:** 2026-08-29  
**Scope:** `run_protein_binding.py`, `mpnn_wrapper.py`,
`plddt_extract_pipeline.py`, `af2_multimer_reduced.sh`, `delta_gpu_run.sh`

---

## Bugs

### `mpnn_wrapper.py:1` — Python file with `#!/bin/sh` shebang

Line 1 is `#!/bin/sh`, making the OS attempt to execute a Python file as a POSIX
shell script. Any direct execution of `./mpnn_wrapper.py` produces a parse error at
the first Python statement. The file should have `#!/usr/bin/env python3` or no
shebang at all.

---

### `mpnn_wrapper.py:18` — `--temp` argument parses temperature as `int` instead of `float`

```python
parser.add_argument("-temp", "--temp", ..., type=int, default=0.1)
```

`type=int` truncates `0.1` to `0`. Every invocation that relies on the default (or
passes a fractional temperature) gets temperature `0`, which collapses the sampling
distribution to greedy argmax. `type=float` is required.

---

### `plddt_extract_pipeline.py:122` — division by zero if `counter2` is 0

```python
avg_pae = running_sum / counter2
```

`counter2` counts PAE matrix cells where exactly one of `row_index` / `col_index`
falls in `target_range`. If `target_range` is empty (protein shorter than 10 residues)
or the PAE matrix is empty, `counter2` stays 0 and this line raises `ZeroDivisionError`.

---

## Potential Issues

### `run_protein_binding.py:50` — adaptive function reads CSV from current working directory

```python
file_name = f'af_stats_{pipeline.name}_pass_{pipeline.passes}.csv'
with open(file_name) as fd:
```

This path is relative to wherever the process was started (typically the script
directory). If the working directory is wrong or if AF2 fails and the file was never
written, this raises `FileNotFoundError` and crashes the adaptive function, leaving
the pipeline in an undefined state. Should use an absolute path based on `pipeline.base_path`
and wrap with `try/except`.

---

### `run_protein_binding.py:15` — `adaptive_criteria` declared `async` with no awaits

```python
async def adaptive_criteria(current_score: float, previous_score: float) -> bool:
    return current_score > previous_score
```

This function does no I/O or async work. Declaring it `async` adds unnecessary
overhead at every call site. Make it a plain `def`.

---

### `plddt_extract_pipeline.py` — incompatible with current IMPRESS output structure

`on_replica_done` in the current campaign (`sm_binding_workflow.py`) reads
`binder_scores_*.json` directly from the alphafold output directory. This script reads
from `af_pipeline_outputs_multi/{name}/af/prediction/best_models` — a directory tree
that the current pipeline does not create. This script is effectively stale and will
produce empty / zero results if run against current outputs.

---

### `delta_gpu_run.sh:5,44` — SBATCH requests 4 tasks but runs single-node Dragon

```
#SBATCH --tasks-per-node=4
...
dragon -s run_protein_binding.py
```

`dragon -s` is single-node mode. Requesting 4 tasks-per-node wastes resources and
may confuse the scheduler. For true multi-node, change to `dragon -m`; for
single-node, change `--tasks-per-node=1`.

---

### `delta_gpu_run.sh:21` — unguarded `LD_LIBRARY_PATH` produces trailing colon

```bash
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH}
```

If `LD_LIBRARY_PATH` is unset, this expands to a trailing `:`, which adds the current
directory to the dynamic linker search path — a security risk. Should be
`${LD_LIBRARY_PATH:-}`.

---

## Code Quality

### `mpnn_wrapper.py` — massive duplicated subprocess.call blocks

The file's 140 lines handle 12+ scenario combinations (monomer/multimer ×
fixed/unfixed × tied/homomer/interface) through deeply nested `if/else` with nearly
identical `subprocess.call` lists. The only differences are which `--*_jsonl` flags
are appended. Refactor to build the argument list incrementally and call
`subprocess.call` once.

---

### `mpnn_wrapper.py` — not used by the current pipeline

The active pipeline calls `mpnn.sh` → `mpnn_run.py` → LigandMPNN's `run.py`.
`mpnn_wrapper.py` calls `protein_mpnn_run.py` (ProteinMPNN, not LigandMPNN) via a
completely different argument schema. This file is dead code relative to the current
pipeline and should be either removed, labelled as a standalone utility, or replaced
with a properly integrated version.

---

### `mpnn_wrapper.py:30-40` — `chains == None` instead of `chains is None`

```python
if chains == None:
    chains = 'A'
```

PEP 8 and Python convention require `if chains is None:`. The `==` form works for
`None` but is non-idiomatic and triggers linter warnings.

---

### `run_protein_binding.py:75` — typo in log message

```python
pipeline.logger.pipeline_log(f'Adaptive descision: {decision}')
```

"descision" → "decision".

---

### `run_protein_binding.py:39` — `eval` for venv activation

```bash
eval "$IMPRESS_PRE_EXEC"
```

(in `delta_gpu_run.sh` line 39) Running an env-supplied string through `eval` allows
arbitrary code execution if `IMPRESS_PRE_EXEC` is set adversarially or incorrectly.
Replace with a direct `source` of the known venv path.

---

### `plddt_extract_pipeline.py:74` — unclosed file handle

```python
data = json.load(open(data_path))
```

The file handle is never closed. Should use `with open(data_path) as f: json.load(f)`.

---

### `plddt_extract_pipeline.py` — extensive commented-out code

Lines 56–60 (biopandas block), 83–92 (`df_json`), 95–100 (print block), and 103–107
(debug prints) are commented-out code that was never removed. These should be deleted
to improve readability.

---

### `plddt_extract_pipeline.py` — manual index tracking instead of `enumerate`

Lines 111–122 use manual `row_index`/`col_index` variables incremented in loop bodies
to track which matrix cell is being accessed. Using `enumerate` would be clearer and
less error-prone.

---

### `af2_multimer_reduced.sh:13-14` — `/tmp/work` and `/tmp/upper` created but never used

```bash
WORK=/tmp/work
UPPER=/tmp/upper
mkdir -p $WORK $UPPER
```

These directories are never referenced in the apptainer call. Leftover from a prior
overlay filesystem approach. Remove.

---

### Directory name typo: `protien_binding_usecase`

The directory is named `protien_binding_usecase` (protein misspelled). The companion
`IMPRESS/src/impress/pipelines/protein_binding.py` is spelled correctly. For new
branches, consider renaming to `protein_binding_usecase` to avoid confusion, although
this changes an established path.
