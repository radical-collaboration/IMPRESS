# Roll back the asyncflow escapes where asyncflow now has the pattern (F14–F17)

**Status:** re-scoped 2026-10-15. F14, F17, F15 part 2 and the `stdio.py` docstring are **fixed on `framework-defaults-pr1` (`a74b71d`)**. They are not yet merged and need no Delta run (see [Order](#order-revised-2026-10-15)). F15 part 1 goes to PR 2 and is blocked on an asyncflow quoting defect. F16 is open and needs a decision · **Items:** F14–F17 · **Evidence:** commit `7327c84` (PR 1), radical.asyncflow 0.5.1 (`main` @ `v0.5.1-1-g038d52a`), F1 job `22767771`, a test run without rhapsody (115 passed / 5 skipped) · **Depends on:** F1 passed; F16 also on F13

## Why

PR 1 (`7327c84`) moved four proven fixes into the framework. Three of them reach around
asyncflow rather than through it: a private backend-table probe, a hand-rolled telemetry
event for stages the engine never sees, and a reconstruction of stdio paths from private
attributes. Those were the right call against what asyncflow 0.5.0 offered.

asyncflow 0.5.1 states its own idiom in `examples/04-concurrent_backends.py`: several
**named** backends on one engine, with the caller naming the target in the decorator
(`@flow.function_task(backend="compute")`, `@flow.prompt_task(backend="ai")`), futures passed
between backends as dependencies, and `LocalExecutionBackend(ThreadPoolExecutor(), name=...)`
for in-process Python work. Routing is **declared, never discovered**.

Measured against that example, four of IMPRESS's escapes can go back, and three must stay
until upstream grows an API. This doc covers the four; the three are in "Keep" below, and the
upstream asks are in [F13](2026-10-08-framework-deferred.md#f13).

The checkout of `radical.asyncflow` at `main` is the same revision as the installed wheel
(`v0.5.1-1-g038d52a`), so there is no newer upstream pattern waiting to be adopted.

<a id="f14"></a>
## F14 — Declare the adaptive backend instead of probing for it

**Evidence.** `ImpressManager._local_backend_task` reads the engine's private backend table to
find out whether a backend named `local` exists (`src/impress/impress_manager.py:162-164`).
There is no public accessor: `WorkflowEngine.backend` returns only the default
(`workflow_manager.py:141-143`). The probe also gives the manager a silent mode switch — an
engine whose thread pool is named `callbacks` instead of `local` falls back to
`asyncio.to_thread` with no error and no log line, which is a behaviour change nobody asked
for and nothing reports.

**Change.** `ImpressManager(..., adaptive_backend="local")`, defaulting to `None`:

- a name means register the callback as `flow.function_task(backend=<name>)`, as example 04
  does — no `getattr(self.flow, "_backends", ...)`, no `isinstance(dict)` guard;
- `None` means `asyncio.to_thread`, today's fallback;
- `adaptive_offload=False` keeps its current meaning (run on the loop).

**An unknown name must be caught before the first submission (corrected 2026-10-15).** The
first draft said asyncflow "raises `KeyError` at submit", so the manager could wrap the first
call and re-raise. It does not reach the caller:
- the lookup `self._backends[b_name]` runs in the engine's background submit path
  (`workflow_manager.py:1381`);
- `submit()` logs and re-raises the error (`:1387-1389`);
- the run loop catches it and calls `_handle_shutdown_signal` (`:1317-1319`).

So a misspelled `adaptive_backend` would shut down the **whole engine** at the first adaptive
call, with every pipeline's tasks in flight. `ImpressManager.start()` therefore validates the
name before it submits any pipeline. If the engine's backend table is readable, a missing name
raises `ValueError` naming the backend asked for and the ones the engine has. That keeps one
guarded read of `flow._backends`. It is now a check that fails loudly, not a silent mode
switch, and it goes when F13's `has_backend` ask lands. If the table is not readable (a mock
engine), the check is skipped.

The smb runner passes `adaptive_backend="local"`, which reaches the same
`function_task(backend="local")` path F1 measured. Every other runner has no `local` backend
and keeps `asyncio.to_thread`, so F14 no longer has to wait for **F7**.

**Test.** Extend `tests/unit/test_manager_adaptive_logic.py::TestAdaptiveOffload`:
- a declared backend is routed to. This replaces `test_uses_local_backend_when_present`,
  which asserts the probe, and keeps its assertions: registered once as
  `("adaptive_decision", "local")`, labelled `p<N>:adaptive`;
- with a `local` backend present but no name declared, the callback runs in a thread;
- `start()` raises `ValueError` naming a backend the engine does not have, before any
  pipeline runs.

<a id="f15"></a>
## F15 — Use asyncflow's own `LocalExecutionBackend` on the dev path, and cover PR 1's defaults locally

**Evidence.** The smb runner imports rhapsody's `ConcurrentExecutionBackend` even for
non-Dragon development (`examples/small_molecule_binding/run_small_molecule_binding.py:87`,
`:452-455`), while asyncflow ships `LocalExecutionBackend` for exactly that, handles
executables as well as functions (`backends.py:311-343`), takes `name=`, and is already what
the other runners use (`examples/dummy.py:90`,
`examples/small_molecule_binding/run_test_small_molecule_binding.py:151`). Example 04 uses it
as its `compute` backend.

The cost of the current arrangement is test coverage. `pyproject.toml` requires only
`radical.pilot` and `radical-asyncflow`, so rhapsody is optional. On a checkout without it,
`.venv/bin/python -m pytest -q -rs` gives **115 passed, 5 skipped**. With rhapsody installed
(`ve/impress_a` on Delta) all 120 pass. The skips are precisely PR 1's own defaults:

| Skipped | Why |
|---|---|
| all of `tests/integration/test_task_defaults.py` | `pytest.importorskip("rhapsody.backends")` at `:13` |
| 4 tests in `tests/unit/test_pipeline_task_defaults.py` (`:151`, `:165`, `:173`, `:177`) | `rhapsody.telemetry` not installed, so `impress.LocalStage` cannot be asserted |

So stdio capture, the stderr tail and the `LocalStage` event have **no local coverage at
all** — they are exercised only where rhapsody is installed.

**Change.** Two parts, split across PRs since 2026-10-15:

1. **PR 2.** Runners: `LocalExecutionBackend(ProcessPoolExecutor(), name="compute")` on the non-Dragon
   branch, dropping the rhapsody import from the dev path. Keep `DragonExecutionBackend` for
   production. Also replace the `isinstance(self.flow.backend, ConcurrentExecutionBackend)`
   env branch (`examples/small_molecule_binding/small_molecule_binding.py:739`), which forces
   a rhapsody import at pipeline-definition time, with a check that does not name a class.
   This part stays out of PR 1. The line-739 branch chooses the env and GPU-pinning shape for
   *every* tool task, Dragon included, so it is on the path F1 measured. The runner swap also
   changes dev-path stdio, because `LocalExecutionBackend` ignores `capture_stdio` (below).
   **Blocked, found 2026-10-15:** `LocalExecutionBackend` cannot run a quoted command. The
   engine `shlex.split`s the command an executable task returns (`workflow_manager.py:654-661`).
   The backend's shell mode then re-joins the parts with `" ".join` (`backends.py:318`), which
   drops the quoting, so `bash -c 'echo a; echo b'` runs as `bash -c echo a; echo b`. Every
   stage that wraps its command in `logged_command()` returns exactly that shape, so the swap
   would break five of smb's seven tool stages. Upstream fix: `shlex.join(parts)`, or default
   to exec mode. Added to F13's asks.
2. **PR 1.** Tests only, no runtime change: add a `LocalExecutionBackend` variant of `test_task_defaults.py`. It cannot assert
   the current file-path behaviour, because that backend **ignores `capture_stdio`** — it
   pipes and decodes (`backends.py:311-343`; `capture_stdio` appears nowhere in that module
   outside two docstrings) and the engine then wraps the stderr *text* into the exception
   (`workflow_manager.py:1536-1557`). That is the other shape `stderr_tail` handles, so the
   two variants together cover both.

**Test.** `pytest -q` on a checkout without rhapsody runs the new integration variant rather
than skipping the module; the rhapsody variant still runs on Delta. Pass: both report the
stage name and the failing command's last stderr lines in the raised exception.

**Part 2 result (`a74b71d`).** `tests/integration/test_task_defaults_local.py` passes. With
rhapsody imports blocked, the suite gives 122 passed / 5 skipped; the 5 are the `LocalStage`
tests, which F16 removes. The test runs script files rather than `bash -c '...'`, because of the
quoting defect above.

<a id="f16"></a>
## F16 — Local stages as function tasks on a named backend

**Evidence.** `auto_register_task(local_task=True)` binds the raw coroutine
(`src/impress/pipelines/impress_pipeline.py:138-140`) and `wrap_local_task` hand-rolls an
`impress.LocalStage` event (`src/impress/utils/telemetry.py:22-28`, `:58-84`), because those
stages never reach the engine. asyncflow's pattern is a function task on a Python backend —
example 04's `preprocess`/`postprocess` — and IMPRESS already relies on it for a callback that
mutates the live pipeline: PR 1's adaptive offload. The example's own history retracted the
earlier "not drop-in" objection (`examples/small_molecule_binding/CLAUDE.md`, 2026-10-04 row).

**Change.** `local_task="<backend name>"` (or a manager-level default) registers the stage as
`flow.function_task(backend=<name>)`; `local_task=True` keeps `wrap_local_task` for engines
with no Python backend. Gains: asyncflow-native lifecycle events instead of a bespoke schema,
real dependency futures, concurrency bounded by the pool, and both of F15's skip reasons gone
(the custom event is what needs `rhapsody.telemetry`).

**Why it is not a clean delete.**

1. It spreads a **thread**-pool requirement from one callback to every local stage: these
   mutate `self.state`/`self.taskcount`, so a `ProcessPoolExecutor` backend would mutate a
   pickled copy.
2. It breaks trace continuity — existing analysis reads `impress.LocalStage`. Decide whether
   to emit both for one campaign or to port the analysis.
3. It widens exposure to **F13**: `fut.cancel()` calls the *default* backend's `cancel_task`
   whatever the task's routing, so a `kill_parent` during a local stage misroutes. Today that
   is one callback's worth of risk; this makes it six stages per cycle.

**Test.** The smb mock run (`run_test_small_molecule_binding.py`) must produce the same stage
sequence and adaptive decisions as before, as it did for PR 1, and the trace must carry one
asyncflow task per local stage with the stage's own name. Do not submit a Delta run for this
until F13's cancel bug has an upstream answer.

**Status:** open, needs decision — on the trace-schema break, and on whether a Python backend
becomes mandatory for every engine.

<a id="f17"></a>
## F17 — Drop the private telemetry fallback on `ImpressBasePipeline`

**Evidence.** `pipeline.telemetry` falls back to `getattr(self.flow, "_telemetry", None)`
(`src/impress/pipelines/impress_pipeline.py:101`). The public path already exists and is
already wired: the manager keeps what `start_telemetry()` returns
(`src/impress/impress_manager.py:197`) and injects it into each pipeline (`:108`). The
fallback only serves a pipeline driven without the manager.

**Change.** Remove the `getattr`, and document that telemetry on a manager-less pipeline is
passed in by the caller. One of the three accessors F13 asks upstream for then stops being
needed.

**Test.** Existing `LocalStage` unit tests, which inject telemetry through the manager, keep
passing; add one asserting `telemetry is None` for a manager-less pipeline.

## Keep (no change, narrower documentation)

- **`utils/stdio.py`'s path reconstruction.** No public replacement exists. Two corrections to
  F13's list of private attributes: `fut.task` is set by asyncflow itself
  (`workflow_manager.py:756`) and consumed by its own public dependency API (`:915`), so it is
  undocumented but not private; the genuine privates are the backend table and
  `backend._work_dir` (`src/impress/utils/stdio.py:61-63`). The reconstruction is only
  load-bearing for Dragon. rhapsody's Concurrent backend puts the path in the message, and
  `LocalExecutionBackend` puts the text there.
  **Correction from F1:** Dragon does not surface `SystemExit(<exit code>)`, as this doc and
  `stdio.py:7` said. rhapsody sets `task["exception"] = SystemExit(code)`, but asyncflow keeps
  only `Exception` subclasses and wraps anything else as `RuntimeError(str(...))`
  (`workflow_manager.py:1563-1568`). So the caller sees `RuntimeError('<exit code>')`, as p32
  did on `22767771`. Narrow the module docstring to say exactly that, **in PR 1** (docs only).
- **`logged_command()`.** Partly redundant with `capture_stdio`, but it serves a different
  consumer: a log next to the task's outputs, which `scripts/validate_run.py` and operators
  read. Keep it, and note its cost — it makes the command start with `bash`, and
  `comp_desc["executable"] = shlex.split(cmd)[0]` (`workflow_manager.py:654-660`) is what
  `_tel_executable` prefers over the function name (`:739-741`). It is part of why the
  telemetry label needs `workflow_id` at all.
- **Per-call `workflow_id={pipeline}:{stage}`.** `flow.workflow_scope()`
  (`workflow_manager.py:282-308`) is public and adds a parent span, but it assigns one id to
  everything inside it, so stage identity would fall back to the task label — `bash` for every
  executable stage, the exact defect PR 1 fixed. The two do not compose: a call-time id
  overrides the ContextVar (`:716-718`). Upstream's own comment calls an explicit call-time
  `workflow_id` "a telemetry label, not a membership signal" (`:779`), i.e. IMPRESS's use is
  the sanctioned one. Adopt `workflow_scope` for hierarchy only once the executable label is
  fixed upstream (the third ask in F13).

Also not an escape: `_run_to_completion`'s `asyncio.run` in a worker thread and the
`run_adaptive` async shim. asyncflow's own error tells callers to wrap sync functions in
`async def` (`workflow_manager.py:666`).

## Order (revised 2026-10-15)

1. **With PR 1, before it merges:** F17, F14, F15 part 2 and the `stdio.py` docstring.
   - F14 changes PR 1's own new API. Changing it after merge would break callers.
   - The rest is a one-line deletion, tests or docs.
2. **PR 2:** F15 part 1, beside F7. Both touch the runners' backend layout, and F15 part 1
   touches the env branch every Dragon task takes.
3. **Last:** F16, after F13 has an upstream answer and the trace-schema decision is made.

**Risk to F1.** F1 passed on `e3926d8`, which has none of these changes. They leave the Delta
path unchanged by construction:
- smb declares the `local` backend it already used, so the same `function_task(backend="local")`
  registration happens;
- telemetry is still injected by the manager;
- the docstring and the tests change no code that runs.

They are proven by the unit tests and the smb mock run (same stage sequence and adaptive
decisions as PR 1 recorded), not by a new Delta run.
