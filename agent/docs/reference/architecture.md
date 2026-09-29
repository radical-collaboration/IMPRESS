# Architecture

## The outer loop

One experiment, driven by `impress_a.runtime.executor.CampaignExecutor`. The steps below happen in
this order for any one experiment — but the reasoner is no longer the loop body, so several
experiments can be at different steps at once:

```
observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update ─→ terminate?
           (policy)   (typed     (5 gates    (asyncflow) (QC        (tree,
                       DAG)       + dry-run)             gates)     Pareto,
                                      │                             provenance)
                                      └── reject ──→ back to DECIDE (bounded retry)
```

**Only the reasoner differs between control models.** Everything below the policy layer is shared,
which is what makes frontends pluggable rather than parallel implementations.

There are two ways to be a reasoner, and the second is the reason the first still works unchanged:

- **`decide(obs) -> Decision`** — answer one question at a time. Models A, B, C and D all do this, and
  `policy.driver.SequentialPolicyDriver` plays the part the manager's loop used to play: observe, ask,
  submit, wait, repeat.
- **`conduct(session)`** — drive yourself. The reasoner runs as its own coroutine and reaches the
  executor through `core.session.CampaignSession`: submit as many experiments as it wants, then collect
  them with `as_completed` in the order they finish. This is what makes a federation of task agents
  generating an ensemble in parallel expressible at all.

The executor owns all campaign state and is its **only writer**; it also decides termination, because
budget, stagnation and repeated failure are facts about state a reasoner cannot see. A reasoner may
*request* a stop.

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

Asserted by `tests/test_layering.py`, which walks the source with `ast` and checks every
internal import against this table. `ast.walk` is used deliberately: the real adapters defer their
science imports into `run()` bodies, and a deferred `from ..exec import ...` inside `compose` would
be exactly as fatal as one at the top of the file.

```
cli      → manager, policy, compose, tools, core
control  → manager, runtime, core
policy   → core                           (NOT tools, NOT exec, NOT runtime)
manager  → runtime, policy, tools, core   (a facade; the executor owns the work)
runtime   → policy, compose, exec, tools, core
compose  → tools, core                    (NOT exec)
tools    → exec, core
exec     → compose, tools, core
core     → (nothing internal)
```

`__main__` imports `cli` and nothing else.

Three notes on accuracy. `exec → compose, tools` has been true since the first prototype
(`exec/dispatch.py` imports `TaskGraph` and `TaskAgent`); this line records what the code does rather
than what an earlier version of this document claimed. And `policy → core` is what forced
`core/session.py` and `core/results.py` to exist: a reasoner may hold a `RunOutcome`, so `RunOutcome`
cannot live in `exec/` beside the `ExecutionResults` it projects from. And `manager → tools` is
real — `manager.py` imports `Registry` — and was missing from this table until the layering test
was written; `cli` and `__main__` appeared in no row at all. Both are recorded above rather than
quietly tolerated, because a contract with undocumented edges is not a contract.

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
