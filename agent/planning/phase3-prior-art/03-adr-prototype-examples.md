# `radical.adr` examples — prior-art review (Phase 3)

Repo: `radical.adr` (refcode root, read-only, branch `feature/prototype` — currently checked out HEAD,
confirmed via `git -C <repo> rev-parse --abbrev-ref HEAD`). All 11 files in `examples/` read directly off
disk. Citations use `radical.adr@feature/prototype:<path>:<line>`.

This builds on `docs/phase2-middleware/03-radical-adr.md`, which read the library source plus examples 04
and 09. This document covers the other nine and re-examines 04/09 only where the fuller set changes the
picture. Phase 2's verdict — "mine ADR for patterns, keep our own outer loop" — is treated as the baseline
to confirm or revise, not re-derived.

**Method note:** all findings below are from static reading of source + examples + docs (`ADR.md`,
`SYSTEM.md`, `docs/integrations/asyncflow.mdx`, `CHANGELOG.md`), the same standard Phase 2 used. No example
was executed — several require network LLM calls (03, 09), optional ML deps (`ROSE`, `sklearn` for 02), or
a RHAPSODY backend (10's non-`--local` path). Where a claim depends on runtime behavior I could not
execute, it is marked "inferred," not "confirmed."

---

## Per-example entries

### 01 — `asyncflow-adaptive-search.py`
Minimizes `f(x)=(x-TARGET)²+noise` by shrinking a `center`/`radius` window each cycle. State ("center",
"radius", "history") lives entirely as scalars in `Operator` attributes, mutated only through
`UPDATE_PARAM` actions (`radical.adr@feature/prototype:examples/01-asyncflow-adaptive-search.py:73-78`);
`@observe` re-derives `best`/`history` each cycle by reading `snapshot.objectives` and folding in new
`result.*` observation keys. Policy: plain rule `Policy` subclass, one `@decide`. **Transferable lesson:**
cross-cycle state is carried as a flat, named-scalar bag mutated via `update_param`, re-read from
`snapshot.objectives` — workable for scalar campaign parameters, but it has no notion of a typed
`CampaignObservation` or a lineage tree; anything beyond flat scalars (our Pareto front, budget ledger)
needs a translation layer, not this pattern directly.

### 02 — `rose-active-learning-steered.py`
Two ROSE `SequentialActiveLearner` instances, each run for 5 *internal* iterations inside **one** `@act`
call per cycle (`radical.adr@feature/prototype:examples/02-rose-active-learning-steered.py:129-138`) — ADR
only ever sees the aggregate final MSE, never ROSE's internal steps. Cross-cycle learner state (labeled/
pool data, fitted model) is persisted via **pickle files on disk**, keyed by learner id, read/written
inside module-level closures — a side channel entirely outside ADR's `state`/`Snapshot`. `EnsemblePolicy`
compares the two learners' MSE and reallocates `n_select` (active-learning budget) asymmetrically toward
the better performer (8 vs. 3). **On "steered":** this is ADR's own policy steering a *nested ML
pipeline's hyperparameter* between cycles — there is no external caller, no queue, no MCP, nothing
resembling control model C / headless steering. It is the same `Policy.decide(obs)->Decision` shape as
every other example. **Transferable lesson:** "wrap an entire nested sub-campaign as one opaque `@act`"
is a reasonable shape for treating an external tool as one task-agent boundary (relevant to Compute
Pattern P7), but the pickle-file side-channel state is an anti-pattern — it bypasses whatever typed state/
provenance boundary we build and should not be copied.

