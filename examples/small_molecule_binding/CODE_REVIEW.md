# Code Review — `examples/small_molecule_binding/`

**Date:** 2026-08-29  
**Scope:** `small_molecule_binding.py`, `run_small_molecule_binding.py`,
`run_nonadaptive.py`, `run_test_small_molecule_binding.py`, `mock.py`, `scripts/`

---

## Bugs

### `filter_shape.py:38` — undefined `sfxn` in RosettaScripts XML

The XML passed to `XmlObjects.create_from_string` references `score_fxn="sfxn"` in the
`ScoreTermValueBased` residue selector, but the `<SCOREFXNS>` block only defines
`sfxn_clean`. Rosetta raises an error at parse time and analysis fails for every PDB.

**Fix:** change the selector to `score_fxn="sfxn_clean"` to match the defined score
function, or add a `sfxn` score function definition.

---

### `rfd3.sh:5-6` — comment swaps `$4`/`$5` argument order

The header comment says `$4=scaffold_arg $5=diffusion_batch_size`, but the actual
positional assignments and the call site in `small_molecule_binding.py` are
`$4=diffusion_batch_size $5=scaffold_arg`. The code is correct; the comment is
misleading and will cause confusion when the script is modified.

---

### `packmin.py:1-22` — old-style `from rosetta.*` imports

Lines 10–22 import from `rosetta.core.*`, `rosetta.protocols.*` etc. (old pre-3.8
binding namespace). Modern PyRosetta exposes these only under `pyrosetta.rosetta.*`.
On Delta (where a current PyRosetta is installed), all of these imports will raise
`ModuleNotFoundError` at startup.

**Fix:** replace all `from rosetta.X import Y` with `from pyrosetta.rosetta.X import Y`
(or remove unused imports — most of the imported symbols are never referenced in the
actual code body).

---

## Potential Issues

### `small_molecule_binding.py:149,152,153` — Anvil-specific hard-coded default paths

```python
self.mpnn_dir       = kwargs.get("mpnn_dir",       "/anvil/projects/x-nairr240405/mason/LigandMPNN")
self.foundry_sif_path = kwargs.get("foundry_sif_path", "/anvil/projects/x-nairr240405/mason/foundry.sif")
self.colabfold_path = kwargs.get("colabfold_path", "/anvil/projects/x-nairr240405/mason/localcolabfold")
```

These defaults silently resolve to non-existent paths on any system other than Anvil
and the tools fail at runtime with no clear error that the path is wrong. Callers on
Delta must remember to override all three via `kwargs` or env vars.

**Recommended fix:** default to `None` and raise a clear `ValueError` in `__init__` if
the path is not supplied. Or at minimum document the required overrides prominently.

---

### `small_molecule_binding.py:367,449,489,605` — analysis tasks infer taskdir from `self.taskcount`

Every analysis task (e.g. `analysis_sequence`) computes its input directory as
`{base_path}/{name}/{self.taskcount}_mpnn/out`. This works only because the
corresponding computation task (`mpnn`) incremented `taskcount` immediately before.
If any other counted task is inserted between computation and analysis, the path
silently points to the wrong directory and the task reads stale or absent files.

---

### `run_small_molecule_binding.py:20`, `run_nonadaptive.py:16` — rhapsody DEBUG logging enabled unconditionally

```python
rhapsody.enable_logging(level=logging.DEBUG)
```

DEBUG-level rhapsody logs every Dragon message exchange. On a multi-pipeline run this
generates thousands of lines per second and buries application output. Both runner
scripts have this unconditional call; it should default to INFO or be gated by an
env variable.

---

### `af2.sh:40` — `--num-models 1` is an integration-only flag

Running with a single model is fast but produces lower-quality predictions. This was
set during integration testing and was not reverted for production. Should either be
removed or made configurable via a script argument.

---

### `mock.py` — taskdir path is missing the pipeline name component

Real task dirs: `{base_path}/{pipeline_name}/{count}_taskname`  
Mock task dirs: `{base_path}/{count}_taskname`

