# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `README.md` first** for what IMPRESS-A is and how it fits together. This file covers what you need
to *work on* it: commands, invariants that must not be broken, and behaviours that are easy to get wrong.

## Commands

```bash
source .venv/bin/activate        # do NOT use system Python - see "Environment" below
pip install -e ".[dev]"          # once; then no PYTHONPATH is needed anywhere

pytest tests -q                                      # 29 tests, ~4s, no allocation
pytest tests/test_validation.py -q                   # one file
pytest tests -q -k interlock                         # by name
pytest tests/test_campaign.py::test_lying_tool_is_caught_by_qc -q

impress-a tools                                      # list registered tools
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
| `src/impress_a/` | The package |
| `toolkits/` | Declarative tool specs + skill docs, discovered at runtime — not package data |
| `campaigns/`, `sites/` | Campaign specs and per-machine configuration |
| `docs/` | **Shipping reference.** `reference/`, `decisions/`, `limitations.md`, `roadmap/` |
| `planning/` | **Process history, not reference.** The design record; superseded in places. Where it disagrees with `docs/` or the code, the code is right |

## Invariants — do not break these

Each exists because of a specific failure mode. Details in `docs/reference/architecture.md`.

| Invariant | Enforced in | Why |
|---|---|---|
| **`policy` must not import `tools` or `exec`** | review | Policies emit abstract `ExperimentIntent`. If a policy can reach a tool adapter, control models stop being swappable |
| **`compose` must not import `exec`** | review | Keeps the whole validation path testable with no backend — the entire laptop test tier |
| A QC `FAIL` node is **never** eligible for the Pareto front | `core/qc.py`, `core/pareto.py` | These tools fail *silently*; exit code is never sufficient evidence |
| **P6 tools are inlined, never scheduled** | `compose/validate.py` gate 4 | Scheduling overhead would exceed the work. A scheduled P6 node is a composer bug |
| `replicas: N` means **N independent lineages**, one `DesignNode` each | `compose/composer.py`, `manager._absorb` | Fanning out then funnelling back collapses N candidates into one |
| Pattern signatures ignore **parameter values** — shape only | `compose/graph.py` | Otherwise every parameter tweak resets a pattern's accumulated trust |
| A measurement **supersedes but never deletes** a prediction | `core/tree.ingest_measurement` | The predicted-vs-measured gap is the surrogate-calibration signal |
| The Pareto front is **not monotonic** once measurements arrive | `core/pareto.py` | A node promoted on an optimistic prediction can be demoted by its own assay |
| Rejection triggers **bounded in-cycle retry**, not a discarded cycle | `manager.run` | `on_rejected` hands the policy a reason and another attempt |
| `execute()` is not overridden by tool adapters | `tools/agent.py` | Pattern dispatch belongs to the exec layer; overriding bypasses P6-inline and P4-ledger rules |
| QC gates are deterministic **even for LLM-driven task agents** | `tools/agent.py` | An LLM may author a protocol; it does not judge whether the result passed its clash check |

## Middleware gotchas

Full notes in `docs/reference/middleware-integration.md`. The ones that cost the most time:

- **Rhapsody backends are awaitable and must be awaited.** `__await__` triggers state registration.
  Constructing synchronously appears to work, then fails later with
  `Backend 'x' not registered. Available backends: []`.
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
`test_campaign.py` (full campaigns on `ConcurrentExecutionBackend` with mock tools).

The bundled `mock_noodle` tool **lies**: it completes successfully, reports a confident `designability`,
and produces a structure with no secondary structure. It exists so the QC layer is tested at campaign
scale. When adding mocks, let some of them return plausible-but-wrong output — silent failure is the
dominant hazard, so the suite has to manufacture some.

## Known open risk

**Cancellation.** Backtracking works by *branching the tree*, which avoids cancelling in-flight work — so
the risk is deferred, not solved. Anything needing true cancellation (aborting a running graph on `Stop`,
reclaiming resources from an abandoned lineage) should be spiked against the installed asyncflow before
being designed around. Other gaps: `docs/limitations.md`.