### 03 — `asyncflow-llm-adaptive-search.py`
Same search as 01, but `OpenRouterPolicy(LLMPolicy)` makes one real vendor call per `@decide`, using
`instructor.from_openai(...)` with `response_model=SearchDecision` (a Pydantic model) for structured output
(`radical.adr@feature/prototype:examples/03-asyncflow-llm-adaptive-search.py:70-86`). The prompt is built
from a class-level `system_prompt` string plus `self.render_observation(obs)` (JSON-dumped obs) — no
hidden hooks, everything inline in one method body. **Transferable lesson:** this is the cleanest, most
minimal worked reference for control model B's oracle-call boundary in the whole set: render obs → one
vendor call with a typed response schema → map fields straight onto `Decision`. Directly reusable as a
starting shape for our Model B policy's LLM-call boundary.

### 05 — `spawn-block.py`
One `@act` (`prepare_and_score`) calls `self.engine.block(workflow)(self.engine, candidate)`, where
`workflow` is a plain async function that builds two `engine.function_task`s and sequences them with plain
`await` — a two-step preprocess→score DAG assembled and run to completion inside the block, once per
candidate per cycle (`radical.adr@feature/prototype:examples/05-spawn-block.py:31-50,68-70`). **Important
correction to the framing this file was assigned under:** despite its name and the module docstring's
claim to demonstrate "`@act` returning a block Future," this example **never cancels anything** — no
`cancel_task`, `cancel_operator`, or `restart_operator` call appears anywhere in it; the block is simply
awaited to completion every time. It demonstrates `engine.block` as a sequential sub-DAG composition idiom
inside an `@act`, not the cancellation/backtracking mechanism it was expected to illustrate. Per ADR's own
docs (`ADR.md:274-278`, `docs/integrations/asyncflow.mdx:63-77`), the unmerged `feature/enable_block_
cancellation` branch is required specifically for *spawning, restarting, or cancelling operators or tasks
at runtime* — plain sequential `engine.block` composition, as used here, is not called out as needing it.
This example is therefore likely runnable against released (main-branch) asyncflow (inferred from docs
scoping + source, not executed) — but it establishes nothing about M4 backtracking/stop, contrary to
what its filename suggests.

### 06 — `multi-operator.py`
N fully independent `SearchOperator`s, one `WorkflowEngine` shared across all of them, driven via
`asyncio.gather(*[run_one(engine, c, id) for ...])`
(`radical.adr@feature/prototype:examples/06-multi-operator.py:103-110`); no shared state, no coordination.
**Transferable lesson:** validates that "one shared `WorkflowEngine`, N independent per-lineage loops"
composes cleanly with plain `asyncio.gather` — but these are N full independent campaigns (different
starting `center`), not cooperating branches of one design-lineage tree. Useful only as a template for
"the engine is shared infra, the loop-owner is per-lineage," which is exactly our own loop-ownership
decision — but no cooperation, sharing, or backtracking between lineages is demonstrated.

### 07 — `multi-operator-same-goal.py`
Same operator/policy as 06, but two operators race to the same convergence goal; the first to finish its
`run()` generator triggers a `done_callback` that calls `t.cancel()` on the other's wrapping `asyncio.Task`
(`radical.adr@feature/prototype:examples/07-multi-operator-same-goal.py:132-140`). That cancellation
propagates as a `CancelledError` into the loser's `Operator.run()` async generator, hitting its generic
`finally` block, which calls `future.cancel()` on every still-pending `state.task_futures` entry
(`radical.adr@feature/prototype:src/radical/adr/operator.py:680-683`). **This is the only one of the 11
examples that touches cancellation at all**, and it does so incidentally, at the plain-`asyncio.Task`
level — not through any of ADR's own `cancel_task`/`cancel_operator`/`restart_operator` action verbs. It
also cancels an entire campaign, never a single branch of a tree. Whether the underlying
`future.cancel()` call actually propagates into AsyncFlow's execution backend on *released* asyncflow (vs.
needing the unmerged branch's "patched_cancel fix" / "block-cancellation propagation," per `ADR.md`'s G1
and `docs/integrations/asyncflow.mdx`) could not be determined without running it against both.

