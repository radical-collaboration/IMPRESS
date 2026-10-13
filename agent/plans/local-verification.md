# Local verification — what can be checked without an allocation

**Status:** reference, not a task list. Written 2026-09-29 against HEAD `041caba`.

## Problem

The laptop tier is real and it is cheap — six commands, about three minutes, no GPU, no allocation,
no science stack. But it exists only as prose, scattered: `CLAUDE.md` describes it twice (under
"Commands" and under "Testing"), `plans/backlog.md` restates part of it in its closing paragraph,
and each plan stub repeats the fragment it cares about. The baseline numbers — 94 tests, 41 lint
findings, 11 registered tools — appear in four places and nothing fails when they drift. They have
drifted once already: `09cef87` had to hand-edit "77 -> 89 in both places it appears", and the count
is 94 now.

This file is the one place to point at. It also records what each check *proves*, which is the part
prose keeps dropping, and the four holes in the tier.

## The tier

Everything below runs from the repo root with the project venv active
(`source .venv/bin/activate` — **not** the system Python, which has asyncflow 0.3.1 against this
project's 0.5.1).

### 1. The suite

```bash
pytest tests -q            # the whole tier, ~15 s
```

| File | What a green run proves |
|---|---|
| `test_core.py` | Pure logic: tree, Pareto, QC. No backend, no I/O |
| `test_validation.py` | The five composer gates and the self-promoting interlock |
| `test_campaign.py` | Whole campaigns on `ConcurrentExecutionBackend` with mock tools — including that `mock_noodle`'s confident lie is caught by QC |
| `test_real_toolkits.py` | The real specs load, type-check as a chain, and `dry_run` — **without executing any real binary** |
| `test_backend_bound.py` | The startup timeout and heartbeat, against a fake backend that blocks its own thread's event loop the way Dragon's `Batch()` does |
| `test_remote_session.py` | `RemoteSession` over the control plane |
| `test_http_adapter.py` | A campaign end to end over a loopback socket |
| `test_layering.py` | The import contract, walked with `ast` — including imports inside function bodies |
| `test_gate_fixtures.py` | Each real tool's declared gates against its known-bad fixtures, and the registry against the tool directories on disk |

What it does **not** prove: that any real toolkit works. `test_real_toolkits.py` runs
`pre_process` + `parameterize` and stops. Backlog A1 — no line of RFdiffusion3, LigandMPNN,
PyRosetta or Boltz has ever executed through this system — is untouched by a green suite.

### 2. Lint

```bash
ruff check src tests       # must not exceed 41
```

A ceiling, not a target. Rising means new debt; falling is welcome.

### 3. The import contract

The three layering invariants from `CLAUDE.md`:

- `policy` must not import `tools`, `exec` or `runtime`
- `compose` must not import `exec`
- `core` imports nothing internal

**Asserted by `tests/test_layering.py`**, which walks every `.py` under `src/impress_a/` with `ast`
and checks all three rules plus every other edge against one table mirroring
`docs/reference/architecture.md`. `ast.walk` rather than a module-level scan, because the adapters
defer science imports into `run()` bodies on purpose and a deferred `from ..exec import ...` inside
`compose` would be exactly as fatal.

Its one blind spot is a dynamic `importlib.import_module`, which `Registry.agent_for` uses
legitimately, within its own layer.

### 4. Registration

```bash
impress-a tools            # must list 11
```

Eleven: `mock` ×5, `rfd3` ×1, `ligandmpnn` ×1, `boltz` ×1, `rosetta` ×3. The count *is* the
assertion — loading is validating, and a toolkit that fails anywhere registers **nothing**, so an
unknown gate id or a malformed spec shows up as a missing toolkit rather than an error. Ten means
something silently disappeared.

### 5. Preflight

```bash
impress-a preflight campaigns/delta-small-molecule-smoke.yaml
```

**Expected to fail here**, and that is the check: it must fail as a readable table of what is
missing (`FOUNDRY_SIF_PATH`, `MPNN_DIR`, `BOLTZ_CACHE`, `apptainer`, `boltz`, `import pyrosetta`,
`ligand_smiles`), not as a traceback. This is the command that runs on a Delta login node *before*
`sbatch`; running it locally proves its reporting path, not the environment.

### 6. Campaigns end to end

```bash
impress-a run campaigns/mock-stabilize.yaml --model D      # also A, and null
impress-a run campaigns/delta-small-molecule-smoke.yaml --model D
```

The mock campaigns must terminate with a stated reason and a non-empty Pareto front. The Delta
smoke campaign must **compose** a graph naming `rfd3_design…`, never `mock_generate…` — that
substitution is the bug that made the smoke test necessary in the first place.

Note these two are the only entries here that write: run directories under `campaigns/_runs/`, and
an `asyncflow.session.*` directory in the CWD per engine run. Sixty are sitting in the repo root
right now. Gitignored, but they accumulate — clean periodically.

### Also local, and undocumented elsewhere

```bash
python3 slides/timeline_model.py --limit 4   # stops t=135, before the first exploit run lands at t=144
python3 slides/timeline_model.py             # limit 6: runs to t=315, front forms at t=144
```

This is a live demonstration of backlog G1 — exploration can never move the front, so every informed
explore landing counts toward stagnation. Latent today because no shipped policy emits the truncated
explore chain; it fires the first time a `conduct()` reasoner explores the way the deck describes.

## Holes in this tier

Three of the four this file originally recorded are closed. What each cost, and what is left:

1. **The import contract has no test — CLOSED.** `tests/test_layering.py`. Writing it immediately
   surfaced two pieces of doc drift: `manager → tools` is real (`manager.py:39` imports `Registry`)
   and was missing from `architecture.md`'s table, and `cli`/`__main__` appeared in no row at all.
   Both were reconciled by fixing the doc up to the code, never by loosening the table. The test
   also guards the table itself against being edited to make a violation go away.

2. **No toolkit has known-bad fixtures — CLOSED** (backlog B2). Twenty fixtures across the five
   real tools plus `mock_noodle`, run by `tests/test_gate_fixtures.py` against each tool's own
   declared gates, with a rule — not a list — failing any future real tool that arrives without
   one. `count_matches_request` got its first test ever (B3). Two fixtures are filed as bug
   reports rather than reassurance: a LigandMPNN header that `_CONF_RE` cannot parse is currently
   reported as a design with 0.0 confidence, indistinguishable from a genuinely bad one; and
   `passes_ours_fails_upstream.good.json` is the executable record of G4, a payload our gates
   accept and upstream's calibrated thresholds reject.

   **Still open: B1.** Every fixture here is a JSON payload, because every gate is a threshold on a
   number. No fixture is *structural*, since no structural gate exists to feed one.

3. **The baselines are prose — CLOSED**, by deletion rather than by syncing. The tool count is now
   derived from disk (`test_the_registry_registers_every_tool_directory_on_disk`), which is the one
   that carries signal: loading is all-or-nothing, so a broken gate id removes a whole toolkit and
   shows up as a shorter list. The test and lint counts are simply no longer restated — a test
   asserting the test count fails on every legitimate addition, and a test shelling out to `ruff`
   would pin the suite to a lint version. The lint ceiling survives as prose in `backlog.md`, once.

   Found while doing this: `README.md` said **77 tests** in two places. The earlier 89 → 94 sync
   had missed it entirely, which is the argument for deleting the numbers rather than maintaining
   them.

4. **`timeline_model.py` is not in the tier — STILL OPEN, and worse than recorded.** `slides/` is
   gitignored (`.gitignore:11`) and has zero tracked files, so the model exists only in a working
   tree that happens to have it, while three tracked documents cite its output as evidence. G1's
   *behaviour* is now pinned by two characterization tests that need none of it
   (`test_core.py::test_a_node_missing_a_constrained_objective_is_never_feasible` and
   `test_campaign.py::test_a_truncated_chain_can_never_move_the_front`), so what is missing is only
   the *timing* evidence. Un-ignoring that one file is a repo-policy decision, deliberately left
   open rather than taken silently.

## Relationship to the other documents

`CLAUDE.md` stays the orientation for someone working on the code. `plans/backlog.md` keeps its
closing "verification that applies to any item" paragraph, which is about *change* — what any patch
must not break. This file is about the *tier* — what exists, what it proves, and what it misses.
