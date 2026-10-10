# `radical.adr` — RADICAL Autonomous Decision Runtime (v0.1.0)

Refcode root (read-only): `<workspace>/impress-a-refcodes/middleware/radical.adr/`

---

## 1. What ADR actually is

ADR is a small, self-contained **Observe → Decide → Act (ODA) runtime** for steering long-running
HPC workflows executed by `radical.asyncflow`. It is not a task-execution engine and not an agent
framework in the LangGraph/multi-agent sense — it is the *steering loop* that sits between domain
science and AsyncFlow, per `SYSTEM.md` §1:

```
Domain Science (IMPRESS · ROSE · Campaign Manager)
    radical.adr  (Operator · Policy · Goals · Decision · ActionSet)
        │  AsyncFlow API
radical.asyncflow (WorkflowEngine · function_task · engine.block)
        │  execution backend
RADICAL-Pilot · LocalExecutionBackend · HPC cluster
```

Its own summary (`ADR.md`, "Sacred boundary", `SYSTEM.md:30`):

> "the Operator only Observes, Decides, and Acts. It never owns scheduling, execution lifecycle, or
> distributed resources."

Central classes, all real and implemented in `src/radical/adr/`:
`Operator` (`operator.py`, 1317 lines — the runtime core), `Policy`/`@decide`/`LLMPolicy`/`ChainPolicy`
(`policy/`), `Goal`/`AnyGoal`/`AllGoal` (`goals.py`), `Decision`/`Action`/`ActionKind` (`decision.py`),
`RuntimeState`/`Snapshot` (`state.py`), `ActionSet` (`tools/__init__.py`), `ObserverBase`/
`RecordingObserver`/`replay_trace` (`observer.py`, `recording.py`).

`README.md` (verbatim):

> "ADR autonomously and dynamically orchestrates agent-based systems—powered by large language
> models (LLMs), rule-based reasoning engines, or hybrid approaches—to establish objectives, evaluate
> conditions, make decisions, and execute actions within well-defined policy, governance, and safety
> constraints."

This description is largely accurate for what's built, with one important caveat on "governance...
safety constraints" — see §6.

---

## 2. Vocabulary mapping

| ADR term | Our term (Part B) | Match |
|---|---|---|
| `Operator` | the agent / campaign runtime | close, but ADR's Operator **owns the loop** (§5) |
| `Operator.run()` cycle (RUN→OBSERVE→DECIDE→ACT) | our `observe→decide→compose→validate→execute→analyze→update→terminate?` loop | overlapping but coarser — ADR's DECIDE+ACT collapse compose/validate/execute/analyze into one step (§5) |
| `@observe` → `obs: dict` | `CampaignObservation` | ADR's is an **untyped `dict`**; ours is a typed object |
| `Policy.decide(obs) -> Decision` | `ControlPolicy.decide(obs) -> Decision` | same name, **different shape** (§3) |
| `Decision` (flat: actions + stop + goals + delegate_to + notify) | `Decision` (discriminated union: `ComposeAndRun\|Backtrack\|RequestHuman\|Stop`) | different factoring — see §3 |
| `Action` / `ActionKind` (SPAWN_TASK, CANCEL_TASK, RETRY_TASK, SPAWN_BLOCK, SPAWN_OPERATOR, RESTART_OPERATOR, CANCEL_OPERATOR, UPDATE_PARAM) | our "compose" (typed DAG) + "execute" phases | ADR's actions are **flat dispatch verbs against a registry of pre-declared `@act` methods**, not a runtime-composed arbitrary DAG (§4) |
| `Goal` (name, metric, threshold, direction, `for_cycles` debounce; `AllGoal`/`AnyGoal` combinators) | our multi-objective Pareto front + stopping criteria | ADR's goals are **scalar threshold predicates**, not a Pareto front; closer to "stopping conditions" than to our objective/lineage model |
| `RuntimeState` / `Snapshot` (observations/runtime/objectives/artifacts/directives/task_context) | our campaign state (append-only lineage tree, budget ledger, provenance) | ADR's state is **flat and ephemeral-by-default**; no lineage tree, no backtracking model, no budget ledger (only opt-in JSON checkpoint of a subset) |
| `ChildHandle` / `add_child` / `SPAWN_OPERATOR` (parent-child operator hierarchy) | (no direct equivalent — closest is our task-agent tree per Compute Pattern) | ADR's hierarchy is **operator-of-operators**, a different axis than our tool/task-agent composition |
| `@act` method (returns `asyncio.Future` from `engine.function_task`/`engine.block`, or a plain value for local exec) | our Task Agent four-phase execution (pre-process→parameterize→execute→post-process) | ADR's `@act` is a **single opaque dispatch point**; it has no notion of pre/post-process phases or QC gates — that logic would have to live inside your `@act` body |
| `ActionSet.get_schema("openai"/"anthropic"/"langgraph")` | our tool registry + typed DAG composition surface | ADR renders **pre-declared `@act` methods** as LLM tool schemas; it does not compose arbitrary new DAG shapes at runtime the way our five-gate composer does |
| `RecordingObserver` / `replay_trace` | our full-provenance requirement | partial: records `obs`+`decision` per cycle to JSONL; **no prompts, no model ids, no rationale text** captured by default (§7) |
| `Operator(max_cycles=…, max_runtime=…)` | our budget guard | a **single scalar safety valve** (cycle count / wall clock), not a multi-dimensional budget ledger |
| — (nothing) | our five validation gates (type/structure/parameter/resource/budget) + dry-run + self-promoting interlock | **no equivalent** (§6) |
| `Policy(primary=, fallback=, timeout=)` composition | — | closest ADR gets to policy composition; not a "swap the control model" feature, it's a resilience fallback |

