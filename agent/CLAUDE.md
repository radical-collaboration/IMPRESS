# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `README.md` first** for what IMPRESS-A is and how it fits together. This file covers what you need
to *work on* it: commands, invariants that must not be broken, and behaviours that are easy to get wrong.

## Commands

```bash
source .venv/bin/activate        # do NOT use system Python - see "Environment" below
pip install -e ".[dev]"          # once; then no PYTHONPATH is needed anywhere

pytest tests -q                                      # the whole local tier, no allocation (~2min on a login node)
pytest tests/test_validation.py -q                   # one file
pytest tests -q -k interlock                         # by name
pytest tests/test_campaign.py::test_lying_tool_is_caught_by_qc -q

impress-a tools                                      # list registered tools
impress-a preflight campaigns/<spec>.yaml            # real-toolkit env check, BEFORE sbatch
impress-a run campaigns/mock-stabilize.yaml --model D
#   --model  A | B | C | D | null | replay     --no-guard  disables the correction wrapper
```

Without the editable install, prefix with `PYTHONPATH=src` and use `python -m impress_a`.

### Environment

Use the project `.venv`. The system Python has `radical.asyncflow` **0.3.1** installed while this project
requires **0.5.1**, and its `rhapsody` is an editable install pointing at a different checkout. Running
tests against it produces confusing API errors.

## Repository layout

| Path | Role |
|---|---|
| `src/impress_a/` | The package. `runtime/` owns the executor, session and run service; `manager.py` is a facade over them |
| `toolkits/` | Declarative tool specs + skill docs, discovered at runtime — not package data |
| `campaigns/`, `sites/` | Campaign specs and per-machine configuration |
| `docs/` | **Shipping reference.** `reference/`, `decisions/`, `limitations.md`, `roadmap/` |
| `plans/` | **Working plans.** `backlog.md` is the live outstanding list; `done/` records completed work *for the rulings it contains*, not the task lists |
| `planning/` | **Process history, not reference.** The design record; superseded in places. Where it disagrees with `docs/` or the code, the code is right |

## Invariants — do not break these

Each exists because of a specific failure mode. Details in `docs/reference/architecture.md`.

| Invariant | Enforced in | Why |
|---|---|---|
| **`policy` must not import `tools`, `exec` or `runtime`** | review | Policies emit abstract `ExperimentIntent`. If a policy can reach a tool adapter, control models stop being swappable |
| **`compose` must not import `exec`** | review | Keeps the whole validation path testable with no backend — the entire laptop test tier |
| A QC `FAIL` node is **never** eligible for the Pareto front | `core/qc.py`, `core/pareto.py` | These tools fail *silently*; exit code is never sufficient evidence |
| **P6 tools are inlined, never scheduled** | `compose/validate.py` gate 4 | Scheduling overhead would exceed the work. A scheduled P6 node is a composer bug |
| `replicas: N` means **N independent lineages**, one `DesignNode` each | `compose/composer.py`, `runtime/executor._absorb` | Fanning out then funnelling back collapses N candidates into one |
| Pattern signatures ignore **parameter values** — shape only | `compose/graph.py` | Otherwise every parameter tweak resets a pattern's accumulated trust |
| A measurement **supersedes but never deletes** a prediction | `core/tree.ingest_measurement` | The predicted-vs-measured gap is the surrogate-calibration signal |
| The Pareto front is **not monotonic** once measurements arrive | `core/pareto.py` | A node promoted on an optimistic prediction can be demoted by its own assay |
| Rejection triggers **bounded retry per experiment**, not a discarded cycle | `policy/driver.py` *and* an independent cap in `runtime/executor.py` | `on_rejected` hands the policy a reason and another attempt. The executor caps admissions separately, because a `conduct` reasoner is under no obligation to honour `max_attempts` |
| `execute()` is not overridden by tool adapters | `tools/agent.py` | Pattern dispatch belongs to the exec layer; overriding bypasses P6-inline and P4-ledger rules |
| A tool's `outputs` are **typed `ArtifactRef`s**, never bare strings | `tools/agent.py::_as_artifacts` | The type comes from the spec's declared port, so a handle cannot disagree with what the composer type-checked. Return a `Path` for a file |
| An **untrusted** pattern has at most one instance in flight | `runtime/executor.py::_admit_once` | Promotion counts *consecutive* clean runs; concurrent instances are one draw sampled N times |
| The **executor is the only writer** of campaign state, and decides termination | `runtime/executor.py` | Every mutating block is `await`-free, so an observation is never taken mid-absorb. Adding an `await` inside `observe`/`_absorb` reintroduces torn reads |
| QC gates are deterministic **even for LLM-driven task agents** | `tools/agent.py` | An LLM may author a protocol; it does not judge whether the result passed its clash check |

