# Architecture

## The outer loop

One cycle, driven by `impress_a.manager.CampaignManager`:

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
           (policy)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

**Only `decide` differs between control models.** Everything below the policy layer is shared, which is
what makes frontends pluggable rather than parallel implementations.

| Step | Owner | Notes |
|---|---|---|
| observe | manager | Builds a `CampaignObservation` — front, population stats, budget, failures |
| **decide** | **policy** | Returns `ComposeAndRun \| Backtrack \| RequestHuman \| Stop` |
| compose | manager | Abstract intent → concrete typed DAG; P6 tools inlined |
| validate | manager | Five gates then dry-run; rejection returns a reason to the policy |
| execute | exec layer | Generic dispatch to asyncflow, per compute pattern |
| analyze | task agents | Typed metrics extracted; **QC gates enforced** |
| update | manager | Nodes appended, front recomputed, provenance written, budget charged |

## Layers

```
control/    CampaignControlPlane + transport adapters
policy/     ControlPolicy implementations (the decision frontend)
manager.py  the outer loop
core/       tree · pareto · budget · qc · decision · provenance · artifacts
compose/    TaskGraph · composer · five gates · self-promoting interlock
tools/      ToolSpec · registry · gate library · task agents
exec/       backend factory · resource normalization · dispatcher · job ledger
```

### Import contract

Enforced by review (and CI, where configured):

```
control  → manager, core
policy   → core                    (NOT tools, NOT exec)
manager  → policy, compose, exec, tools, core
compose  → tools, core             (NOT exec)
tools    → exec, core
exec     → core
core     → (nothing internal)
```

Two rules carry real weight:

- **`policy ↛ tools`, `policy ↛ exec`.** Policies emit *abstract* `ExperimentIntent`; turning intent into
  a concrete DAG is the composer's job. If a policy can reach a tool adapter, the seam rots and control
  models stop being interchangeable.
- **`compose ↛ exec`.** Composition and validation must be testable with no backend at all — that is what
  makes the whole laptop test tier possible.

## Composition and validation

The agent composes **arbitrary typed DAGs at runtime**. Five gates run before anything executes, then a
dry-run in which every task agent parameterizes *without* executing:

| Gate | Rejects |
|---|---|
| 1 type | An edge whose producer output type does not unify with the consumer input type |
| 2 structure | Cycles, empty graphs, a tool composed without its QC gates |
| 3 parameter | Out-of-range values, unknown parameters, any `frozen_parameters` |
| 4 resource | P6 scheduled, resource shapes exceeding the site, unproven GPU portability, disallowed external submission |
| 5 budget | An estimate exceeding remaining budget in any dimension |

Rejection is cheap and informative: the policy receives a structured `ValidationFailure` through
`on_rejected` and gets another attempt within the same cycle, bounded by `max_attempts`.

### The self-promoting interlock

Novel composition patterns are never blocked and never trusted on sight. A **pattern** is the graph's
*shape* — tool ids plus typed edges, parameter values excluded, so tuning a parameter does not reset
accumulated trust.

| | Trusted | Provisional |
|---|---|---|
| Cost ceiling | Normal budget rules | Capped fraction of remaining budget |
| Dry-run | Standard | Mandatory |
| Result marking | Normal QC verdict | **Auto-marked `suspect`** regardless of outcome |

Promotion is mechanical — N consecutive clean runs. Demotion is symmetric and immediate on any failure.
The trust ledger is **site-scoped and spans campaigns**, because one campaign may not run a pattern N
times.

## Campaign state

An **append-only tree** of design lineages ranked by a **multi-objective Pareto front**, with
non-destructive backtracking.

- Constraints prune, directions rank. Cost is a first-class objective, not an afterthought.
- **A node whose QC verdict is `FAIL` is never eligible for the front, whatever its scores.** This is the
  single most important coupling in the system: these tools fail silently, so a successful exit code is
  never sufficient evidence.
- `replicas: N` means **N independent lineages**, one design node each.
- A measurement **supersedes but never deletes** a prediction (`docs/decisions/0012`), so the front is
  **not monotonic** once assays arrive — a node promoted on an optimistic prediction can be demoted by
  its own measurement.

## Task agents

Per tool, four phases: **pre-process → parameterize → execute → post-process**. `ToolSpec.agent` declares
whether the agent is deterministic code or LLM-driven.

`execute()` is not overridden by tool adapters — pattern dispatch belongs to the execution layer, and an
adapter scheduling its own work would bypass the P6-inline and P4-ledger rules.

**QC gates are deterministic in both cases.** An LLM may author a protocol; it does not judge whether the
result passed its clash check.