---

## 3. The policy interface — quoted in full

`src/radical/adr/policy/base.py`:

```python
class Policy:
    _adl_decide_fn: Callable | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._adl_decide_fn = None
        for name, val in vars(cls).items():
            if callable(val) and getattr(val, "_adl_decide", False):
                cls._adl_decide_fn = val

    def __init__(
        self,
        *,
        primary:  "Policy | None" = None,
        fallback: "Policy | None" = None,
        timeout:  float | None    = None,
    ) -> None:
        self._primary  = primary
        self._fallback = fallback
        self._timeout  = timeout

    async def decide(self, obs: dict) -> Decision:
        # Dispatch to @decide method if the subclass defines one
        fn = type(self)._adl_decide_fn
        if fn is not None:
            result = await fn(self, obs)
            if not isinstance(result, Decision):
                raise TypeError(...)
            return result

        # Composition: try primary, then fallback
        if self._primary is not None:
            try:
                if self._timeout is not None:
                    result = await asyncio.wait_for(self._primary.decide(obs), timeout=self._timeout)
                else:
                    result = await self._primary.decide(obs)
                if result is not None:
                    return result
            except asyncio.TimeoutError:
                log.warning(...)
            except Exception:
                log.exception(...)
        if self._fallback is not None:
            return await self._fallback.decide(obs)
        raise PolicyError(...)
```

`decision.py`:

```python
class Decision(BaseModel):
    actions:      list[Action]          = []
    directives:   dict[str, Any]        = {}
    stop:         bool                  = False
    delegate_to:  list[str]             = []
    notify:       list[tuple[str, Any]] = []
    goals:        list[Goal]            = []
    remove_goals: list[str]             = []
```

**Comparison against our `ControlPolicy`:**

```python
async def decide(obs: CampaignObservation) -> Decision   # ComposeAndRun|Backtrack|RequestHuman|Stop
async def interpret(results, obs) -> Interpretation | None
async def on_rejected(decision, reason) -> Decision
```

- **`decide`** — present in both, same name, same async signature shape (`obs -> Decision`). But:
  - Our `obs` is a typed `CampaignObservation`; ADR's `obs` is a **plain untyped `dict`** assembled
    by hand in `@observe` (`SYSTEM.md` §3.2: "`@observe` is the **single assembly point for all
    metrics**"). No schema, no validation on what goes in.
  - Our `Decision` is a **discriminated union of four intents**
    (`ComposeAndRun|Backtrack|RequestHuman|Stop`) — the policy picks *one kind of move per cycle*.
    ADR's `Decision` is a **flat bag**: an arbitrary list of `Action`s (any mix of spawn/cancel/retry/
    update-param), plus `stop`, plus goal mutations, plus child delegation — all optionally present
    at once, every cycle. There is no `Backtrack` primitive (nearest analog: `cancel_task` +
    `retry_task`, which re-spawns the *same* task, not a lineage rewind) and no `RequestHuman`
    primitive at all — ADR has no representation for "pause and wait for a person."
