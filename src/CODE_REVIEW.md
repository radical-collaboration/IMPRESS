# IMPRESS `src/` Code Review

**Date:** 2026-08-29  
**Scope:** `/scratch/bblj/mgoliyad1/IMPRESS/src/impress/`  
**Status:** bugs marked ✅ fixed or ⚠️ open  
**Note:** `protein_binding.py` was moved from `src/impress/pipelines/` to
`examples/protein_binding/` in the `origin/main` merge; findings for that file
are now in `examples/protein_binding/CODE_REVIEW.md`.

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
