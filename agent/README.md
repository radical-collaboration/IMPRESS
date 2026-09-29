# IMPRESS-A

**Autonomous protein design on HPC.**

IMPRESS-A conducts scientific exploration of protein design space given a design prompt — *"stabilize the
given protein"* — by repeatedly deciding what experiment to run next, composing a workflow to run it,
executing that workflow on HPC, interpreting the result, and updating a population of design candidates.

*Autonomous* here has a specific meaning: workflow parameters **and topology** are modified at runtime in
response to production data. The agent is not a pipeline with a smart scheduler; it composes new
workflows each cycle from a registry of tools.

---

## Architecture

### One experiment, one variable step

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
         (reasoner)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

Those steps happen in that order for **any one experiment** — but the reasoner is not the loop body,
so several experiments sit at different steps at once. The executor owns all campaign state and is
its only writer; it reaps runs as they finish and decides termination, because budget, stagnation and
repeated failure are facts about state a reasoner cannot see.

**Only the reasoner differs between control models.** Everything below it — composition, validation,
execution, state, provenance — is shared. That is the whole design: a campaign run by a hand-written
rule cascade exercises identical machinery to one steered by a frontier LLM.

There are two ways to be a reasoner:

- **`decide(obs) -> Decision`** — answer one question at a time. Models A-D do this, and a driver
  plays the part the old loop played: observe, ask, submit, wait, repeat.
- **`conduct(session)`** — drive yourself. Submit as many experiments as you like, then collect them
  with `as_completed` in the order they *finish*. This is what makes a federation of task agents
  generating an ensemble in parallel expressible at all.

### Pluggable frontends

Two independent frontend axes plug into the same engine. Neither requires changes below the layer it
occupies.

```
        ┌──── INTERFACE FRONTEND ──────┐       who talks to the campaign
        │  in-process · HTTP+SSE · MCP  │
        └───────────────┬───────────────┘
                        │  CampaignControlPlane — one protocol, adapters translate transport only
        ┌───────────────┴───────────────┐
        │      DECISION FRONTEND        │      who decides what runs next
        │    A · B · C · D · your own   │
        └───────────────┬───────────────┘
                        │  ControlPolicy — decide() → ComposeAndRun | Backtrack | RequestHuman | Stop
        ═════════════════════════════════       shared engine
           runtime executor · CampaignSession
           compose · validate · tools · exec
```

**Decision frontend — four control models**, exactly one active per campaign, fixed at launch:

| | Model | Mode | `decide` |
|---|---|---|---|
| **A** | Four-node agentic loop | autonomous | A LangGraph graph: hypothesize → parameterize, auditable node by node |
| **B** | Heavyweight LLM oracle | autonomous | One structured call over rich campaign state |
| **C** | External caller steering | **headless** | Blocks on the control plane for a directive |
| **D** | Explicit policy | autonomous | Rules, bandit, Bayesian optimization, or replay — fully reproducible |

Writing a fifth is subclassing `BasePolicy` and implementing one method. Policies emit *abstract intent*,
never a concrete DAG, which is what keeps them swappable. They compose: wrap any policy in
`RuleCorrectionsPolicy` for an unconditional external guard, or `LoggingPolicy` for provenance.

**Interface frontend — control-plane adapters.** One transport-agnostic protocol (`observe`, `events`,
`steer`, `artifacts`, `provenance`, `ingest_measurement`, lifecycle). `observe()` returns the **same
observation object a policy's `decide` receives** — informed monitoring means parity of evidence, not a
progress bar. The protocol also carries runs by id — `submit_run`, `list_runs`, `run_result`,
`cancel_run` — with **synchronous admission**: accepted with an id, or refused with the gate and the
reason that refused it. In-process and HTTP+SSE adapters ship; MCP is the same protocol behind a
different transport.

**The substrate is pluggable too.** Execution backends are selected *by name* from site configuration —
`concurrent` on a laptop, `dragon` or `radical` on HPC — so no backend class is named outside one module.

### What the engine guarantees

- **Free graph composition, five gates.** Type, structure, parameter, resource and budget checks run
  before anything executes, then a dry-run in which every task agent parameterizes without executing.
  Rejection hands the policy a structured reason and another attempt.