- **`interpret`** — **does not exist in ADR.** There is no separate results-interpretation step; a
  policy sees raw `obs` (already assembled by `@observe`) and must fold interpretation into `decide`
  itself. ADR's cycle has no slot between OBSERVE and DECIDE for this.
- **`on_rejected`** — **does not exist in ADR.** There is no validation-gate concept upstream of
  action application that could reject a decision and hand it back to the policy (see §6). The
  closest mechanic, `_validate_actions` (operator.py:886), *raises `ActionError` for the whole
  batch* — it does not return control to the policy for reconsideration.

**Verdict on shape:** ADR's policy interface is a **subset in vocabulary, differently factored in
structure**. It covers the "decide" surface area but has no `interpret` or `on_rejected` hooks, and
its `Decision` is a flat multi-action bag rather than a mutually-exclusive four-way discriminated
union. Adopting `ControlPolicy` as ADR's `Policy` verbatim is not possible without extending ADR;
adopting ADR's `Policy`/`Decision` as ours would mean giving up the union's exhaustiveness guarantee
and inventing `Backtrack`/`RequestHuman`/`on_rejected` on top.

---

## 4. Swappability

Policy assignment is a **plain mutable attribute**:

```python
# operator.py
@property
def policy(self) -> "Policy | None":
    return object.__getattribute__(self, "_policy")

@policy.setter
def policy(self, value: "Policy | None") -> None:
    object.__setattr__(self, "_policy", value)
```

and `op.policy = Policy(primary=MockLLMPolicy(), fallback=ProteinDesignPolicy(op))` (from
`examples/04-protein-design.py`) is exactly how it's used. There is:

- **No registry.** No entry points, no config-driven policy lookup by name. You import a class and
  instantiate it.
- **No swap-guard.** Nothing prevents `op.policy = OtherPolicy()` mid-run, between cycles. ADR does
  not assume "fixed at launch" — it assumes the opposite: the docs even market this as a feature
  (`ADR.md`, "Swappable Policy Without Touching the Workflow": *"Switching requires one assignment.
  The operator, its acts, its observations, and its goals are untouched."*).
- **`Policy(primary=, fallback=, timeout=)`** is the one built-in composition mechanism, but it is a
  **resilience fallback** (primary raises/hangs/returns `None` → fallback), not a governed "swap the
  control model" mechanism, and it is evaluated fresh every `decide()` call, not once at launch.

**Against our decision** that the control model is fixed at launch: ADR does not enforce this, and
does not even model it as a decision to make — "swap anytime" is closer to ADR's actual design center
than "fixed at launch." If we adopt ADR's `Policy`, we would need to add our own guard (e.g., freeze
`operator.policy` after `run()` starts, or never expose the setter to Part B code) — ADR gives us
nothing here for free.

---

## 5. Coverage of the four control models

