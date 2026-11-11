# Two live Colab examples for the documentation

**2026-11-11.** Supersedes a pre-plan written from the published documentation alone, which
is a local working draft and is not tracked here. Four of its assumptions did not survive
contact with the source; those are the four marked against it in "Verified, not assumed".

## Why

Nothing in `docs/` could be executed. `getting-started/quick-start.md` builds a pipeline
whose tasks return `"python3 run_homology_search.py"`, a file that does not exist, so the
page cannot be run as written. The three example pages need an allocation, a GPU and model
weights. `docs/impress-a/` is thirteen pages of reference prose with no getting-started page
in its nav at all.

So a reader could learn what IMPRESS claims to do and never watch it do anything. What was
missing was confidence and intuition, not information.

## What shipped

| Path | What |
|---|---|
| `examples/colab/toy_science.py` | The simulated scoring model and the adaptive rule as pure functions. Standard library only. |
| `examples/colab/score_stage.py` | One analysis stage as a standalone process; the pipeline's tasks exec it. |
| `examples/colab/impress_toy.py` | Pipeline, adaptive callback, thread-safe event recorder, runner, sweep. |
| `examples/colab/toy_figures.py` | Five figures; matplotlib imported lazily. |
| `docs/notebooks/impress_adaptive_quickstart.ipynb` | Non-agentic. Real manager, real backend, real subprocess tasks, real child-pipeline spawning. |
| `docs/notebooks/impress_a_knob_lab.ipynb` | Agentic. The knob lab's ten-minute activity, ported: four arms, the two traps, predict-then-run, buy it back. |
| `tests/unit/test_colab_toy.py` | 33 tests: arithmetic, the event log, and the agreement between the in-process scorer and the subprocess. |
| `tests/integration/test_colab_toy_run.py` | 9 tests against a real engine, ~45s. |
| `tox.ini`, `ci.yml`, `pyproject.toml`, `mkdocs.yml` | `notebooks` env and job, `mkdocs-jupyter`, lint paths, codespell skip, weekly drift trigger. |

Both notebooks are committed **with their outputs**, and `mkdocs-jupyter` renders them
statically with `execute: false`, so a reader who never opens Colab still sees a real run.

## Verified, not assumed

Each of these was measured against the installed packages. Four contradict the pre-plan.

| Claim | Evidence |
|---|---|
| `impress-framework` is not on PyPI | `pypi.org/pypi/impress-framework` returns 404. The distribution is `impress`, unreleased. `mkdocs.yml`'s footer still links the dead name — see "not bundled" below. |
| `impress` never imports `radical.pilot` | The only `radical` import in `src/` is `radical.asyncflow` (`impress_manager.py:5`). So `pip install --no-deps` is a legitimate shortcut and is what both notebooks use; `radical.pilot` is sdist-only with a C extension. |
| asyncflow exports two backends, not three | `radical/asyncflow/__init__.py:5`. `ConcurrentExecutionBackend` is rhapsody's. The pre-plan's reported docs inconsistency was already fixed in-tree. |
| An executable task's future resolves to stdout **as text** on `LocalExecutionBackend` | Measured. The pre-plan assumed stdout was unavailable and that scores would have to live in Python; instead the tasks exec `score_stage.py` and the scores come back through the backend. |
| Quoting is lost in a command string (F13/F15) | Measured: `python3 argv.py 'two words' tail` arrives as **three** argv entries. Every argument `score_stage.py` takes is a bare scalar because of it. |
| `max_workers` does not bound executable tasks | They are subprocesses started on the event loop; only function tasks use the pool. Measured: 6 tasks in flight at `max_workers=4`. The pre-plan expected this knob to visibly change the Gantt. It does not, and the figure's caption says so. |
| One `run_adaptive_step(wait=True)` costs about **1.0s** | Measured over three passes: 0.48s for the first, 1.00s each after. The manager notices the flag on one 0.5s poll and clears the barrier on a later one. A short run's wall clock is mostly this, not task work. |
| The adaptive callback runs on a **worker thread** | Measured: `ThreadPoolExecutor-0_0`. The event recorder locks its appends and only a loop-side coroutine prints. |
| A second run in the same event loop works | Required by the sweep cell; covered by `test_two_runs_in_one_event_loop`. |
| The knob lab's four arms run in **4.1s**, collect in 0.1s, eleven figures in 1.9s | Measured on this machine, model D. |
| Both traps reproduce | `hard` stops on "every spec objective satisfied" with an **empty front** (G14). `hopeless` fails integrity on 16 of 16 lineages while `hard` fails zero (decision 0013). |