- **A QC-failed node is never rankable**, whatever its scores. Scientific tools fail *silently* far more
  often than they crash, so a zero exit code is never sufficient evidence.
- **A self-promoting interlock.** Novel workflow shapes are neither blocked nor trusted on sight: they
  run under a cost cap and a forced dry-run, are marked `suspect` regardless of outcome, and promote only
  after N clean runs — demoting immediately on any failure.
- **Append-only state.** A tree of design lineages ranked by a multi-objective Pareto front, with
  non-destructive backtracking and a complete provenance log.
- **Predicted and measured values are one type.** An objective is declared against a property *name*, so
  a surrogate today and a wet-lab assay tomorrow are interchangeable with no change to the campaign spec.
- **Concurrency that does not lie about evidence.** An *untrusted* workflow shape may have only one
  instance in flight, because promotion counts consecutive clean runs and concurrent instances are one
  draw sampled N times. Stagnation counts *informed* attempts for the same reason — a wave of runs
  launched before any of them reported is one attempt, not N.
- **Typed, serializable artifacts.** A tool hands on an `ArtifactRef` — declared type, path or inline
  value, size and content digest — never a bare string. That is what lets a reasoner in another process
  hold a result, compare it, and pass it back without the file crossing the wire.
- **Durable runs.** Every submission and outcome is written to an append-only ledger, so a finished
  run's result is recoverable by id from a process that did not produce it.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest tests -q                                           # the whole local tier, ~10s, no allocation
impress-a tools                                           # list registered tools
impress-a run campaigns/mock-stabilize.yaml --model D     # run a campaign
```

A complete campaign runs on a laptop against the bundled mock toolkit — real manager, real policies, real
composer and validator, with stubbed science. That is deliberate: HPC iteration is slow and expensive, so
almost everything is verifiable locally.

```
$ impress-a run campaigns/mock-stabilize.yaml --model A
  cycles : 3
  stop   : front target reached
  nodes  : 6  front: 3
    n000004 qc=pass  sc_rmsd=2.023 iptm=0.645 ddg=1.517
    n000005 qc=pass  sc_rmsd=0.431 iptm=0.906 ddg=-2.04
    n000006 qc=pass  sc_rmsd=2.116 iptm=0.607 ddg=0.073
```

## Defining a campaign

```yaml
campaign_id: stabilize-lysozyme
goal: "Stabilize the given protein while preserving the designed fold"
backend: concurrent                 # or dragon / radical on HPC
budget: {gpu_hours: 2.0, cpu_hours: 12.0}
objectives:
  - {name: sc_rmsd, direction: minimize, max: 3.0}    # constraints prune
  - {name: iptm,    direction: maximize, min: 0.55}   # directions rank
  - {name: ddg,     direction: minimize}