| Model | Native mechanism in ADR? | Evidence |
|---|---|---|
| **A** — explicit multi-node agentic loop (hypothesize→parameterize→run→analyze) | **Awkward fit.** No node/graph abstraction inside ADR itself. `ADR.md` explicitly hands this off to LangGraph: *"A LangGraph graph is a valid ADR policy... These two concerns are orthogonal."* (`ADR.md`, "ADR and LangGraph Compose"). `examples/09-langgraph-policy.py` confirms the pattern is: LangGraph owns the multi-node reasoning graph, and its *entire output* is wrapped into one flat `Decision` returned from a single `@decide`. ADR itself has no internal notion of "phase" or "node" — you'd reimplement the 4-node state machine yourself inside one `Policy.decide` (or delegate to LangGraph and treat ADR as a downstream executor). |
| **B** — external heavyweight LLM oracle | **First-class, best-fit model.** `LLMPolicy` (`policy/llm.py`) is a purpose-built base class: `render_observation(obs)` (JSON-dumps obs for the prompt), `record_usage(tokens=, latency=, cost=)`, and `ActionSet.get_schema("openai"/"anthropic")` renders every declared `@act` as a vendor tool schema so an LLM's tool-call response maps directly to a `Decision`. `examples/04-protein-design.py`'s `MockLLMPolicy(LLMPolicy)` and `examples/03-asyncflow-llm-adaptive-search.py` are worked examples. ADR's own pitch (`ADR.md`, "LLM as a Scientific Steering Policy") is literally this model. |
| **C** — external caller steering (headless control mode 2) | **Present in design, non-functional in code at 0.1.0.** `ADLMCPServer` (`src/radical/adr/mcp/server.py`) is meant to expose an operator over MCP; tool calls are queued as `InboxMessage(kind=MessageKind.CUSTOM, ...)`. Two breakages: (1) it imports `from radical.adr.tools.registry import ToolRegistry` and `from radical.adr.tools.asyncflow_tools import ASYNCFLOW_TOOLS` — both files are **empty deprecated stubs**: `src/radical/adr/tools/registry.py` and `.../asyncflow_tools.py` contain only `"""Deprecated — use radical.adr.tools.ActionSet instead."""` and no symbols. The import `ASYNCFLOW_TOOLS` does not exist — `ADLMCPServer.__init__` will raise `ImportError`/`AttributeError` on construction. (2) Even if that were fixed, `Operator._apply_message` (operator.py:820–870) branches on `STOP`, `TASK_EVENT`, `DIRECTIVE`, `SNAPSHOT` — there is **no `elif msg.kind == MessageKind.CUSTOM` branch at all**. A CUSTOM message is drained from the inbox and silently dropped; it never reaches `state`. There are zero tests referencing `mcp` anywhere under `tests/` (`grep -ril mcp tests/` → no results), consistent with this path being dead/aspirational. |
| **D** — deterministic / statistical user-supplied policy | **First-class, primary worked example throughout.** Every non-LLM example (`01-asyncflow-adaptive-search.py`, `04-protein-design.py`'s `ProteinDesignPolicy`, `10-resource-aware-search.py`) is a plain `Policy` subclass with a hand-written `@decide` doing arithmetic/rules against `obs`. `ADR.md`: *"A deterministic rule policy — fast, reproducible, auditable"* is listed first among swappable policies. Bandit/Bayesian-opt/evolutionary/replay policies are all expressible the same way (nothing ADR-specific needed) — `RecordingObserver`/`replay_trace` (`recording.py`) is explicitly built for offline replay-policy A/B comparison. |

**Summary:** ADR is strongest exactly where our hypothesis expected it to be weakest-to-moderate (B
and D), and weak/broken exactly where the hypothesis implicitly needed it strongest for the
"external caller steering IS headless control mode 2" claim (C). A is out of scope by ADR's own
design — it explicitly delegates multi-node reasoning to LangGraph.

---

## 6. The loop — ownership conflict

ADR's `Operator.run()` (operator.py:594–690) **is a complete, self-contained outer loop**:

```python
async def run(self) -> AsyncIterator[Snapshot]:
    ...
    while not self._stop_event.is_set():
        await self._drain_inbox()                           # 1. RUN
        snapshot   = self.state.snapshot()
        obs = observe_fn(self, snapshot)                     # 2. OBSERVE
        decision = await self._decide(obs)                   # 3. DECIDE
        self._check_goals(obs, snapshot, decision)
        self._apply_goal_changes(decision)
        await self._apply_actions(decision.actions)          # 4. ACT
        await self._dispatch(decision)
        if decision.stop:
            self._stop_event.set()
        yield snapshot
        self.state.clear_cycle()
        self.state.cycle += 1
        ...
```

`SYSTEM.md`'s own cycle table (§2):

| Step | What happens |
|------|-------------|
| RUN | Drain inbox, promote PENDING→RUNNING |
| OBSERVE | `@observe(snapshot)` → dict |
| DECIDE | `policy.decide(obs)` → Decision; force stop if goals satisfied |
| ACT | Apply each Action; dispatch directives/snapshots |

**This is a structural conflict with Part B's loop.** Our loop is
`observe → decide → compose → validate → execute → analyze → update → terminate?` — eight named
phases, four of which (compose, validate, execute, analyze) sit *between* ADR's DECIDE and the next
OBSERVE, and none of which ADR names or owns separately. ADR's ACT phase directly executes whatever
the policy asked for (`_apply_actions` → `_apply_one` → the `@act` function is called, and if it
returns a `Future` it's dispatched to AsyncFlow) — there is no validation gate, no dry-run, no
interlock between DECIDE and ACT (§ below). If we let ADR's `Operator.run()` be the loop, our
compose/validate/execute/analyze machinery has to be squeezed *inside* the ACT phase (i.e., live
inside `@act` method bodies or be smuggled in as extra logic wrapping `_apply_actions`), which:

- breaks the "validate before any action in the batch is applied, atomically, with structured
  rejection" model we want (ADR's `_validate_actions` does batch-validate, but only for
  action-shape/param-name correctness — see §6 below — and on failure it *raises*, terminating the
  operator's `run()` entirely via an uncaught `ActionError` from `_apply_actions`, not routing back
  to `policy.on_rejected`),
- gives ADR, not us, ownership of cycle counting, inbox draining, and the stop condition,
- and means every one of our five validation gates + dry-run + self-promoting interlock would need
  to be re-implemented as ad hoc code stuffed into `@act`/`@observe`/`@decide` bodies, fighting
  ADR's structure rather than using it.

**Recommendation:** one of the two loops has to give. Given that Part B's loop is the one carrying
our actual governance requirements (five gates, dry-run, interlock, typed `Decision` union,
`on_rejected`), **our loop should own the outer cycle**, and ADR should be used, if at all, only as a
**library of pieces** (its `Goal`/`AllGoal`/`AnyGoal` predicates, its `LLMPolicy` prompt-rendering
helpers, its `RecordingObserver`/`replay_trace` pattern) invoked *from inside* our own
observe/decide/compose/validate/execute/analyze/update/terminate loop — not by calling
`Operator.run()` and ceding the cycle to it.

---

## 7. Governance and safety constraints

Part B needs: five validation gates (type, structure, parameter, resource, budget), a dry-run,
frozen parameters, and a self-promoting interlock (novel patterns run capped + auto-`suspect`,
promote after N clean runs). What ADR actually has:

**`_validate_actions`** (operator.py:886–989) — pre-flight, batch, all-problems-listed:

```python
def _validate_actions(self, actions: list[Action]) -> None:
    """Pre-flight check of every action in a Decision.
    Raises a single ActionError listing all problems found ...
    Unresolvable depends_on uids warn (not raise) ..."""
    registry = type(self)._adl_act_registry
    problems: list[str] = []
    for i, act in enumerate(actions):
        if act.kind in (ActionKind.SPAWN_TASK, ActionKind.SPAWN_BLOCK):
            ...
            fn = registry.get(act.task_name)
            if fn is None:
                problems.append(f"action[{i}]: unknown task '{act.task_name}'; ...")
                continue
            self._validate_spawn_params(i, act, fn, problems)
        ...
    if problems:
        raise ActionError(...)
```

This is a **structural + parameter-name/arity gate only** — is the task name registered, are the
kwargs the right names, are required params present, do `depends_on` uids resolve. It is *not*:
resource-aware (no GPU/CPU/node checks), not budget-aware (no compute-hours/dollar check gating a
spawn), has no dry-run mode (there is no "simulate this action set without executing it" path
anywhere in `operator.py`), and has no concept of frozen parameters. On failure it **raises
`ActionError`**, which propagates out of `_apply_actions` uncaught by the loop — there is no
`on_rejected`-style path back to the policy; a bad `Decision` kills the run.

**Budget**: the closest primitives are `Operator(max_cycles=..., max_runtime=...)` (two scalar caps,
operator.py:317–319, checked at end of each cycle) and resource `Goal`s (e.g. `Goal("cpu_healthy",
"cpu_percent", 90.0, direction="minimize")`, purely advisory — a goal only forces `stop=True` when
*all* goals including it are satisfied; it does not gate or block a specific spawn). There is no
multi-dimensional budget ledger (GPU-hours, dollars, wall-clock, API calls tracked and enforced
per-action) anywhere in the codebase.

**Self-promoting interlock (novel-pattern-capped, promote after N clean runs):** **no equivalent at
all.** Nothing in `operator.py`, `decision.py`, or `goals.py` tracks "is this action pattern novel,"
caps its concurrency, marks it `suspect`, or promotes it after clean runs. This would be entirely
new code on our side.

**Verdict:** ADR's `_validate_actions` is a genuine but shallow analog to our "structure + parameter"
gates only (2 of 5). Type validation exists implicitly via Pydantic on `Action`/`Decision` fields
(structural, not domain-typed). Resource gate, budget gate, dry-run, and the interlock are entirely
absent — we would build all four ourselves regardless of what we adopt from ADR.

---

## 8. State and provenance

`RuntimeState`/`Snapshot` (`state.py`) hold `observations` (cleared per cycle), `runtime` (task
statuses, persist), `objectives` (persist), `artifacts` (persist), `directives` (cleared per cycle),
`task_context` (uid → `{name, kwargs}`, persist). `Snapshot` is a frozen Pydantic model — "safe to
log, serialize, or pass across coroutines" (`state.py:16-21`).

**Checkpointing** (`operator.py:733-790`, `save_checkpoint`/`load_checkpoint`) is real and tested
(`tests/unit/test_checkpoint.py`), but explicitly partial: it dumps `cycle`, `objectives`, `runtime`
(with in-flight tasks rewritten to `"LOST"`), `artifacts`, `task_context`, runtime goals, and
child-lifecycle metadata to JSON. It does **not** persist live task Futures ("the sacred boundary")
and does **not** persist child operator *instances* — only their lifecycle bookkeeping; you must
re-declare children with `add_child` yourself on resume.

**Audit trail**: `RecordingObserver`/`replay_trace` (`recording.py`) writes one JSON line per cycle:
`{"cycle": int, "obs": <the raw obs dict>, "decision": decision.model_dump()}`. This *is* a genuine,
working per-cycle audit log (`tests/integration/test_recording_roundtrip.py` exercises it), and
`replay_trace` re-drives a different policy against the recorded `obs` sequence offline for A/B
comparison — a useful pattern.

**Gap against our reproducibility requirement**: nothing in this trail captures **pinned model ids,
prompts, or rationale text**. `LLMPolicy.record_usage(tokens=, latency=, cost=)` is explicitly
documented as *not* flowing into this pipeline: "Usage tracking is purely local bookkeeping...It
never flows through `state`, `snapshot`, or `@observe`" (`policy/llm.py:38-40`), stored only in an
in-memory `deque(maxlen=256)` on the policy instance that a checkpoint does not capture and that
vanishes with the process. There is no field anywhere for "which model/version answered this
decision" or "what was the exact prompt." **If we want full provenance (pinned model ids, prompts,
rationale) we have to add it ourselves** — either by extending `@observe`/`Decision` to carry it (so
it flows through `RecordingObserver` naturally) or by building a parallel provenance store.

