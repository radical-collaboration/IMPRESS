# Architecture

## The outer loop

One experiment, driven by `impress_a.runtime.executor.CampaignExecutor`. The steps below happen in
this order for any one experiment — but the reasoner is no longer the loop body, so several
experiments can be at different steps at once:

```
observe ─→ SPECIFY ─→ PLAN ─→ compose ─→ review ─→ execute ─→ analyze ─→ update ─→ terminate?
           (Spec      (Stage   (typed     (coverage, (asyncflow) (QC       (tree,
            revision)  of       DAG)       5 gates,              gates)    Pareto,
                       Tasks)              budget,                         provenance)
                          │                dry-run)
                          └── reject ──→ back to PLAN (bounded retry, with the gate and reason)
```

How the campaign's inputs become that Spec and that Stage — the toolkit, the goal, the budget and
the parameters, step by step with the refusal guarding each — is
[`resolution.md`](resolution.md).

**Only the reasoner differs between control models.** Everything below the policy layer is shared,
which is what makes frontends pluggable rather than parallel implementations.

There are two ways to be a reasoner:

- **a Specifier and a Planner** - two halves, with separate contracts. The Specifier turns the
  caller's `Goal` into a mutable `Spec` of atomic objectives and revises it as data arrives; the
  Planner maps the objectives that are ready onto Tasks and emits a candidate `Stage`.
  `runtime.roles.RolesDriver` runs both as the Listener, Specifier, Planner and Deployer over one
  `CampaignSession`. **This replaced `decide(obs) -> Decision`**, which answered "what should the
  campaign be trying to achieve" and "which tool should run next" in a single call - so no
  transcript could say which half of a control model earned its cost, which is exactly what the
  four-arm comparison needs to say. What each shipped model does with the two contracts, and what
  it is shown when it does, is [`control-models.md`](control-models.md).
- **`conduct(session)`** - drive yourself. The reasoner runs as its own coroutine and reaches the
  executor through `core.session.CampaignSession`: submit as many experiments as it wants, then
  collect them with `as_completed` in the order they finish. This is what makes a federation of
  task agents generating an ensemble in parallel expressible at all.

The executor owns all campaign state and is its **only writer**; it also decides termination, because
budget, stagnation and repeated failure are facts about state a reasoner cannot see. A reasoner may
*request* a stop.

| Step | Owner | Notes |
|---|---|---|
| observe | manager | Builds a `CampaignObservation` — front, population stats, budget, failures, and the `ToolkitView` a reasoner chooses from |
| **specify** | **policy** | `Specifier.revise` returns a `SpecRevision` — objectives to add, delete or re-status. The executor applies it and is the only writer |
| **plan** | **policy** | `Planner.plan` returns a candidate `Stage` of `TaskMapping`s, or `None`. `replan` answers a rejection; `RequestHuman` and a stop request remain available through the session |
| compose | manager | A Stage (or abstract intent) → concrete typed DAG. P6 inlining is designed but not built, so a P6 declaration is refused at load |
| review | manager | Coverage against the applied Spec, six gates, budget, then dry-run; rejection returns the gate and reason to the Planner |
| execute | exec layer | The Stage runs as one asyncflow **block** on the campaign's single engine; each node's adapter is a task on the `local` route and each tool command an executable task on `compute`, placed per backend |
| analyze | task agents | Typed metrics extracted; **QC gates enforced** |
| update | manager | Nodes appended, front recomputed, provenance written, budget charged |

## Layers

```
control/    CampaignControlPlane + transport adapters
policy/     the decision frontend: specifiers/ + planners/ (one module per control
            model), the reasoning seam, and the role wrappers
manager.py  the outer loop
core/       tree · pareto · budget · qc · decision · provenance · artifacts
compose/    TaskGraph · composer · five gates · self-promoting interlock
tools/      ToolSpec · registry · gate library · task agents
exec/       engine + named backend routes · Stage-as-block · command launcher ·
            placement · job ledger
analysis/   per-Task validation and the four-arm scoring harness. May not import
            `policy` or `control`: a scorer that could reach a reasoner could score a
            campaign by asking it
```

### Import contract

Asserted by `tests/test_layering.py`, which walks the source with `ast` and checks every
internal import against this table. `ast.walk` is used deliberately: the real adapters defer their
science imports into `run()` bodies, and a deferred `from ..exec import ...` inside `compose` would
be exactly as fatal as one at the top of the file.