The mock directory structure is inconsistent with the real one. This means mock tests
do not exercise the same path logic as real runs. Any test that checks or mocks the
directory layout will diverge silently from production behavior.

---

## Code Quality

### `small_molecule_binding.py:691` — commented-out `fixed_residues_file` argument

```python
#                    fixed_residues_file=f"{self.pipeline_inputs}/fixed_residues.txt" )
```

The `fixed_residues_file` parameter is accepted by `mpnn()` but never passed in the
refine cycle. Either wire it in or remove the dead parameter and the comment.

---

### `run_small_molecule_binding.py:3` — unused imports

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
```

Neither is used anywhere in the file. Remove them.

---

### `run_small_molecule_binding.py:155` — hardcoded pipeline count (8 pipelines)

```python
for i in range(1, 9)
```

The number of pipelines is baked in as a magic literal. Should be a named constant or
a command-line argument.

---

### `filter_shape.py:6-9` — bare `sys.argv` instead of argparse

Arguments are taken as `sys.argv[1..4]` with no validation. Wrong argument count
causes an unhelpful `IndexError`. Both `fastrelax.py` and `packmin.py` use `argparse`
properly — `filter_shape.py` should too.

---

### `filter_shape.py:18-21`, `118-129` — explicit `.close()` inside `with` blocks

```python
with open(gen_output_file, 'w') as genout:
    genout.write(...)
    genout.close()   # redundant
```

Calling `.close()` inside a `with` block is redundant and confusing — the context
manager closes the file on exit. Remove all explicit `.close()` calls inside `with`
blocks.

---

### `filter_energy.py` — always prints to stdout

Line 45: `print(f"Processed: {pdb_file}, ...")` prints to stdout for every file. When
the subprocess runs with stdout redirected to a log file this ends up in the log, but
if stderr is inspected separately the output is silent. Behaviour is inconsistent with
all other scripts that write only on failure.

---

### `fastrelax.sh:12` — unquoted `$0` in `dirname`

```bash
SCRIPT_DIR="$(dirname $0)"   # wrong
```

Should be `$(dirname "$0")` to handle paths with spaces. `filter_shape.sh` and
`packmin.sh` already use the quoted form — this is the one outlier.

---

### `packmin.py` — large commented-out code blocks

Lines 96–116 contain multi-line commented-out tutorial fragments, original import
notes, and unreachable code. Clean these up before publication.

---

### `mpnn_wrapper.sh` — legacy script, superseded by `mpnn.sh`

`mpnn_wrapper.sh` calls `run.py` directly (bypassing the numpy alias fix in
`mpnn_run.py`), hardcodes `echo "A16" > fixed_residues.txt`, and invokes
`protein_mpnn_run.py` (ProteinMPNN) rather than LigandMPNN's `run.py`. The active
pipeline uses `mpnn.sh` → `mpnn_run.py`. This script is dead code and should be
removed or explicitly marked as deprecated.

---

### `af2.sh:31,36` — diagnostic echo lines remain

Two `echo` lines print to the log file:

```bash
echo "[af2.sh] using colabfold_batch: $colabfold_bin"
echo "[af2.sh] data_dir: $data_dir"
```

Acceptable while debugging, but should be removed or made conditional on a `VERBOSE`
flag before pushing to the shared branch.

---

### `run_nonadaptive.py:56` — commented-out `LocalExecutionBackend` alternative

```python
#backend = await LocalExecutionBackend(ProcessPoolExecutor())
backend = await DragonExecutionBackend()
```

The commented-out local backend is a leftover from development/testing. Remove it to
avoid confusion about which backend is active.

---

### `run_nonadaptive.py:77` — hardcoded pipeline index list

```python
for i in [1,2,4,6,7,8,10,11,12,13,14,15,16,18,19,20,23,26,27,30,32]
```

Like `run_small_molecule_binding.py`'s hardcoded range, the specific protein indices
are baked in with no clear mapping to input files. Should be a named constant or
driven by scanning the input directory.