---

## 9. Relationship to asyncflow and flowgentic

`pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2",
    "radical.asyncflow",
]
```

ADR **depends directly on `radical.asyncflow`** and nowhere else — confirmed by `grep -ril
flowgentic .` across the entire refcode (source, docs, examples, tests) returning **zero matches**.
`radex` and `orbit` are likewise absent. ADR does not execute anything itself: `@act` methods call
`self.engine.function_task(fn)(...)` or `self.engine.block(fn)(...)` directly — every unit of actual
work is dispatched through AsyncFlow's `WorkflowEngine`; ADR only ever holds and cancels the
resulting `asyncio.Future`. This matches `SYSTEM.md`'s "sacred boundary" claim exactly and is
consistent across every example and the operator source.

Important immaturity caveat (`ADR.md`, gap **G1**, and repeated in `docs/integrations/asyncflow.mdx`):

> "Block cancellation, `future.state`, `workflow_id` kwarg, and `patched_cancel` live on the
> `feature/enable_block_cancellation` branch of AsyncFlow. The AsyncFlow main branch does not include
> these... A team cannot install from main and get full ADR behavior."

So ADR's dependency on asyncflow is not just "any asyncflow" — operator-as-block, task cancellation,
and RUNNING-state detection require an **unmerged feature branch**. This is directly relevant to our
M2/M4 open questions (`DragonExecutionBackend` config, cancellation adequacy for backtracking/stop):
if we build on ADR's `Operator`, our cancellation semantics inherit this unmerged-branch dependency.

