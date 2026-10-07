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

On Delta, `.venv` is a **symlink** to `$WORK_DIR/ve/impress_a`, and `$WORK_DIR` must be on NVMe
(`/work/nvme/<project>/$USER`). The venv holds PyRosetta and torch, and reading them is the single
largest cost this project pays: measured on HDD-backed `/work/hdd`, `import pyrosetta` alone takes
**471s** (a 598 MB `rosetta.so`, demand-paged) and `import torch` ~280s. That is not a tuning
detail — it is why `packmin` could not start inside its 300s budget in job 22675512. `WORK_DIR`
replaces the older `$SCRATCH`, which was both HDD-backed and ambiguous about whether it already
included `$USER`. `impress-a preflight` flags a venv still on HDD.

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
| Only **integrity** gate failures count against a pattern's trust; **acceptance** failures still FAIL the node | `runtime/executor._record_evidence`, `tools/spec.py` | Counting quality thresholds made promotion a function of target difficulty - job 22702568 ran 30/30 tasks clean and promoted nothing (decision 0013) |
| An adapter **omits** a metric it could not read - never reports 0.0 | `metrics_reported` gate + `ToolSpec` validation | A fabricated zero turns "the tool broke" into "the design is weak", which acceptance gates no longer count against trust |

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
- asyncflow writes `asyncflow.session.*` into the CWD on every engine run *unless given a `work_dir`*.
  `make_engine`/`make_engine_bounded` take one, and the executor passes the campaign root, so sessions
  land beside provenance. Any new direct engine construction (tests included) must pass it too, or the
  checkout fills up again - 516 empty ones had to be deleted.

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

**One campaign has completed.** Job 22692304 ran all six stages — `rfd3_design ->
ligandmpnn_design -> packmin -> fastrelax -> filter_shape -> boltz_predict` — to `6/6 tasks ok`
in 2m53s, admitted on the *first* attempt, every stage passing its gates, and terminated with a
one-node Pareto front. All four campaign objectives carry real values (`total_score` −272.0,
`shape_complementarity` 0.591, `complex_plddt` 0.507, `ligand_iptm` 0.752). Per-tool cost is
measured for all six.

Read that as a floor, not a result. It is **one lineage, one cycle, one draw**: `replicas > 1`
has never run, so the independence invariant is unexercised; and no measurement has ever
superseded a prediction, so the calibration machinery is untested against reality.

**The trusted path has executed, twice.** Job 22726105 promoted the six-stage pattern after r0002,
exactly as predicted from a replay of 22702568's metrics, and admitted r0003 and r0004 trusted -
no forced dry-run, no cost cap, normal QC verdict. It took decision 0013 to get there: under the
old all-gates rule, 22702568 ran 30/30 tasks clean and promoted nothing. r0004 was then demoted by
packmin's `total_score <= 1000` integrity bound over a +1064.5 pose that relaxed normally, so that
bound is gone: whether a pose exploded is fastrelax's call, by whether it converges. What has
still never happened is a sustained trusted run, or a node reaching plain `pass` - every trusted
node so far missed an acceptance threshold. See `plans/next-run-promotion.md`.

**Wall time is not stable, and cost models must not be tuned as if it were.** `rfd3_design` took
145.7s in job 22684607 and 45.0s in 22692304 — same campaign, same allocation, same parameters,
3.2× apart. `cost_model` figures feed gate 5 and the untrusted-pattern cap, which *refuse*
graphs, so they sit a few multiples above measurement on purpose.

Four defects reached real hardware before anything caught them, and each was invisible to a dry run:

- **What a tool writes.** The `*.cif.gz` glob selected a diffusion *trajectory* rather than the
  design - same extension, and `denoised` sorts first. Discovery goes through `*_model_*.json` now.
- **Whether a tool can import.** LigandMPNN died in `run.py`'s module-level imports: a missing
  `ml_collections`, then `np.int`, removed in numpy 1.24 and still used by its vendored openfold.
  It runs through `MPNN_SHIM` now, never directly.
- **Where the bytes live.** `import pyrosetta` cost **471s** off HDD-backed Lustre, so `packmin`
  could not finish starting inside its 300s budget. On NVMe it is seconds. This one nearly caused a
  second bug: the fix queued up was to raise three walltimes to 1800/3600/1200, which would have
  hidden the real cost behind timeouts six times too large. See `docs/limitations.md`.
- **An estimate that refuses work.** The `cost_model` figures were literature guesses 6-69x over
  measurement. Gate 5 and the untrusted-pattern cap refuse graphs against them, so the inflated
  gpu side summed past the cap and the policy truncated `boltz_predict` off the chain - silently,
  because nothing checks that a graph can still produce the campaign's objectives. It warns now
  (`runtime/executor._objectives_without_a_producer`), and it is a heuristic, not a gate.

The pattern worth carrying forward: **"checked against the binary" is not "executed,"** and a
plausible explanation is not a diagnosis - the trajectory bug was a convincing cause for a
LigandMPNN failure it had nothing to do with. `impress-a preflight` first. See
`plans/first-real-run.md` and backlog A1/A4/A6.

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

**QC for the real toolkits leans on self-reported confidence.** Their quality gates are
`metric_in_range` against a number the tool chose to report about itself, which is precisely what a
confidently-wrong tool passes. Since decision 0013 those are *acceptance* gates, so trust rests on the
*integrity* gates alone: presence checks, `has_secondary_structure`, and the Rosetta divergence bounds.
There are still no structural gates (backlog B1). Known-bad fixtures exist for every real tool, and each
must fail an integrity gate or declare itself `acceptance_only`.

Full list: `plans/backlog.md`. Shipping-facing summary: `docs/limitations.md`.