Install timings, for the Gate A record: `impress-a` editable with `[figures]`, 31s with a
warm pip cache, 644 MB. Both notebooks pass `pytest --nbmake` in 23.7s together.

Cross-version evidence: the helper was exercised on Python 3.14 with `radical.asyncflow`
0.5.0 and on Python 3.10 with 0.6.0.

## Still open

**Nothing has been run in a real Google Colab runtime.** Everything above is a local
surrogate. The outstanding checks are the Python version Colab actually ships (3.12 is
assumed, and `tox.ini`'s `basepython` and the CI job both encode that assumption), the
wall-clock cost of both installs on a cold runtime, and whether Colab's `#@param` forms
render as intended. The notebooks' install cells are guarded on `find_spec`, so they are
re-runnable, but the clone-and-install path itself has only been reasoned about.

`mkdocs-jupyter` is pinned to **0.26.3, deliberately not the newest**: 0.27.0 declares
`requires-python >=3.12` and `ci.yml` runs both the `docs` and `docs-deploy` jobs on 3.11,
so the newer pin turns those red on a resolution error. Move the pin when those jobs move.

## New backlog items

<a id="f24"></a>
### F24 — an adaptive rule with no depth cap hangs `start()` with no diagnostic

The framework has no generation, lineage or depth concept, and enforces no limit of its own:
`submit_child_pipeline_request` is a bare assignment with zero validation
(`impress_pipeline.py:65-67`), and `ImpressManager.start()` returns only when
`pipeline_tasks`, `new_pipeline_buffer` and `adaptive_tasks` are all empty
(`impress_manager.py:280-287`). A rule that always spawns therefore never reaches that
condition, and the failure presents as a hang rather than an error.

Every example carries its own cap and each invented it separately —
`MAX_SUB_PIPELINES = 3`, `pipeline.generation >= pipeline.max_generations`,
`MAX_REDESIGN_DEPTH = 3`. That is the signal this belongs in the framework: an optional
`max_generations` on `PipelineSetup`, with the manager refusing a child request past it and
logging why, would retire three copies and turn a hang into a message.

Tier 3. Found while writing `examples/colab/`, which has the same hand-rolled cap for the
same reason.

<a id="f25"></a>
### F25 — a child config with no `name` raises `KeyError` from inside the poll loop

`ImpressManager.start()` indexes `config["name"]` directly when it drains a child request
(`impress_manager.py:201`), before `PipelineSetup.from_dict` ever sees it. A caller who omits
the key gets a `KeyError` raised out of the manager's loop, mid-run, with every other
pipeline already in flight — not a validation error naming the offending parent.

The same shape as F21, which is about a child config carrying a bare `adaptive_fn`, and
probably wants the same answer: validate a child request where it is submitted, and decide
once whether a bad one drops that child or fails the run.

Tier 3.

## Not bundled, deliberately

Two adjacent defects were found and left alone rather than folded into this work:

- `mkdocs.yml:130` points the footer's PyPI icon at `pypi.org/project/impress-framework/`,
  which 404s. It renders on every page of the site.
- `docs/concepts/architecture.md:152` and `README.md:57` still show rhapsody's
  `ConcurrentExecutionBackend` as though asyncflow exported it.

## Conventions followed

`examples/colab` was added to `ruff check` and to `codespell` in `tox.ini`, so the only part
of `examples/` that readers are pointed at from the documentation holds the repository's
zero-lint ceiling. It is not added to `ruff format --check`, for the same reason `agent/` is
not.

`*.ipynb` was added to `[tool.codespell] skip`. This is load-bearing rather than tidy:
`codespell ... docs` walks the tree by content, not extension, and the base64 of a committed
PNG output yields findings (`te`, `fro`, `fPR`) that are not words and cannot be fixed.
Verified by running codespell against the notebooks with the skip bypassed.