`radical.adr[mcp]` optional extra pulls in `mcp>=1.0` for `ADLMCPServer` — currently non-functional
per §5.

---

## 10. Worked example, walked through

`examples/04-protein-design.py` — closest to our domain (protein design, docking + MD refine):

- `ProteinDesignOperator(Operator)` declares state (`best_score`, `batch_size`,
  `candidates_tried`), one `@goals` (`good_score`: `best_score < -8.0`), two `@act`s (`dock`,
  `md_refine`, both dispatched via `self.engine.function_task(...)` — real AsyncFlow calls, mocked
  scoring function), and one `@observe` that folds dock/refine results into `best_score`.
- `ProteinDesignPolicy(Policy)` — a plain rule policy: refine the top-2 "high performers" from last
  cycle, dock `batch_size` new candidates from a fixed pool each cycle. Pure Python arithmetic, no
  ML/LLM.
- `MockLLMPolicy(LLMPolicy)` — stub `@decide` that `raise NotImplementedError`, meant to be replaced
  with a real vendor call.
- `main()` wires: `op.policy = Policy(primary=MockLLMPolicy(), fallback=ProteinDesignPolicy(op))` —
  so every cycle tries the (broken, intentionally so) LLM path, catches the exception via `Policy`'s
  composition try/except, and falls back to the rule policy. Runs `async for snapshot in op.run():
  ...` for 10 cycles, prints `best_score` each cycle.