## Middleware gotchas

Full notes in `docs/reference/middleware-integration.md`. The ones that cost the most time:

- **Rhapsody backends are awaitable and must be awaited.** `__await__` triggers state registration.
  Constructing synchronously appears to work, then fails later with
  `Backend 'x' not registered. Available backends: []`.
- **The `WorkflowEngine` and a backend's async init must be built on the loop that will use them.**
  `WorkflowEngine.__init__` captures the running loop and puts its `run-component` dispatch task on
  it. Build one on a throwaway loop (e.g. `asyncio.run(...)` on a helper thread) and you get an
  engine that looks fine and dispatches nothing — every submitted task hangs, silently. Only
  `exec/backend._construct_backend_sync` may be offloaded to a thread. Cost of learning this: two
  full Delta allocations (jobs 22328172, 22328262).
- **Dragon empties the root logger.** `Pool()`/`ProcessGroup()` call `setup_BE_logging`, which calls
  `_clear_root_log_handlers()` — so a run configured with `logging.basicConfig` alone goes mute the
  moment the Dragon backend comes up. Keep handlers on your own logger with `propagate = False`
  (`scripts/delta_run_campaign.py`).
- **`ConcurrentExecutionBackend` is in rhapsody, not asyncflow.** asyncflow exports only
  `NoopExecutionBackend` and `LocalExecutionBackend`. Real backends resolve *by name* via
  `rhapsody.backends.get_backend()`; keep rhapsody unnamed outside `exec/backend.py`.
- **asyncflow task names come from `fn.__name__`** — the decorators take no `name=` kwarg. Setting
  `__name__` before decorating is what lets one generic factory serve every DAG node.
- **Two asyncflow idioms, not interchangeable.** Unawaited futures as call arguments express DAG *edges*;
  `asyncio.gather` awaits *independent* work.
- **Resource shapes are not portable** across backends; `exec/resources.py` owns the translation.
- **No retry primitive, no durable job state** in asyncflow. Both are ours (`exec/ledger.py`).
- asyncflow writes `asyncflow.session.*` into the CWD on every engine run. Gitignored; clean periodically.

## Adding a tool

`toolkits/<toolkit>/tools/<id>/spec.yaml` + a `TaskAgent` subclass (`entry:` points at it) + a mention in
that toolkit's `SKILL.md`. Full guide: `docs/reference/authoring-tools.md`.

**Never edit the composer, validator or manager to add a tool.** If you need to, the layering is wrong.

Loading is **validating**: a default outside its own range, an unknown QC gate id, a `P1` tool declaring
no GPU, or a `SKILL.md` missing a required section is a load-time error — and a toolkit that fails
anywhere registers **nothing**, never a partial set. `qc_gates` are mandatory for non-P6 tools, and gate
implementations are shared by id from `tools/gates.py` rather than reimplemented.

## Testing