### 08 — `hierarchical-operator.py`
A `CampaignOperator` statically declares one child (`explorer`) via `add_child` in `__init__`
(`radical.adr@feature/prototype:examples/08-hierarchical-operator.py:116-120`), then the policy
dynamically fans out `K` `refiner_i` children at runtime once `explorer.done`, each `depends_on=
"explorer"` (lines 153-162). The parent observes children through a read-only `ChildHandle`
(`obs["explorer"].done`, `.started`, `.status`, `.best_x` — `radical.adr@feature/prototype:src/radical/adr/
operator.py:177-221`) — no Futures, uids, or `child:*` keys touch policy code. `spawn_operator` is
idempotent, keyed on `.started`, so gating a fan-out on `if not explorer.started: spawn` needs no
user-managed "already spawned" flag. **No `cancel_operator`/`restart_operator` call appears anywhere in
this example** — only the happy-path spawn/observe cycle is exercised. **Transferable lesson:** the
idempotent-spawn-gated-on-observed-status idiom is a clean, small, genuinely reusable pattern for our own
dynamic fan-out bookkeeping — independent of whether we adopt ADR's operator hierarchy itself. But ADR's
hierarchy (independent state/policy/goals per node, "operator-of-operators") is a **different composition
axis** than our design-lineage tree (one policy per campaign, shared multi-objective Pareto front,
cross-lineage backtracking): it maps more plausibly onto an outer-loop spawning nested per-cluster/
per-batch task-agent sub-loops than onto representing sibling lineages of one tree. Per the CHANGELOG,
this whole feature (`SPAWN_OPERATOR`/`add_child`/`ChildHandle`) is explicitly the newest, least
field-proven part of ADR — and ADR's own gap G6 ("`start()` hierarchy not validated at scale") is
consistent with this being a toy 1-explorer/3-refiner tree, not evidence of scale.

### 09 — `langgraph-policy.py` (already covered by Phase 2 — noting only what the fuller set adds)
Same "one `@decide`, everything inline" shape as 03, but the reasoning step is delegated to a one-node
LangGraph graph, and — new relative to Phase 2's read — the LLM (via LangGraph) can propose a **new**
`Goal` at runtime, merged live into the active goal set with `Decision(actions=..., goals=new_goals)`
(`radical.adr@feature/prototype:examples/09-langgraph-policy.py:194-202`), no operator restart needed.
**Transferable lesson:** "runtime goal proposal from an oracle" is an interesting idea for Model B, but
ADR applies **zero governance** to it — any proposed `Goal` is accepted unconditionally. This is exactly
the missing validation-gate problem Phase 2 flagged (§7); do not copy the "accept unconditionally" part.