This end-to-end example demonstrates every core mechanic working together (state proxying via
annotated attrs, `@act`→AsyncFlow dispatch, `@observe` result-folding, `@goals` convergence, `Policy`
fallback composition) on a domain adjacent to ours, but it is intentionally shallow: mocked docking,
no real QC gates, no resource awareness, no budget, no multi-node reasoning — it exercises D (rule
policy) with a token gesture at B (LLM, stubbed out).

---

## 11. Maturity — implemented vs. aspirational

Real, working, and reasonably well-tested (120 test functions across `tests/unit`, `tests/integration`,
`tests/smoke`, per `CHANGELOG.md`: *"Full suite: 120 passing"* — confirmed by
`grep -rc "^def test_\|async def test_" tests` → 120):

- Core ODA loop (`Operator.run`), `@act`/`@observe`/`@goals`/`@decide` decorators, `Decision`/`Action`
  dispatch for `SPAWN_TASK`/`CANCEL_TASK`/`RETRY_TASK`/`UPDATE_PARAM`
- Goal evaluation incl. `AllGoal`/`AnyGoal` combinators and `for_cycles` debounce
- Parent-child operator hierarchy (`add_child`, `SPAWN_OPERATOR`, `ChildHandle`,
  `RESTART_OPERATOR`/`CANCEL_OPERATOR`) — newest feature, per git log the most recent commit before
  docs-only commits
- Checkpoint/resume (partial, by design — excludes live futures/child instances)
- `RecordingObserver`/`replay_trace` — genuinely useful, tested (`test_recording_roundtrip.py`)
- `Policy(primary=, fallback=, timeout=)` composition, incl. timeout-triggered fallback

**Documented-but-broken or aspirational**, found by code inspection, not assumption:

- `ADLMCPServer` (external caller steering / our control model C) — imports symbols
  (`ToolRegistry`, `ASYNCFLOW_TOOLS`) from files that are empty deprecated stubs
  (`tools/registry.py`, `tools/asyncflow_tools.py` both contain only a deprecation docstring). Even
  setting that aside, `Operator._apply_message` has no `CUSTOM`-message branch, so MCP-originated
  mutations would be silently dropped. Zero test coverage. This directly undercuts the docs'
  `docs/integrations/mcp-server.mdx` walkthrough, which presents it as working.
- `ADR.md`'s own "Limitations and Known Gaps" section is unusually candid and should be taken as
  ground truth over the marketing framing earlier in the same file — it lists (as of this snapshot)
  unresolved: **G2** no peer-to-peer operator messaging (must relay through a parent), **G6** `start()`
  hierarchy not validated at scale (3+ levels, 50+ fan-out), **G7** `depends_on` not fully reflected in
  LLM schema at older doc revision (though `CHANGELOG.md` "Unreleased" claims this specific one is now
  fixed — the two documents are not perfectly in sync, itself a maturity signal), **G8** goals are
  binary with no progress/rate signal, **G9** no conditional action sequences (a decision's actions
  all fire unconditionally; branching on a same-cycle result needs a full extra cycle).
- No release tags exist (`git tag` → empty); all work sits under version `0.1.0` in `pyproject.toml`
  across ~18 commits, most recent labeled "update docs" — this is pre-release, single-repo, would
  read as "still moving" rather than "stabilized API."

**Governance/safety machinery Part B needs and ADR does not have at all** (not a documentation gap —
simply absent from the code): resource validation gate, budget validation gate, dry-run, frozen
parameters, self-promoting interlock. See §6.

---

## Verdict