`tests/test_core.py` (pure logic) · `test_validation.py` (the five gates + interlock) ·
`test_campaign.py` (full campaigns on `ConcurrentExecutionBackend` with mock tools) ·
`test_real_toolkits.py` (the real specs, without executing any real binary) ·
`test_backend_bound.py` (backend-construction timeout/heartbeat, against a fake backend
that blocks its own thread's event loop the way Dragon's `Batch()` does) ·
`test_http_adapter.py` (a campaign driven end to end over a loopback socket) ·
`test_layering.py` (the import contract, walked with `ast` rather than trusted to review) ·
`test_gate_fixtures.py` (each real tool's gates against its known-bad fixtures, and the
registry against the tool directories on disk).

**Counts are not restated in prose.** `test_gate_fixtures.py` derives the tool count from the
toolkit directories rather than asserting 11; there is no asserted test count and no asserted lint
count. The one number worth stating is the lint ceiling, and it is stated once, in
`plans/backlog.md`.

**A magic number in a test is often a bug report.** `stagnation_limit = 10_000` appeared in three
tests before anyone noticed the defect was in the executor, not the test setup. If a test needs an
engine parameter pushed to an absurd value to be meaningful, suspect the engine first.

The bundled `mock_noodle` tool **lies**: it completes successfully, reports a confident `designability`,
and produces a structure with no secondary structure. It exists so the QC layer is tested at campaign
scale. When adding mocks, let some of them return plausible-but-wrong output — silent failure is the
dominant hazard, so the suite has to manufacture some.

## Known open risks

**The real toolkits have never executed.** RFdiffusion3, LigandMPNN, PyRosetta and Boltz register,
validate, type-check as a chain and dry-run — and no line of their code has run through this system.
Their CLI contracts have since been checked directly against the installed binaries on Delta (not
just read from old scripts), which found and fixed genuine bugs — `rfd3_design` was invoking flags
the real Hydra-based CLI doesn't have at all — but "checked" is not "executed." Treat the real path
as untested. `impress-a preflight` first; see `plans/first-real-run.md`.

**Dragon backend construction is synchronous and can hang the event loop.** `Batch()` builds with no
`await` points, so a stall there is invisible — no heartbeat, no campaign log, nothing — until
whatever wall-clock limit kills the job (measured: job 22318678 spent its full 2-hour allocation this
way). Bounded now by `CampaignSpec.backend_startup_timeout_s`/`backend_startup_heartbeat_s`
(`exec/backend.make_engine_bounded` runs the *synchronous* construction on a daemon thread so the
bound stays effective, and builds the backend's async init and the engine on the caller's own loop —
see the loop-ownership gotcha above); 0 disables it, the default for every non-Delta campaign. See
`docs/limitations.md`.

**Dragon teardown can hang too, and it is the more expensive end.** Measured on the reference
IMPRESS pipeline (job 22491438): `flow.shutdown()` never returned after every pipeline had finished,
and the job sat 60 minutes before being cancelled by hand — ~64 GPU-hours, 37% of its billed total,
spent *after* the science was done. Bounded by `CampaignSpec.backend_shutdown_timeout_s` (0 disables;
300s in both Delta campaigns). On expiry the teardown is abandoned with a warning, never raised:
results are already durable in provenance and the ledger by then, so the cost is leaked backend state
in an exiting process — whereas raising would report a campaign that succeeded as failed. The
reference pipeline declined this fix and relies on an operator watching the log; we do not.

**Cancellation is advisory.** Measured rather than assumed: the concurrent backend's `Future.cancel()`
returns `False` once a callable has started, and asyncflow discards that answer — so queued work is
reclaimed, running work is not, and you cannot learn which happened. A run's terminal state must always
come from collecting it, never from the fact that cancel was called. Backtracking sidesteps this by
*branching the tree*. Reclaiming a GPU from an abandoned run remains unsolved.

**QC for the real toolkits leans on self-reported confidence.** Their gates are almost entirely
`metric_in_range` against a number the tool chose to report about itself, which is precisely what a
confidently-wrong tool passes. No structural gates, and no known-bad fixtures anywhere.

Full list: `plans/backlog.md`. Shipping-facing summary: `docs/limitations.md`.
