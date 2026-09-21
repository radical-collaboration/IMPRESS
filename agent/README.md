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

### One loop, one variable step

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
           (policy)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

**Only `decide` differs between control models.** Everything below the policy layer — composition,
validation, execution, state, provenance — is shared. That is the whole design: a campaign run by a
hand-written rule cascade exercises identical machinery to one steered by a frontier LLM.

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
           manager · compose · validate
           tools · exec · rhapsody backends
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
progress bar. The in-process adapter ships; HTTP+SSE and MCP are the same protocol behind a different
transport.

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

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest tests -q                                           # 29 tests, ~7s, no allocation needed
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

Reference implementation: engine, all four control models, and a runnable mock campaign. Real tool
adapters, the HTTP and MCP adapters, checkpoint resume, and the network-service governor are not yet
built — see [`docs/limitations.md`](docs/limitations.md), which also records cancellation as the known
open risk.