```

## Adding a tool

A declarative `spec.yaml` plus a `TaskAgent` subclass, in a toolkit directory alongside the `SKILL.md`
that tells an agent how to use it. Loading is validating — a bad range, an unknown QC gate, or a missing
skill section fails at load, and a toolkit that fails anywhere registers nothing. Adding a tool never
requires touching the composer, validator or manager. See
[`docs/reference/authoring-tools.md`](docs/reference/authoring-tools.md).

## Requirements

Python **≥3.11** where Dragon is used; **3.10** suffices for the mock/laptop path. Scientific tools run
as subprocesses or in containers and do not constrain the agent environment. Built on
[`radical.asyncflow`](https://github.com/radical-cybertools/radical.asyncflow) and
[`rhapsody`](https://github.com/radical-cybertools/rhapsody); LangGraph drives the control-model-A loop.

## Documentation

| | |
|---|---|
| [`docs/reference/architecture.md`](docs/reference/architecture.md) | The loop, layers, import contract, invariants |
| [`docs/reference/frontends.md`](docs/reference/frontends.md) | Control models and control-plane adapters in detail |
| [`docs/reference/compute-patterns.md`](docs/reference/compute-patterns.md) | P1–P8 — normative for every `ToolSpec` |
| [`docs/reference/authoring-tools.md`](docs/reference/authoring-tools.md) | Writing tools, gates and skill documents |
| [`docs/reference/middleware-integration.md`](docs/reference/middleware-integration.md) | asyncflow / rhapsody seam and its gotchas |
| [`docs/decisions/`](docs/decisions/) | Numbered, immutable architecture decision records |
| [`docs/limitations.md`](docs/limitations.md) | Known gaps and residual risks, stated plainly |

`planning/` holds the design record that produced this system. It is process history, not reference
documentation, and is not part of the published package.

## Status

Reference implementation, exercised end to end on a laptop and not yet on real hardware.

| | |
|---|---|
| Engine — compose, five gates, interlock, Pareto tree, provenance | works |
| Four control models (A/B/C/D), plus `conduct` reasoners | works |
| Concurrent experiments, durable runs, reattach after restart | works |
| Control plane — in-process and HTTP+SSE adapters | works |
| Mock toolkit campaign | works |
| Real toolkits (RFdiffusion3, LigandMPNN, PyRosetta, Boltz) | wired, CLI contracts verified against real installs, **never executed** |

`pytest tests -q` — ~10s, no allocation. A complete campaign runs on a laptop with stubbed
science, which is deliberate: HPC iteration is slow and expensive, so almost everything is verifiable
locally. The corollary is that everything *only* verifiable on HPC is unverified.

## Known issues

**No real campaign has ever run.** The four real toolkits register, validate, type-check as a chain
and dry-run, and their adapters invoke real binaries — but no line of RFdiffusion, LigandMPNN,
PyRosetta or Boltz code has executed through this system. Treat the real path as untested.

**The Dragon backend can hang silently during construction.** `Batch()` is built synchronously with
no `await` points, so a stall there blocks the event loop entirely — no heartbeat, no timeout, until
whatever wall-clock limit kills the job. Measured, not theoretical: job 22318678 spent its full
2-hour allocation this way. Bounded now by `backend_startup_timeout_s`/`backend_startup_heartbeat_s`
on `CampaignSpec` (both Delta campaigns set 600s); see `docs/limitations.md`.

**`ligand_smiles` was empty** in both Delta campaign specs. Resolved for the ALR benchmark target
(`campaigns/data/alr/`, borrowed from the original IMPRESS project) — both campaigns now set it to
the real ligand's SMILES, and a fail-fast check catches any future target that leaves it blank
instead of silently modeling no ligand.

**Three tool arguments were unverified** and are now checked directly against the installed real
toolkits on Delta: LigandMPNN's and Boltz's seed/batch flags were confirmed correct as written.
RFD3's contract was not merely unverified but **wrong** — it invoked flags (`--config`/`--out`) the
real Hydra-based CLI doesn't have — and has been rewritten to the real contract. `boltz_predict` was
also found to be missing a required `--no_kernels` flag along the way. Run `impress-a preflight` on
a login node first regardless — it now also checks `ligand_smiles`.

**QC for the real toolkits is thin where it matters most.** The specs lean almost entirely on
`metric_in_range` against each tool's *own* self-reported confidence — which is exactly what a
confidently-wrong tool passes. There are no structural gates (is the ligand actually in the output
complex, are there chain breaks, does sequence length match the contig). Every real tool now
carries the known-bad fixtures `docs/reference/authoring-tools.md` asks for, so its declared gates
have been seen to fail on output that should fail them; what those gates *measure* is still the
tool's own opinion of itself.

**Cancellation is advisory.** Measured, not assumed: the concurrent backend's `Future.cancel()`
returns `False` once a callable has started and asyncflow discards that answer, so queued work is
reclaimed and running work is not. A run's terminal state always comes from collecting it. Reclaiming
a GPU from an abandoned run is unsolved.

**Cost models are unmeasured.** Gate 5 and the interlock's 10% provisional cap refuse graphs against
literature figures, not measurements. This already bites: a campaign budget can be too small to admit
its own first run.

**`sites/*.yaml` is read by no code.** Its `tool_delivery: {real|mock}` switch is inert.

## Plans

`plans/` holds the working plans: [`plans/backlog.md`](plans/backlog.md) is the live list of
outstanding work with a recommended order, `plans/*.md` are stubs for the next tracks, and
`plans/done/` records completed work and the decisions behind it — the rulings are the part worth
keeping, not the task lists.

Nearest term: structural QC gates (the known-bad fixtures now exist), then the first real Delta run. Further out:
the MCP adapter, checkpoint/restart resume (the ledger and `reattach` exist; nothing resumes from
them yet), registry hardening, and the P5 network-service governor.
