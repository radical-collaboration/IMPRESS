# Defects found while updating the docs after PR #72

**Status:** open · **Evidence:** docs review of `main` at `9a413cd`; docs fixed in `910279d`, `a5bc68e` · **Items:** F21, F22, F23

The docs pass after PR #72 corrected every page to describe the code as it is. Three code issues
it found are larger than a docs fix, so the pages now state the current behaviour and these items
track the change.

<a id="f21"></a>
## F21: a bad child `adaptive_fn` raises out of `manager.start()`

**Why.** `PipelineSetup` rejects an `adaptive_fn` that is not a declared task (F20). For the
setups passed to `start()`, that happens before any pipeline runs. A child request, though, is
converted with `PipelineSetup.from_dict(config)` inside the manager's poll loop
(`src/impress/impress_manager.py:203`) with no handler, so the `TypeError` leaves `start()` with
other pipelines still in flight. `docs/concepts/architecture.md` now says so.

**Change (needs decision).** One of:
- catch it there, log a `child_pipeline_rejected`-style event, and drop only that child; or
- keep failing fast, but document it as the intended contract and make sure the engine and
  in-flight pipelines are torn down cleanly.

**Test.** A unit test whose adaptive function submits a child with a bare `async def`; assert
the chosen behaviour (child dropped and siblings finish, or a clean `TypeError` from `start()`).

<a id="f22"></a>
## F22: `radical-asyncflow` floor is older than the API the code uses

**Why.** `pyproject.toml:22` declares `radical-asyncflow>=0.4.0`. The code and every example rely
on named backends (`ConcurrentExecutionBackend(..., name=)`), `WorkflowEngine.create(backend=[...])`,
`flow.function_task(backend=...)` and `capture_stdio`, and the suite and all Delta acceptance
runs used 0.5.0 / 0.5.1. Nothing has been run on 0.4.x. rhapsody has no floor at all, though
0.5.0 removed `DragonExecutionBackendV3`.

**Change.** Confirm the oldest asyncflow that has all four features, then raise the floor in
`pyproject.toml` and `docs/getting-started/installation.md:43`. Consider `rhapsody-py>=0.5.0` in
the optional extras.

**Test.** `pip install` the floor version into a clean venv and run `pytest tests`.

<a id="f23"></a>
## F23: protein_binding path defaults disagree with its Delta setup script

protein_binding has no tracker of its own, so its path bugs are kept here.

**Why.**
- `examples/protein_binding/protein_binding.py:152` reads pre-computed MSAs from the hard-coded
  `~/boltz/msa_cache`. `delta_env_setup.sh:165` writes them to `${WORK_DIR}/boltz/msa_cache`, so
  on a default setup `s3` never finds them and Boltz runs single-sequence.
- `delta_gpu_run.sh:63` defaults `BOLTZ_VENV` to `${HOME}/ve/boltz`; `delta_env_setup.sh:138`
  builds it in `${WORK_DIR}/ve/boltz`.

`docs/examples/protein-binding.md` documents both mismatches and the workaround.

**Change.** Derive the MSA cache from `BOLTZ_CACHE_DIR` (already exported by `delta_gpu_run.sh`),
falling back to `~/boltz`; default `BOLTZ_VENV` to `${WORK_DIR}/ve/boltz`. Then remove the
workaround notes from the doc.

**Test.** On Delta, a 1-pipeline, 1-pass run after `delta_env_setup.sh`: the generated FASTA
references the cached MSA paths instead of `empty`.