### 10 — `resource-aware-search.py`
Adds a second `Goal("cpu_healthy", metric="cpu_percent", threshold=CPU_LIMIT, direction="minimize")`
alongside the scientific convergence goal — both must be satisfied (implicit AND over a `list[Goal]`) to
stop (`radical.adr@feature/prototype:examples/10-resource-aware-search.py:73-84`). Resource "modeling" is
a **single scalar CPU percentage**, sourced one of two ways: (a) real path — subscribe to RHAPSODY
telemetry (`engine.start_telemetry(...).subscribe(callback)`) writing into a **module-level dict** read
inside `@observe` (the same side-channel-state pattern as 02's pickle files); (b) `--local` path — the
policy itself fabricates a decreasing CPU value via `update_param`, proving `Goal` is source-agnostic. The
policy throttles fan-out count (`n_tasks = 1 if cpu > 80.0 else 4`) but this is advisory only: the `Goal`
is checked as a **per-cycle threshold on the stop condition**, never as a pre-flight block on a specific
spawn, and it carries no memory of cumulative resource consumption. **This does not resemble our budget
ledger or resource-feasibility gate**: no GPU/CPU/node-count accounting, no cumulative spend, no
before-the-fact admission check — confirms Phase 2 §7 with a fully worked concrete example rather than
source-level inference alone, and additionally shows a trap: it would be easy to mistake a `Goal` for a
resource *gate* when it is only ever a stopping-condition input.

### 11 — `record-replay.py`
Precise mechanism, verified by direct reading: `RecordingObserver(str(trace_path))` is passed as
`observer=` at `Operator(engine, observer=...)` construction
(`radical.adr@feature/prototype:examples/11-record-replay.py:89`). Per cycle it writes one JSON line —
confirmed format `{"cycle": int, "obs": <raw dict>, "decision": decision.model_dump()}`. `replay_trace(path,
policy)` reads the JSONL back and, per line, calls `policy.decide(obs)` fresh using **only the recorded
`obs`** — the recorded `decision` is for inspection only, never fed back in (confirmed by
`docs/integrations/asyncflow.mdx:49`: *"`replay_trace` reads only the recorded `obs`... the recorded
`decision` is for inspection"*) — returning `list[Decision]` with no engine, no `Operator`, no task
dispatch at all. Notably, the operator being recorded here has **zero `@act` methods** — it never spawns a
single task; state is one scalar (`best_score`) mutated only via `update_param`. So the mechanism itself is
demonstrated working, but only on the simplest possible operator; nothing here shows replay against a
trace of a real multi-task campaign. And — confirming Phase 2's gap exactly — the trace captures nothing
beyond raw `obs` + `decision.model_dump()`: no prompt text, no model id, no rationale, no token/cost/
latency (`LLMPolicy.record_usage()` bookkeeping is a separate, disconnected in-memory `deque`, and this
example doesn't even use an `LLMPolicy`). The gap is structural, not something this example happens to
miss by omission.

### 04 — `protein-design.py` (already covered by Phase 2 — noting only what the fuller set adds)
Nothing new mechanically beyond Phase 2's read. In context of the other nine, it now reads as the
"reference happy path" that 01/05/10 all specialize from — same `@act`→`engine.function_task`, same
`@observe` result-folding, same `Policy(primary=,fallback=)` composition — confirming that this shape is
uniform across the entire domain-adjacent example, not a one-off.

---

## Synthesis table

| Example | ADR feature exercised | IMPRESS-A concern | Verdict |
|---|---|---|---|
| 01 | flat-scalar state via `update_param`, rule `Policy` | outer-loop state carry / control model D | **adapt** — workable for scalars, no typed observation or lineage tree |
| 02 | `@act` wrapping a whole nested sub-campaign; pickle-file side-state; comparative budget reallocation | task-agent boundary (P7); parallel-lineage budget split | **adapt** the wrapping idiom; **avoid** the side-channel-file state pattern |
| 03 | `LLMPolicy` + `instructor` + `response_model`, inline vendor call | control model B oracle-call shape | **adopt** |
| 05 | `engine.block` sequential sub-DAG inside one `@act` | Compute Pattern P7; (expected but absent) M4 backtrack/stop | **adapt** the block idiom; **not evidence** for cancellation — none demonstrated |
| 06 | `asyncio.gather` over N independent Operators, one shared engine | parallel lineages, shared execution infra | **adapt** — validates shared-engine/per-lineage-loop shape; no cooperation shown |
| 07 | done-callback race + incidental `asyncio.Task.cancel()` → generic `future.cancel()` in `run()`'s `finally` | M4 early-stop across lineages | **adapt cautiously** — only cancellation-touching example, coarse (whole-campaign), correctness on released asyncflow unverified |
| 08 | `add_child`/`spawn_operator`/`ChildHandle`, idempotent status-gated fan-out | outer-loop/task-agent split; dynamic fan-out | **adopt** the idempotent-gate idiom; **avoid** conflating with our lineage-tree model — different axis |
| 09 | LangGraph-as-`@decide`; runtime `Goal` proposal | control model A (delegated); ungoverned goal mutation | **adopt** the idea of an external framework as a policy body for A; **avoid** unconditional goal-mutation acceptance |
| 10 | second `Goal` for a resource scalar; side-channel telemetry read; policy-side throttling | budget ledger / resource-feasibility gate | **avoid** as a model — advisory, per-cycle, no cumulative accounting, no pre-spawn gate |
| 11 | `RecordingObserver`/`replay_trace` JSONL record + offline re-drive | control model D replay policy; provenance | **adopt** the mechanism; must extend schema for prompts/model ids/rationale ourselves |
| 04 | `Policy(primary=,fallback=)` resilience fallback (B→D) | control model B fallback | (Phase 2 territory — confirms uniformity, nothing new) |

---

## Does the example set change Phase 2's verdict?

**No — it reinforces it, with two findings that go beyond what the library source alone showed.**

1. **Every single one of the 11 examples cedes the entire outer loop to `Operator.run()` or
   `run_to_completion()`.** There is no example — including the multi-operator ones (06, 07, 08) — where
   ADR's pieces are invoked as a library *from inside* a caller-owned loop. 06/07/08 run multiple or
   nested full `Operator.run()` loops concurrently; they never call `_decide`/`_apply_actions` piecemeal
   or drive ADR one step at a time from outside. Every `main()` in the set is structurally
   `async for snapshot in op.run(): ...` or `await op.run_to_completion()`. If ADR ever demonstrated a
   "compose cleanly under a caller-owned loop" usage mode, it would be a significant finding revising
   Phase 2's recommendation — **it does not appear anywhere in this set.**
2. **Governance is absent across the board, confirmed concretely rather than by source inspection alone.**
   No example does a dry-run, a resource pre-check before spawn, or a cumulative budget check; 10's
   resource `Goal` — the closest attempt — is a per-cycle advisory threshold on the stop condition, never
   a gate on a specific spawn.
3. **New finding:** none of the 11 examples call `cancel_task`, `cancel_operator`, or `restart_operator`
   at all. The one example that touches cancellation (07) does so incidentally, at the plain-`asyncio`
   level, landing in a generic cleanup path. This means the exact mechanism Phase 2 flagged as depending
   on an unmerged asyncflow branch (block/task cancellation, relevant to our M4 backtrack/stop) is
   **entirely unexercised by the example suite** — we have zero empirical support from these examples that
   it works, independent of the unmerged-branch question.

**Verdict: unchanged. Mine for patterns, keep our own outer loop.** The evidence for this is now stronger,
not just theoretical (§6 of the Phase 2 doc) — it is confirmed by every one of eleven independent worked
examples with no exception.

---

## Control-model coverage — strict (demonstrated in code, not described)

| Model | Demonstrated in this example set? |
|---|---|
| **B** (heavyweight LLM oracle) | **Strongest.** 03 and 09 both contain complete, self-contained scripts making real vendor calls (`instructor`/OpenAI, LangChain/OpenAI via OpenRouter) with a full render→call→typed-parse→`Decision` pipeline. Confirms and extends Phase 2's 04/09 finding. |
| **D** (deterministic/rule/statistical) | **Strongest, most common.** 01, 02, 05, 06, 07, 08, 10, 11 are all plain rule `Policy` subclasses doing ordinary Python arithmetic against `obs`. |
| **A** (explicit multi-node agentic loop) | **Not demonstrated.** 09 delegates all multi-step reasoning to a single LangGraph node wrapped in one flat `Decision`; no example builds a multi-node hypothesize→parameterize→run→analyze graph inside ADR itself. Same conclusion Phase 2 reached from 09 alone. |
| **C** (external caller steering / headless control mode 2) | **Not demonstrated anywhere.** No example imports `radical.adr.mcp` or anything resembling an external steering channel. Example 02's "steered" in its title refers to ADR's own policy steering a nested ROSE pipeline's hyperparameter — an internal decision, not an external caller — and is unrelated to control model C. This doubly confirms Phase 2's finding that C is non-functional/aspirational: not only is the MCP path broken in source, the example suite does not even attempt to demonstrate a workaround. |

---

## Maturity

- **Dependency on the unmerged `feature/enable_block_cancellation` asyncflow branch is narrower than "all
  examples need it," but the one place it matters most (cancellation) is also the one place the example
  suite avoids exercising.** Per ADR's own docs (`docs/integrations/asyncflow.mdx:63-77`, `ADR.md:274-278`),
  the branch is required specifically for *spawning, restarting, or cancelling operators or tasks at
  runtime*. Source inspection shows `_sync_running_states` degrades gracefully rather than crashing on
  released asyncflow (`getattr(fut, "state", None) == "RUNNING"` — silently `None` if the attribute is
  missing: `radical.adr@feature/prototype:src/radical/adr/operator.py:813-818`), so plain task-spawning
  examples (01, 02, 03, 04, 06, 08, 09, 10) and block-composition-without-cancellation (05) are plausibly
  runnable against released asyncflow with degraded RUNNING-state visibility only — inferred from source
  and docs scoping, **not executed, so not confirmed**. Example 11 has no `@act` at all and is fully
  decoupled from any asyncflow-engine dependency at runtime — the example least likely to be affected by
  branch status. Example 07, the only one invoking `future.cancel()`, is the one place where I could not
  determine from source alone whether the behavior is correct on released asyncflow or silently degraded.
- **Self-consistency with library source is good** — every ActionSet method used in the examples
  (`spawn_task`, `spawn_operator`, `update_param`, the `__getattr__`-based `@act` shorthand,
  `ChildHandle.started`/`.done`/`.status`) matches the source exactly, and `Policy(primary=, fallback=)`
  composition in 04 matches `policy/base.py`'s implementation precisely.
- **One inconsistency worth flagging:** example 05's own module docstring frames it as demonstrating a
  cancellation-related mechanism ("`@act` returning a block Future... The `@act` method IS the workflow
  entry point"), and the phase-3 task brief inherited an expectation that it relates to
  cancellation/backtracking — but the code performs no cancellation at all. The docstring oversells what
  the example does; treat 05 only as a block-composition idiom.
- **Newest, least field-proven code is exactly what example 08 exercises.** Per `CHANGELOG.md`'s
  "Unreleased" section, `SPAWN_OPERATOR`/`add_child`/`ChildHandle` are called out as the newest addition
  landed alongside a batch of other hardening work; `ADR.md`'s own gap G6 ("`start()` hierarchy not
  validated at scale — 3+ levels, 50+ fan-out") is consistent with 08 being a toy 1-explorer/3-refiner
  tree, not evidence against that gap. No release tags exist; 0.1.0, single repo, actively churning —
  consistent with Phase 2's maturity read, now reinforced by which example is newest and least tested.

---

## Patterns for Phase 4

1. **Adopt** — `Policy.decide(obs) -> Decision` one-method dict-in/structured-out contract as a starting
   vocabulary for `ControlPolicy` (already Phase 2's call; reconfirmed across 8 more worked examples).
2. **Adopt** — `RecordingObserver`/`replay_trace` JSONL per-cycle record + offline re-drive mechanism (11)
   for our Model D replay policy: `observer=` kwarg at construction, one JSON line per cycle, replay reads
   only the recorded `obs`. Must extend the recorded schema ourselves for prompts/model ids/rationale text
   — nothing in this example (or ADR generally) does that already.
3. **Adopt** — the `LLMPolicy` "render_observation → one inline vendor call with a typed `response_model`
   → map straight onto `Decision`" shape (03) as the concrete boundary for our Model B oracle policy.
4. **Adopt** (idiom) — idempotent-spawn-gated-on-observed-status (`ChildHandle.started`/`.done`, 08) for
   our own dynamic fan-out bookkeeping, independent of adopting ADR's operator hierarchy wholesale.
5. **Adapt** — "wrap a whole nested sub-pipeline/sub-campaign as one opaque unit dispatched via a single
   task/block" (02's ROSE-in-an-`@act`, 05's `engine.block` sequential chain) for Compute Pattern P7 —
   keep the shape, replace the state-sharing mechanism (pickle files / module-level dicts, used
   identically in 02 and 10) with our own typed pre/post-process phases.
6. **Adapt** — `Goal`/`AllGoal`/`AnyGoal` as a stopping-condition primitive (confirms Phase 2); explicitly
   design around the trap example 10 exposes — a `Goal` is never a resource *gate*, only a stop-condition
   input; do not let it stand in for our budget ledger's pre-spawn feasibility check.
7. **Adapt** — shared-`WorkflowEngine` + N independent per-lineage `Operator.run_to_completion()` loops
   via `asyncio.gather`, optionally racing via done-callback cancellation (06, 07) — validates our
   "loop-owner is per-lineage, engine is shared infra" shape, but treat the cancellation semantics as
   unverified and coarse (whole-campaign, not sub-branch).
8. **Avoid** — ADR's hierarchical operator-of-operators model (08) as a stand-in for our design-lineage
   tree; it is a different composition axis (independent state/policy/goals per node vs. one shared
   multi-objective Pareto front with cross-lineage backtracking).
9. **Avoid** — treating any example as evidence for control model C; none touch MCP, and 02's "steered"
   title is unrelated internal self-steering.
10. **Avoid** — relying on example 07's incidental cancellation as validation that ADR's cancellation is
    ready for M4 backtrack/stop; it is the only touch-point in the whole suite, it is coarse, and its
    correctness against released (non-feature-branch) asyncflow could not be confirmed here.

---

## What could not be determined

- No example was executed. Whether examples 01, 02, 04, 05, 06, 08, 09, 10, 11 actually run to completion
  against released (main-branch) `radical.asyncflow`, versus silently degrading or failing, is inferred
  from source (`getattr` graceful fallback in `_sync_running_states`) and from ADR's own docs' explicit
  scoping of the feature-branch requirement — not confirmed by running either branch.
- Whether `future.cancel()` inside `Operator.run()`'s `finally` block (hit by example 07) actually
  propagates cancellation into AsyncFlow's execution backend on released asyncflow, or no-ops/misbehaves
  absent the unmerged branch's "patched_cancel fix," could not be determined without running both.
- Whether ADR's parent-child hierarchy has been exercised at any scale beyond the toy tree in example 08
  is explicitly unresolved by ADR's own gap G6 (already surfaced in Phase 2); this example neither
  confirms nor contradicts it.
- No pyproject/lockfile in this refcode pins an exact asyncflow git commit for the feature branch, so
  which exact asyncflow revision these examples were last verified against (by ADR's own authors, if
  ever) is unknown from this repo alone.

---

## Top 5 concretely reusable things (most valuable first)

1. **`LLMPolicy` render-observation → typed-vendor-call → `Decision` shape** (example 03) — the cleanest,
   most minimal, fully worked reference for our control model B oracle-call boundary anywhere in the
   refcode.
2. **`RecordingObserver`/`replay_trace` JSONL record + offline re-drive mechanism** (example 11) — cheap,
   directly useful base for our Model D replay policy and provenance store, provided we extend the
   schema for prompts/model ids/rationale ourselves.
3. **Idempotent-spawn-gated-on-observed-status idiom** (`ChildHandle.started`/`.done`, example 08) — small
   but genuinely reusable for our own dynamic fan-out bookkeeping, independent of adopting ADR's operator
   hierarchy.
4. **`Goal`/`AllGoal`/`AnyGoal` composite stopping-condition primitive** — solid building block for
   multi-condition stop criteria, so long as it is kept strictly out of the budget-ledger/resource-gate
   role (example 10's trap).
5. **Shared-engine, N-independent-per-lineage-loops-via-`asyncio.gather`, optional done-callback race**
   template (examples 06, 07) — validates that our own loop-ownership decision (our loop owns the cycle,
   the engine is shared infra) composes cleanly, without needing ADR's own coordination primitives at all.
