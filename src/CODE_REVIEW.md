# IMPRESS `src/` Code Review

**Date:** 2026-08-29  
**Scope:** `/scratch/bblj/mgoliyad1/IMPRESS/src/impress/`  
**Status:** bugs marked ✅ fixed or ⚠️ open

---

## Bugs

### ✅ `impress_manager.py:164` — `kill_parent` path crashes on unpack

When a pipeline sets `kill_parent=True`, the manager appended the bare `pipeline`
object to `completed_pipelines`:

```python
completed_pipelines.append(pipeline)   # was wrong
```

The cleanup loop unpacks `for pipeline, future in completed_pipelines:`, so this
raises `ValueError: not enough values to unpack` the moment any pipeline is killed.

**Fix applied:** changed to `completed_pipelines.append((pipeline, pipeline_future))`.

---

### ⚠️ `protein_binding.py:7–9` — module-level `EnvironmentError` on import

`MPNN_PATH` is validated at module import time:

```python
_mpnn = os.environ.get("MPNN_PATH")
if not _mpnn:
    raise EnvironmentError("MPNN_PATH is not set ...")
```

Any code that does `from impress.pipelines.protein_binding import ...` — even
conditionally — will crash at import if the env var is absent. Should be deferred
to `__init__`.

---

## Potential Issues

### `impress_manager.py` — `WorkflowEngine` leaks on exception

`start()` creates `self.flow = await WorkflowEngine.create(...)` but never calls
`self.flow.shutdown()`. The caller is responsible for cleanup, but if `start()`
raises mid-run the caller's post-`await` shutdown line is never reached and the
engine leaks.

**Recommended fix:** wrap the main loop in `try/finally` inside `start()`, or
document that callers must guard with `try/finally`.

---

### `impress_pipeline.py:99` — `finalize` abstract/async mismatch

`ImpressBasePipeline` declares:

```python
@abstractmethod
async def finalize(self):
    """Optional: Cleanup or finalization logic"""
```

Both `SmallMoleculeBindingPipeline` and `ProteinBindingPipeline` implement it as
a plain `def finalize(self, ...)` (synchronous, with extra args). This means:

- Calling `await pipeline.finalize()` on a subclass instance would fail because
  the method is sync.
- The docstring says "Optional" but `@abstractmethod` makes it mandatory.

**Recommended fix:** either remove `@abstractmethod` and provide a no-op base
implementation, or declare it consistently as sync across the hierarchy.

---

### `protein_binding.py:303–310` — all AF2 tasks launched concurrently

```python
results = await asyncio.gather(*alphafold_tasks, return_exceptions=True)
```

All structures are folded in parallel. If there are N structures, N AF2 processes
compete for GPU memory simultaneously, likely causing OOM on real runs. AF2 should
be serialised per GPU or gated by a semaphore.

---

## Code Quality

### `logger.py` — no log level filtering

`LogLevel` enum is defined but never used to filter output. Every `debug()` call
always prints regardless of any configured level. The `activity_summary` method is
at DEBUG level but fires on every active cycle, producing steady noise. A minimum
configurable log level check should be added to `_write_log` or each log method.

---

### `logger.py` — `error()` ignores `self.output_stream`

`error()` and `critical()` bypass `self.output_stream` and always write to
`sys.stderr` directly via `_write_log(formatted, to_stderr=True)`. A caller that
sets a custom output stream (e.g. for testing) will silently lose error messages.

---

### `protein_binding.py:185` — hardcoded peptide sequence

```python
pep_seq = "EGYQDYEPEA"   # PDZ-domain peptide
```

This is a PDZ-specific constant hardcoded inside `s3()`. It should be a
constructor parameter (e.g. `self.peptide_seq`) so the pipeline is reusable for
other targets.

---

### `protein_binding.py:267–268` — `os.unlink()` without existence check in `finalize()`

```python
os.unlink(f"{self.output_path_af}/{a}.pdb")
os.unlink(f"{self.output_path}/af/fasta/{a}.fa")
```

If an AF2 task failed and the file was never created, `finalize()` raises
`FileNotFoundError`. Should use `pathlib.Path.unlink(missing_ok=True)` or check
existence first.

---

### `protein_binding.py:282–286` — redundant `pass` statement

```python
if self.is_child and self.passes == self.start_pass:
    self.logger.pipeline_log("Skipping MPNN and Ranking steps ...")
    pass   # redundant — remove
```

The `pass` is a no-op. Remove it. Also the log message says "Skipping MPNN and
Ranking" but execution still continues into `s3` (fasta), `s4` (AF2), etc. — the
message is partially misleading.

---

### `impress_manager.py:222` — `activity_summary` shows stale buffer count

`len(self.new_pipeline_buffer)` is logged *after* `self.new_pipeline_buffer.clear()`
runs (line 217), so the buffered count is always reported as 0. Move the summary
log before the clear, or capture the count beforehand.

---

### `impress_manager.py` — `self.flow` only exists after `start()` is called

`submit_new_pipelines()` is a public method that references `self.flow`, but
`self.flow` is created inside `start()`. Calling `submit_new_pipelines()` directly
before `start()` raises `AttributeError`. Either initialise `self.flow = None` in
`__init__` with a guard, or make `submit_new_pipelines` private.
