# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Revision History

| Date | Commit | Notes |
|---|---|---|
| 2026-11-11 | — | Directory created. The helper behind the Colab quickstart notebook: `toy_science.py` (pure scoring model and adaptive rule), `score_stage.py` (one stage as a subprocess), `impress_toy.py` (pipeline, adaptive callback, recorder, runner), `toy_figures.py` (figures). Covered by `tests/unit/test_colab_toy.py` and `tests/integration/test_colab_toy_run.py`; added to `ruff check` and `codespell` in `tox.ini` |

## Context

This is the only example in the repository that runs **without an allocation, a
GPU, model weights or rhapsody**. It exists so the documentation has something a
reader can execute, which nothing in `docs/` had before. A full run is about
five seconds on `impress` plus `radical.asyncflow` alone.

The framework is real and the science is not. Every score is a seeded
pseudo-random draw. What the run demonstrates is adaptive execution -- when
`run_adaptive_step` fires, what the callback decides, and what a spawned child
pipeline does to the run -- not any property of a protein. Keep that distinction
in anything written here; it is printed on the figures for the same reason.

## Verified behaviours this code depends on

Each of these was measured against the installed packages, not read from the
documentation. Breaking any of them breaks the example silently.

**Quoting is lost in a command string.** `LocalExecutionBackend` re-joins what
asyncflow `shlex.split` produced, so `/bin/echo 'two words'` reaches the process
as three argv entries, not two. Backlog F15. Every argument `score_stage.py`
takes is therefore a bare scalar.

**An executable task's future resolves to stdout as text** on this backend,
which ignores `capture_stdio`. That is how the simulated scores get back into
the pipeline. On rhapsody's backends the same future resolves to a *file path*
instead, so code copied out of here will need `capture_stdio=False` there.

**`adaptive_fn` must be the declared engine task.** `PipelineSetup` validates
this at construction and a child config is validated the same way, mid-run.
`_ADAPTIVE_TASK` in `impress_toy.py` is module-level for exactly that reason,
mirroring `examples/dummy_adaptive.py`; it is also why `run_sweep` is
sequential.

**The adaptive callback runs on a worker thread**, not on the event loop
(measured: `ThreadPoolExecutor-0_0`). `EventRecorder` locks its appends, and
only the loop-side `stream` coroutine prints.

**`max_workers` does not bound executable tasks.** They are subprocesses started
on the event loop; only function tasks and the adaptive callback go through the
thread pool. The concurrency figure shows six tasks in flight at
`max_workers=4`, and its caption says so rather than hiding it.

**One `run_adaptive_step(wait=True)` costs about a second.** The manager notices
the flag on a 0.5s poll and clears the barrier on a later one. A short run's
wall clock is mostly this, not task work. Do not tune `task_duration_s`
expecting it to dominate.

**`register_pipeline_tasks()` runs inside `__init__`, before `self.logger`
exists.** Anything a task body reads must be assigned before
`super().__init__()`.

## Conventions

`toy_science.py` must stay importable with the standard library alone:
`score_stage.py` runs once per task, so anything it imports is paid for on every
task. `toy_figures.py` imports matplotlib inside its functions, so
`impress_toy.py` works on a machine with no plotting stack -- the same split
IMPRESS-A makes with its `figures` extra.

The figure palette is copied from `agent/src/impress_a/analysis/plot_style.py`,
not imported from it: importing `impress_a` here would invert the dependency
between the two packages and break the lean install the notebook uses. A fifth
hue has to be re-validated before it is added; see the `campaign-plot-style`
skill.