The user's hypothesis — "autonomous encapsulation with swappable policies via radical.adr" mapping
onto Part B's `ControlPolicy` abstraction — is **half right**. ADR *does* provide a real, working,
swappable-policy abstraction (`Policy`/`@decide`/`Decision`), and it is the strongest evidence
we have anywhere in this refcode set for how a "policy" layer over an HPC steering loop should look.
But it diverges from our design in four load-bearing ways:

1. **Policy shape mismatch.** ADR's `Decision` is a flat multi-action bag with no `Backtrack`/
   `RequestHuman` primitives and no `interpret`/`on_rejected` hooks (§3).
2. **Loop ownership conflict.** ADR's `Operator.run()` wants to own the entire cycle, including
   what we call compose/validate/execute/analyze; adopting it as-is means either subordinating our
   governance machinery into `@act` bodies, or not using `Operator.run()` at all (§5).
3. **No governance layer.** None of our five validation gates (beyond thin structural/param
   checking), no dry-run, no budget guard beyond two scalar caps, no self-promoting interlock (§6).
4. **Swappability is unguarded and assumes runtime switching**, the opposite of our "fixed at
   launch" decision (§4).
5. **The one control model our hypothesis leaned on for "external caller steering" (C) is
   non-functional in the actual code** — the MCP path imports from empty deprecated stub modules
   and the operator's message dispatcher has no branch for the message kind MCP would send (§5).

**Recommendation: mine ADR for patterns; do not adopt its runtime wholesale.**

Specifically:
- **Adopt/borrow the vocabulary and interface shape** of `Policy.decide(obs) -> Decision` as a
  starting point for `ControlPolicy` — it validates that "one method, dict-in, structured-decision-
  out" is a workable contract for LLM, rule, and hybrid policies alike (confirmed across three real
  policy types in `examples/04-protein-design.py` and `examples/09-langgraph-policy.py`).
- **Adopt the `Goal`/`AllGoal`/`AnyGoal` pattern** (name, metric, threshold, direction, `for_cycles`
  debounce, AND/OR composability) as a candidate primitive for expressing *stopping conditions*
  specifically — it is well-designed and well-tested — but do not conflate it with our Pareto-front
  multi-objective model; it solves a narrower problem (binary convergence checks).
- **Adopt the `RecordingObserver`/`replay_trace` pattern** for offline policy replay/A/B testing —
  cheap to reimplement and directly useful, but must be extended to capture prompts/model
  ids/rationale to satisfy our provenance requirement; ADR's version explicitly does not.
- **Do not adopt `Operator.run()` as our outer loop** — build our own
  observe→decide→compose→validate→execute→analyze→update→terminate loop, and if ADR-derived pieces
  are used, invoke them as library calls from inside our loop, not the reverse.
- **Do not depend on `ADLMCPServer`** for headless control mode 2 / control model C in its current
  state — it needs a real `ToolRegistry` implementation and a `CUSTOM`-message branch in whatever
  message dispatcher we build; treat this as "build our own thin adapters" (which Part B already
  specifies: in-process, HTTP+SSE, MCP).
- **Build our own governance layer from scratch** — five validation gates, dry-run, budget ledger,
  self-promoting interlock all have to be designed and implemented by us; ADR gives essentially
  nothing reusable here beyond the idea of a pre-flight batch validator.

**What we would give up if we adopted ADR's `Operator`/`Policy` more fully:** the `Decision` union's
exhaustiveness (Python's type checker can't help us the way a `Backtrack|RequestHuman|Stop|
ComposeAndRun` union does against ADR's flat `Decision`), a distinct `interpret` step (we'd have to
fold interpretation into `decide`, weakening separation of concerns), the "fixed at launch" guarantee
(we'd have to add our own lock around `Operator.policy`), and — most importantly — ownership of the
outer loop, without which our validation gates and interlock have no natural home.

## Risks

- **Unmerged AsyncFlow feature branch dependency** (`feature/enable_block_cancellation`) — if we
  build anything on ADR's `Operator` hierarchy/cancellation features, we inherit this instability
  (§9), directly touching M2/M4.
- **0.1.0, no tags, actively churning** (breaking changes noted in `CHANGELOG.md`'s own "Breaking"
  section for this same unreleased version) — treating any part of ADR as a stable dependency now is
  risky.
- **Docs ahead of code** in at least one place we could verify precisely (MCP server) — a caution to
  independently verify any other ADR claim before relying on it, rather than trusting `ADR.md`/
  `SYSTEM.md` at face value.