```
cli          → control, manager, runtime, policy, compose, tools, core, analysis
control      → manager, runtime, core
policy       → core                           (NOT tools, NOT exec, NOT runtime)
manager      → runtime, policy, tools, core   (a facade; the executor owns the work)
runtime      → policy, compose, exec, tools, core
compose      → tools, core                    (NOT exec)
tools        → exec, core
exec         → compose, tools, core
analysis     → runtime, exec, compose, tools, core   (NOT policy, NOT control)
integrations → cli, manager, runtime, tools, core    (NOT exec)
core         → (nothing internal)
```

`__main__` imports `cli` and nothing else. `integrations` is a second composition root, like `cli`:
nothing else in the package imports it, so an adapter may name another project's types without any
layer of IMPRESS-A knowing that project exists. `exec` is absent from its row on purpose — an
integration drives the executor, it does not dispatch.

Three notes on accuracy. `exec → compose, tools` has been true since the first prototype
(`exec/stage.py` imports `TaskGraph`, `exec/dispatch.py` imports `TaskAgent`); this line records what
the code does rather than what an earlier version of this document claimed. And `policy → core` is what forced
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

## One engine, and two boundaries

All task work in a campaign is deployed by **one** long-lived `radical.asyncflow` `WorkflowEngine`,
which reaches Dragon only through rhapsody. It carries named routes: `compute` (Dragon on an
allocation, rhapsody's concurrent backend off one), `local` (a thread pool for adapters and QC), and
`ai` when the campaign declares a locally hosted reasoner. A Stage is one `@flow.block`, so the
block's future is the graph's result and cancelling it cascades to every unfinished member on the
backend that member was routed to.

The other boundary is between processes. `impress-a run` keeps the reasoner and the executor in one
process as two asyncio tasks — the executor's pump raced against the reasoner's `conduct` — and
`impress-a serve` + `impress-a control` splits them, with `CampaignSession` as the seam. What does
**not** split is the engine: it belongs to the loop it was built on, and a second engine or a second
event loop is not how the processes are separated. The Reviewer and Deployer stay execution-side
because the dry-run instantiates task agents and must run where the toolkit is installed.

Both boundaries, what each one buys, and what it does not, are recorded in
[decision 0015](../decisions/0015-one-engine-and-the-process-boundary.md).

## Composition and validation

The agent composes **arbitrary typed DAGs at runtime**. Six gates run before anything executes, then a
dry-run in which every task agent parameterizes *without* executing — which proves parameter values
are legal and nothing about the command that will run ([`invocation.md`](invocation.md), step 3):

| Gate | Rejects |
|---|---|
| 1 type | An edge whose producer output type does not unify with the consumer input type |
| 2 structure | Cycles, empty graphs, a tool composed without its QC gates |
| 3 parameter | Out-of-range values, unknown parameters, any `frozen_parameters` |
| 4 resource | P6 scheduled (unreachable now that a P6 declaration fails at load, and kept as a backstop), resource shapes exceeding the site, unproven GPU portability, disallowed external submission |
| 5 budget | An estimate exceeding remaining budget in any dimension |
| 6 tool delivery | Mock tools in a campaign that declares `tool_delivery: real`, and the reverse |

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

Promotion is mechanical — N consecutive clean runs, where *clean* means no task failed and no **integrity**
gate failed. Demotion is symmetric and immediate on any integrity failure. **Acceptance** gates (quality
thresholds) still fail the node and keep it off the front, but say nothing about whether the pattern is
sound, so they do not touch trust ([decision 0013](../decisions/0013-trust-counts-integrity-not-acceptance.md)).
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
- A measurement **supersedes but never deletes** a prediction ([decision 0012](../decisions/0012-one-property-two-sources.md)), so the front is
  **not monotonic** once assays arrive — a node promoted on an optimistic prediction can be demoted by
  its own measurement.

## Task agents

Per tool, four phases: **pre-process → parameterize → run → post-process**, driven by
`TaskAgent.__call__`. An adapter overrides `run()` only; the inherited `parameterize` and
`post_process` are what make parameter checks and QC gates impossible to skip. `ToolSpec.agent`
declares whether the agent is deterministic code or LLM-driven, and nothing reads it yet: every
shipped adapter is deterministic code.

Inside `run()` the adapter builds its tool's command in one pure function and hands it to `run_cmd`,
which submits it to the engine as a placed task — an adapter that started a process any other way
would run it on the campaign host, unplaced and unrecorded. The whole path from a spec to a running
command, with each shipped tool's command written out, is [`invocation.md`](invocation.md).

**QC gates are deterministic in both cases.** An LLM may author a protocol; it does not judge whether the
result passed its clash check.
