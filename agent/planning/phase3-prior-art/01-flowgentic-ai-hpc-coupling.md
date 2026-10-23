# Prior-art review: `flowgentic` — `examples/ai-hpc-coupling/`

**Repo:** `<workspace>/impress-a-refcodes/middleware/flowgentic`
**Ref:** `origin/demo/radical` (read via `git show`/`git ls-tree`; never checked out)
**Path:** `examples/ai-hpc-coupling/`

## 1. What the demo is

A single synthetic scientific loop — "surrogate-guided search stands in for active
learning, screening, or iterative reconstruction: propose candidates, run expensive
simulations, assimilate the evidence, decide whether to continue" — implemented
**four times** at increasing levels of agent involvement, all sharing one science
core (`campaign_common.py`): a resident `SurrogateService` (propose/assimilate),
a synthetic `evaluate_candidate` simulation with one injected transient failure,
fixed `CampaignSettings` (batch_size=4, budget=24, uncertainty_threshold=0.25,
max_cycles=8), and one `write_summary` reporting format. Two named local
backends stand in for RHAPSODY: `ai` and `compute` (`LocalExecutionBackend` over
a `ThreadPoolExecutor`), explicitly "laptop-safe" stand-ins — "Replacing them
with RHAPSODY backends changes resource setup, not the scientific loop or agent
graph."

Every one of the four variants can optionally be wrapped by `adr_control.py`
(`--controller adr` vs. the default `--controller application`), which is the
same file reused unmodified across all four — this is presented explicitly as
the reason ADR is worth having: "ADR wraps either a compiled agent graph or the
direct AsyncFlow RADICAL baseline" without changing either implementation.

## 2. The variant ladder — corrected reading

**The premise in the task brief needs correcting.** This is *not* a ladder of
escalating autonomy over identical control logic (as IMPRESS-A's A/B/C/D fixed
control policies are). It is **two independent axes**:

- **Axis 1 — who owns the outer loop / programming model:** direct AsyncFlow
  Python (`radical_*`) vs. LangGraph-compiled graph via Flowgentic (`application.py`
  / `flowgentic_campaign.py`, `agentic_*`) vs. AsyncFlow-owned loop with LangGraph
  confined to three bound decision points (`augmented_*`).
- **Axis 2 — whether agents reason at all:** `radical_*` and `application.py`
  (the "retained deterministic LangGraph" demo) have **no LLM reasoning** —
  candidate selection is copied straight from the surrogate. `agentic_*` and
  `augmented_*` add three genuinely nondeterministic (or scripted-rehearsal)
  agent decisions: planner (candidate batch), analyst (evidence interpretation),
  supervisor (next strategy / continue-stop recommendation).

The README states the recommended comparison is **RADICAL baseline vs.
agent-augmented RADICAL** (path 1 and path 4), with the pure-LangGraph-owned
agentic version (path 3) kept only "to show the alternative in which LangGraph
owns the complete cycle," and the deterministic LangGraph version (path 2) kept
only for internal regression testing, not presentation. So the demo's own authors
consider **augmented > agentic** as the better pattern — i.e., they converged on
**AsyncFlow-owned loop + bounded agent insertion points**, not framework-owned
loop, as the recommended shape. That is a strong, explicit data point in favor
of IMPRESS-A's approach (application/loop owns the cycle; the LLM never owns the
loop).

### Comparison table

| Rung | File(s) | Who owns the outer loop | What varies at each decision point | Agent reasoning? | Hard stop authority |
|---|---|---|---|---|---|
| **RADICAL baseline** | `radical_application.py`, `radical_campaign.py` | Ordinary Python `while` loop over `run_cycle` (AsyncFlow tasks only) | Nothing — surrogate proposal used directly, no decision layer | None | Application `while` loop (or ADR, unchanged) |
| **Retained deterministic LangGraph** | `application.py`, `flowgentic_campaign.py`, `campaign_types.py` | LangGraph `StateGraph.compile()`, driven by an outer Python `while state["cycle"] < max_cycles: ... graph.ainvoke(state)` | Nothing — same as baseline, just re-expressed as 3 graph nodes (plan/simulate/analyze) mapped to AsyncFlow via Flowgentic `@flowgentic(flow_type=...)` | None (deterministic) | Same outer `while` loop (or ADR) |
| **Agentic** | `agentic_application.py`, `agentic_support.py`, `agentic_campaign.py` | LangGraph graph (`planner_agent → simulation_executor → analyst_agent → supervisor_agent → END`) compiled and `ainvoke`'d each cycle by an outer Python `while` loop | Planner selects candidate batch; analyst interprets evidence; supervisor picks next strategy + continue/stop — all inside the graph, LangGraph "owns" the cycle's internal structure | Yes — genuine or scripted `AgentDecisionModel` | Outer `while` loop applies the **same** hard uncertainty/budget check regardless of what the supervisor recommended (or ADR) |
| **Agent-augmented RADICAL** | `augmented_application.py`, `augmented_agents.py`, `augmented_campaign.py` | Ordinary Python `run_cycle` function (AsyncFlow tasks) — **no LangGraph graph in the application at all** | Same three decisions (planner/analyst/supervisor), but each is a private single-node LangGraph graph invoked through `flowgentic.agent.bind_agent()` as an opaque `AgentTask.ainvoke()` — LangGraph never sees the scientific loop | Yes | `run_cycle`'s caller (outer `while`, or ADR) — identical hard-policy functions (`enforce_candidate_policy`, `enforce_supervisor_policy`) as the agentic version |

### Mapping to IMPRESS-A's A/B/C/D

None of the four rungs is a clean match to A/B/C/D, because **IMPRESS-A's models
differ in what `decide` computes** for a fixed loop, while this demo's rungs
differ in **loop ownership and framework boundary placement**, which is a
different axis entirely (closer to Phase 2's "loop ownership" question than to
control-model choice). The closest correspondences:

- **Augmented rung ≈ IMPRESS-A model D in spirit** (explicit, application-owned
  policy that calls out to a user-pluggable decision component) but the
  "decision component" here is three bound LangGraph nodes, not one
  `ControlPolicy.decide`. There is no single `Decision` union return value here
  — decisions are three separate typed Pydantic objects consumed at three fixed
  points in one fixed cycle shape. IMPRESS-A's model D lets an externally
  supplied policy choose among `ComposeAndRun | Backtrack | RequestHuman | Stop`
  at one point per full loop iteration; this demo never backtracks and never
  requests human input — there is no analog to those two decision variants at all.
- **Agentic rung ≈ nothing in A/B/C/D**, and this is worth stating plainly: no
  rung here hands full loop ownership to an LLM-driven agentic loop the way
  IMPRESS-A's model A (explicit four-node agentic loop) implies an LLM *choosing*
  what runs next each iteration. Even the "agentic" rung's supervisor only
  recommends a `Strategy` (explore/balanced/exploit) and a continue/stop
  advisory that a hard policy can override — it never composes an arbitrary DAG,
  never picks *which tool* to run next, and never backtracks. **The demo has no
  analog to IMPRESS-A's runtime DAG composition, its five validation gates, or
  its append-only design-lineage tree at all.** This is a single continuous
  numeric-search loop over one candidate representation, not a typed multi-tool
  composition problem.
- **B (heavyweight LLM oracle) and C (external caller steering) have no
  correspondence here either.** There's no static-prompt-based accept/reject
  oracle, and no external supervisory process steering the loop from outside.

**Bottom line correction to the task's framing:** this is not "IMPRESS-A's four
control models over one campaign." It is a demonstration of **loop-ownership
options and where to put the framework seam**, holding one fixed, low-decision-
complexity scientific loop constant. It is still highly relevant — just to a
different one of IMPRESS-A's open questions (loop ownership / ADR wiring) than
the control-policy-variation question the task brief guessed at.

## 3. Typed contracts — `campaign_types.py` and `agent_contracts.py`

### `campaign_types.py` — full quote

```python
class CampaignState(TypedDict):
    """Scientific, conversational, and execution state for one campaign."""

    messages: Annotated[list[BaseMessage], add_messages]
    implementation: str
    cycle: int
    center: float
    radius: float
    uncertainty: float
    best_x: float | None
    best_value: float | None
    budget: int
    spent: int
    candidates: list[float]
    results: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    service: SurrogateService
    decision: str


@dataclass
class CampaignApplication:
    """A compiled campaign graph and its persistent surrogate service."""

    graph: CompiledStateGraph
    state: CampaignState
    service: SurrogateService
    service_future: asyncio.Future[SurrogateService]
```

This is LangGraph-specific (a `TypedDict` graph state, tied to `add_messages`
and `BaseMessage`), and it conflates scientific state with a scratch
`"decision": str` field that is never a structured type — it is set to strings
like `"continue or stop according to campaign goals"` for the non-agentic
variants and to the actual `Recommendation` literal for the agentic ones. This
is much thinner and much less type-safe than `ControlPolicy`'s `Decision`
union: there is no `ComposeAndRun`/`Backtrack`/`RequestHuman`/`Stop` distinction
anywhere in this codebase, and state is not append-only or lineage-tracked —
`CampaignState` is a single flat dict overwritten each cycle via `{**state, ...}`
merges (`radical_application.py`, `augmented_application.py`) or via LangGraph's
node-return-dict merge semantics. There is no Pareto front, no backtracking, no
tree of design lineages — this is a single-point iterative search, not a
branching design-space search.

### `agent_contracts.py` — full quote

```python
Strategy = Literal["explore", "balanced", "exploit"]
Recommendation = Literal["continue", "stop"]


class PlannerDecision(BaseModel):
    """A planner agent's bounded experiment proposal."""

    candidates: list[float] = Field(
        min_length=1,
        description="Candidate coordinates selected for the next simulation batch.",
    )
    rationale: str = Field(description="Scientific reason for selecting this batch.")


class AnalysisDecision(BaseModel):
    """An analyst agent's interpretation of a surrogate update."""

    recommendation: Recommendation
    interpretation: str = Field(
        description="Concise interpretation of the new evidence and uncertainty."
    )


class SupervisorDecision(BaseModel):
    """A supervisor agent's recommendation for the next campaign cycle."""

    recommendation: Recommendation
    next_strategy: Strategy
    rationale: str = Field(
        description="Reason for the recommendation and next search strategy."
    )


class AgentDecisionModel(Protocol):
    """Decision interface shared by live and presentation-rehearsal agents."""

    name: str

    async def plan(self, context: dict[str, Any]) -> PlannerDecision: ...
    async def analyze(self, context: dict[str, Any]) -> AnalysisDecision: ...
    async def supervise(self, context: dict[str, Any]) -> SupervisorDecision: ...
```

Plus the **policy-guard functions**, which are the single most transferable
idea in this file — they are the closest thing here to `ControlPolicy.on_rejected`:

```python
def enforce_candidate_policy(
    decision: PlannerDecision,
    fallback_candidates: list[float],
    *,
    expected_count: int,
    lower_bound: float,
    upper_bound: float,
) -> tuple[list[float], str]:
    """Validate an agent proposal and fall back to the surrogate if necessary."""
    candidates = [round(float(value), 6) for value in decision.candidates]
    if _candidate_batch_is_valid(candidates, expected_count=expected_count,
                                  lower_bound=lower_bound, upper_bound=upper_bound):
        return candidates, "agent proposal accepted"
    fallback = [round(float(value), 6) for value in fallback_candidates][:expected_count]
    if not _candidate_batch_is_valid(fallback, expected_count=expected_count,
                                      lower_bound=lower_bound, upper_bound=upper_bound):
        fallback = evenly_spaced(lower_bound, upper_bound, expected_count)
    return fallback, "agent proposal rejected; surrogate fallback enforced"


def enforce_supervisor_policy(
    decision: SupervisorDecision,
    *, uncertainty: float, uncertainty_threshold: float, spent: int, budget: int,
) -> tuple[Recommendation, str]:
    """Keep stop authority with the hard scientific and resource policy."""
    hard_stop = uncertainty <= uncertainty_threshold or spent >= budget
    if hard_stop:
        status = ("supervisor agrees with hard stop" if decision.recommendation == "stop"
                   else "hard stop overrides supervisor")
        return "stop", status
    if decision.recommendation == "stop":
        return "continue", "premature agent stop rejected by hard policy"
    return "continue", "supervisor recommendation accepted"
```

### Comparison to `ControlPolicy` / `Decision` / `ToolSpec`

- **`AgentDecisionModel` Protocol ≈ `ControlPolicy`'s `decide`**, but split into
  three separately-typed methods (`plan`/`analyze`/`supervise`) rather than one
  `decide` returning a `Decision` union. It has no `interpret` and no
  `on_rejected` method as such — rejection handling is done externally by the
  two `enforce_*` free functions, not as a policy method. That is a meaningfully
  different shape: **rejection/fallback logic lives in shared, framework-neutral
  code the policy cannot see or override**, rather than being a policy
  responsibility. This is arguably a *stronger* separation of authority than
  giving the policy its own `on_rejected` hook — worth considering for
  IMPRESS-A: should validation/fallback ever be delegable to the policy, or
  should it always be enforced from outside regardless of policy?
- **No `ToolSpec` analog whatsoever.** There is exactly one tool shape
  (float-batch proposal) and one fixed pipeline; nothing here addresses
  typed-DAG composition, parameter/resource/budget validation gates, or
  dry-run. `ToolSpec` and the five-gate validator are pure IMPRESS-A invention
  with no precedent in this demo.
- **No `Decision` union (`ComposeAndRun | Backtrack | RequestHuman | Stop`).**
  The closest thing is the `Recommendation = Literal["continue", "stop"]` plus
  a separately reported `Strategy`. There is no `Backtrack` (the search here
  only ever contracts around a moving center, never returns to a prior
  lineage) and no `RequestHuman` at all.
- **Verdict: adopt the guard-function pattern** (`enforce_*` as free functions
  external to the policy, each returning `(value, status_string)` for
  auditability) — this maps directly onto how IMPRESS-A's five validation gates
  should relate to `ControlPolicy.decide`: gates are not something a policy can
  bypass, and the guard's status string is itself useful, auditable evidence
  (they thread it straight into the trace/summary). **Avoid** copying the
  three-separate-typed-method shape (`plan`/`analyze`/`supervise`) as a
  replacement for one `decide` — it works here because the pipeline shape is
  fixed and always exactly three decisions per cycle; IMPRESS-A's loop has one
  decision point per cycle by design and should not fragment it.

## 4. `adr_control.py` and the loop-ownership question — direct empirical data

This is the single most decision-relevant finding in the whole file set, and it
is unambiguous: **`adr_control.py` hands the complete outer loop to
`radical.adr.Operator.run()`.** It does not call ADR pieces piecemeal from an
externally-owned loop. Quoting the structure in full (already close to complete
above in section discovery, key excerpt):

```python
class CampaignOperator(Operator):
    def __init__(self) -> None:
        # ADR cycle 0 dispatches the first action; one final control cycle
        # is required to observe the last completed scientific cycle.
        super().__init__(engine, max_cycles=settings.max_cycles + 1)
        self._campaign_state = application.state

    @goals
    def stop_conditions(self) -> AnyGoal:
        return AnyGoal([
            Goal(name="scientific_convergence", metric="uncertainty",
                 threshold=settings.uncertainty_threshold, direction="minimize", inclusive=True),
            Goal(name="budget_exhausted", metric="spent",
                 threshold=float(settings.budget), direction="maximize", inclusive=True),
        ], name="stop_condition")

    @act
    async def execute_campaign_cycle(self, campaign_state: dict[str, Any]) -> dict[str, Any]:
        return await cycle_executor(campaign_state)

    @observe
    def observe_campaign(self, snapshot: Snapshot) -> dict[str, Any]:
        completed_cycles = [value for key, value in snapshot.observations.items()
                            if key.startswith("result.") and isinstance(value, dict)
                            and "uncertainty" in value]
        if completed_cycles:
            self._campaign_state = completed_cycles[-1]
        return {"campaign_state": self._campaign_state,
                "uncertainty": self._campaign_state["uncertainty"],
                "spent": self._campaign_state["spent"]}

class CampaignPolicy(Policy):
    def __init__(self, operator: CampaignOperator) -> None:
        super().__init__()
        self.actions = operator.get_actions()

    @decide
    async def choose_next_cycle(self, observation: dict[str, Any]) -> Decision:
        state = observation["campaign_state"]
        if (state["uncertainty"] <= settings.uncertainty_threshold
                or state["spent"] >= state["budget"]
                or state["cycle"] >= settings.max_cycles):
            return Decision(stop=True)
        return Decision(actions=[self.actions.execute_campaign_cycle(campaign_state=state)])

operator = CampaignOperator()
operator.policy = CampaignPolicy(operator)

previous_cycle = application.state["cycle"]
async for _snapshot in operator.run():
    if operator._campaign_state["cycle"] != previous_cycle:
        cycle_printer(operator._campaign_state, "ADR")
        previous_cycle = operator._campaign_state["cycle"]
```

Key observations:

- **The whole application cycle (`run_cycle`, or `graph.ainvoke` for the graph
  variants) is wrapped as exactly one ADR `@act` action.** ADR's `Operator.run()`
  drives the observe→decide→act loop itself; the demo's own `while` loop is
  entirely absent under `--controller adr`. This **confirms Phase 2's finding
  precisely**: ADR's `Operator.run()` owns a complete outer loop, and this demo
  resolves the conflict not by keeping its own loop and mining ADR pieces, but
  by **surrendering loop ownership to ADR and shrinking its own cycle down to a
  single opaque action**. That works *only because* one whole scientific cycle
  (propose→simulate→assimilate[→agents]) is coarse-grained enough to be treated
  as one atomic, restartable-from-outside unit with no internal decision points
  ADR needs visibility into.
- **This does not resolve the conflict Phase 2 flagged for IMPRESS-A** — it
  sidesteps it by choosing a problem where the whole inner loop can be one
  black-box action. IMPRESS-A's loop has decision points *inside* each cycle
  (`decide`, `compose`, `validate`, `execute`, `analyze`) that the control model
  itself needs visibility into and must be able to interrupt (`Backtrack`,
  `RequestHuman`). Wrapping IMPRESS-A's entire `observe→...→terminate?` cycle as
  one ADR `@act` action would work for models with no mid-cycle interruption,
  but would make `Backtrack`/`RequestHuman` invisible to ADR's own goal
  evaluation until the next full cycle completes — i.e., **ADR's `Operator.run()`
  cannot observe or arbitrate a decision that happens inside the action it
  dispatches.** This is a strong data point *against* using `Operator.run()` as
  IMPRESS-A's actual loop, and a strong data point *for* Phase 2's
  recommendation to mine ADR's `Policy`/`Decision`/`Goal` primitives while
  keeping IMPRESS-A's own loop as the owner.
- **A structural workaround worth noting:** the operator uses
  `max_cycles=settings.max_cycles + 1` "because ADR cycle 0 dispatches the first
  action; one final control cycle is required to observe the last completed
  scientific cycle" — an off-by-one artifact of ADR's dispatch-then-observe
  ordering that this demo had to explicitly account for. If IMPRESS-A ever does
  lean on `Operator.run()` for anything, budget/cycle-count bookkeeping needs to
  account for this same off-by-one.
- ADR's `Goal`/`AnyGoal` mechanism (`metric`, `threshold`, `direction`,
  `inclusive`) is a clean, declarative way to express multiple simultaneous stop
  conditions (`scientific_convergence` OR `budget_exhausted`) — **adopt this
  pattern for expressing IMPRESS-A's own multi-dimensional budget ledger stop
  conditions**, even without adopting `Operator.run()` itself; it is a good
  vocabulary for "stop if ANY/ALL of these named, thresholded, directional
  metrics are satisfied," independent of who drives the loop.
- Notably, **`CampaignPolicy.choose_next_cycle` re-implements the identical hard
  stop check that the non-ADR `run_with_application_control` also implements**
  (`uncertainty <= threshold or spent >= budget or cycle >= max_cycles`) — the
  demo duplicates its hard-stop logic between the two controllers rather than
  sharing one function. That is worth flagging as an **avoid**: IMPRESS-A should
  keep exactly one stop-policy implementation regardless of which control model
  or loop-owner is in effect.

## 5. asyncflow idioms — concrete patterns, confirming Phase 2

Every non-agentic variant declares tasks the same way, directly against
`radical.asyncflow.WorkflowEngine`:

```python
@flow.function_task(service=True, backend="ai")
async def load_surrogate() -> SurrogateService:
    return await SurrogateService.load()

service_future = load_surrogate()          # NOT awaited immediately
service = await service_future              # awaited only when the value is needed

@flow.function_task(backend="ai")
async def propose_candidates(center: float, radius: float, cycle: int) -> dict[str, Any]:
    return await service.propose(center, radius, settings.batch_size, cycle)

@flow.function_task(backend="compute")
async def simulate(x: float, cycle: int, candidate_index: int, fail_once: bool = False) -> dict[str, Any]:
    return await evaluate_candidate(x, cycle, candidate_index, fail_once)
```

Cycle body (`radical_application.py`):

```python
proposal = await propose_candidates(state["center"], state["radius"], state["cycle"])
...
results = await asyncio.gather(
    *(retry_transient_simulation(lambda x=x, index=index: simulate(x, state["cycle"], index, fail_once=...))
      for index, x in enumerate(candidates))
)
update = await update_surrogate(results, state["radius"], state["cycle"])
```

This **confirms Phase 2's finding precisely, with one clarification**:
dependencies are not "unawaited futures passed as arguments" in the sense of
passing a `Future` object into another decorated call without awaiting it first
— in every example here, each AsyncFlow task call **is itself awaited directly**
(`await propose_candidates(...)`), and concurrency between *independent* tasks
is expressed with ordinary `asyncio.gather` over the coroutine objects returned
by calling the decorated functions, not by passing unresolved futures as
arguments to a *downstream* task decorator. The one case that comes closest to
Phase 2's phrasing is the persistent-service pattern: `service_future =
load_surrogate()` is created and left **unawaited** at that call site, then
awaited later (`service = await service_future`) — and separately,
`application.service_future.cancel()` is called at shutdown without ever being
awaited again. So: **confirmed for the service/singleton-future pattern,
corrected for the general dependency-fan-out pattern** — ordinary
`asyncio.gather` over directly-invoked (and directly-awaited) task calls is the
idiom actually used for fan-out, not deferred/unawaited future chaining across
tasks.

Backend selection is by string name passed to the decorator (`backend="ai"` /
`backend="compute"`), matching named backends constructed once:

```python
async def create_local_backends(compute_workers: int) -> list[LocalExecutionBackend]:
    compute = await LocalExecutionBackend(ThreadPoolExecutor(max_workers=compute_workers), name="compute")
    ai = await LocalExecutionBackend(ThreadPoolExecutor(max_workers=2), name="ai")
    return [compute, ai]
```

Only `LocalExecutionBackend` is exercised anywhere in this example — **no
`DragonExecutionBackend`, `ConcurrentExecutionBackend`, or RHAPSODY backend
appears in this demo at all.** The README is explicit that this is deliberate
("laptop-safe... Replacing them with RHAPSODY backends changes resource setup,
not the scientific loop") but it means **this file set provides zero real
evidence about real backend/resource-shape behavior** — that evidence has to
come from elsewhere in the refcode set (or from rhapsody/asyncflow's own tests),
not from this demo.

Flowgentic-mediated task declaration (the deterministic and agentic LangGraph
variants) uses a decorator-returning-decorator idiom instead of `flow.function_task`
directly:

```python
flowgentic = integration.execution_wrappers.asyncflow
@flowgentic(flow_type=AsyncFlowType.SERVICE_TASK, backend="ai")
async def load_surrogate() -> SurrogateService: ...
@flowgentic(flow_type=AsyncFlowType.FUNCTION_TASK, backend="compute", retry=SIMULATION_RETRY)
async def simulate(...): ...
@flowgentic(flow_type=AsyncFlowType.AGENT_TOOL_AS_FUNCTION, backend="ai", tool_description="...")
async def query_surrogate(...): ...
```

`AsyncFlowType` values observed: `SERVICE_TASK`, `FUNCTION_TASK`,
`AGENT_TOOL_AS_FUNCTION`, `EXECUTION_BLOCK` (the last used to wrap whole
LangGraph *nodes*, not underlying capabilities, so that node execution itself is
placed/instrumented). Retry is expressed as a first-class decorator kwarg here
(`retry=SIMULATION_RETRY`, a `flowgentic.langGraph.fault_tolerance.RetryConfig`)
— **this is Flowgentic providing a retry primitive that Phase 2 said asyncflow
itself lacks.** See §6.

The **agent-adapter seam** (`src/flowgentic/agent.py`, referenced by
`augmented_application.py`) is the cleanest, most directly reusable piece of
code in the whole tree — it shows how to make a framework-neutral component
`ainvoke`-able as an AsyncFlow task without a decorator at the call site at all,
calling `flow.function_task` as a plain higher-order function:

```python
def bind_agent(flow: WorkflowEngine, component: AgentComponent, *,
                identity: str, framework: str, backend: str = "ai") -> AgentTask:
    async def invoke_agent(context: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        response = await component.ainvoke(context)
        finished = time.perf_counter()
        return {"agent": identity, "framework": framework,
                "decision": _structured_payload(response),
                "event": {"name": f"agent.{identity}", "backend": backend,
                           "cycle": int(context.get("cycle", -1)),
                           "started": started, "finished": finished,
                           "duration": finished - started}}
    invoke_agent.__name__ = f"agent_{identity.replace('-', '_')}"
    submit = flow.function_task(invoke_agent, backend=backend)
    return AgentTask(identity, framework, backend, submit)
```

`flow.function_task` accepts a plain function as its first positional argument
(non-decorator call form), returning a submitter callable — worth confirming
against the actual asyncflow signature before relying on it, but it is directly
demonstrated working here.

## 6. Shared scaffolding — what had to be built, and what it reveals

`campaign_common.py`, `demo_support.py`, and `agentic_support.py` had to build,
by hand, exactly the categories Phase 2 predicted would not come for free:

- **Retry:** `retry_transient_simulation` (RADICAL baseline) wraps a call with
  `asyncio.wait_for(..., timeout=5.0)`, catches one specific exception type
  (`TransientSimulationError`), sleeps `0.05s`, and retries **exactly once, hard
  coded** — no backoff schedule, no retry budget, no jitter. This is a minimal,
  bespoke, single-purpose retry, confirming Phase 2's "no retry primitive" for
  the raw AsyncFlow path. The Flowgentic path, by contrast, is more complete:
  `flowgentic.langGraph.fault_tolerance.RetryConfig(max_attempts=2,
  base_backoff_sec=0.05, max_backoff_sec=0.05, jitter=0.0, timeout_sec=5.0,
  retryable_exceptions=(TransientSimulationError,))` passed as a decorator kwarg
  — this **is** a real, typed retry primitive, just owned by Flowgentic, not
  asyncflow. **Adopt the shape of `RetryConfig`** (typed, exception-filtered,
  backoff/jitter/timeout fields) as a model for IMPRESS-A's own retry primitive,
  whether or not IMPRESS-A depends on Flowgentic directly.
- **No durable job ledger of any kind.** State (`CampaignState` /
  `AgenticCampaignState`) is an in-memory dict merged each cycle; nothing is
  checkpointed to disk until `write_summary` runs once at the very end. There is
  no per-cycle checkpoint, no restart-from-cycle-N, and no persisted record of
  in-flight tasks. `_SIMULATION_ATTEMPTS` (a module-level dict keyed by
  `(cycle, candidate_index)`) is the only durable-ish bookkeeping, and it is
  process-local, in-memory, and reset by `reset_demo_state()` between runs —
  this is explicitly presentation-only bookkeeping, not a real ledger. **This
  confirms Phase 2's prediction exactly: no durable job ledger anywhere in this
  stack; IMPRESS-A must build its own.**
- **Resource normalization: not exercised.** Because only `LocalExecutionBackend`
  backends are used, there is no code here that reconciles RADICAL `{"ranks",
  "gpus_per_rank"}` shapes against Dragon `process_template` shapes. Phase 2's
  finding that resource shapes are not portable across backends is **neither
  confirmed nor contradicted** by this demo — it is simply out of scope here.
- **Cycle bookkeeping:** handled ad hoc per variant (`state["cycle"] += 1`
  inline in each `run_cycle`/node), duplicated across `radical_application.py`,
  `application.py`, `agentic_application.py`, and `augmented_application.py`
  nearly verbatim. No shared cycle-boundary abstraction exists; each file
  reimplements its own `while state["cycle"] < settings.max_cycles and
  state["spent"] < state["budget"]: ...` loop with the same three-way stop-reason
  logic (`uncertainty` / `budget` / `max_cycles`) copy-pasted four times (see
  `run_with_application_control`, `run_agentic_with_application_control`,
  `run_augmented_with_application_control` — nearly identical bodies). **Avoid**
  copying this duplication; **adopt** the underlying three-way stop-reason
  vocabulary (goal reached / budget exhausted / max cycles reached) as a good
  minimal taxonomy, but implement it once, shared, parametrized over which
  metric/threshold applies — exactly what IMPRESS-A's multi-dimensional budget
  ledger and terminate-decision path should already be doing.
- **No P5-governor equivalent, and no analog to a network-service pattern
  requiring lifecycle governance.** `SurrogateService` is a "resident" object
  (loaded once, reused, referenced by closure from every task), but it lives
  entirely in the same process as the orchestrating loop — it is never a
  separately-scheduled, network-addressable, or independently-lifecycled
  service. There is no code here analogous to IMPRESS-A's P5 (network service)
  pattern; **this demo provides no evidence at all for P5 governance**, only for
  P6 (in-process, never scheduled) — which is exactly what `SurrogateService` is.
- **QC / gate enforcement:** the only gate-like code in this entire tree is
  `_candidate_batch_is_valid` (bounds + count + finiteness + uniqueness check)
  and the two `enforce_*` guard functions in §3 — narrow, single-purpose,
  hand-written, and specific to one float-batch shape. There is no generalized
  type/structure/parameter/resource/budget gate sequence anywhere here; this
  reinforces that IMPRESS-A's five-gate validator is genuinely new work, not
  something to mine from this codebase.

## 7. LLM integration

Two decision-model implementations share the `AgentDecisionModel` protocol
(`agentic_support.py`):

- **`LangChainDecisionModel`** — live mode. Builds a structured-output call per
  decision: `self.model.with_structured_output(schema)` then
  `structured_model.ainvoke([SystemMessage(<role prompt>), HumanMessage(json.dumps(context, indent=2, sort_keys=True))])`,
  with a `schema.model_validate(response)` fallback if the model's structured
  output doesn't come back as an instance of the schema. **This is a
  meaningfully better pattern than the IMPRESS oracle precedent** (static prompt
  + exact string match): the system prompt is fixed per role (three different,
  role-scoped instructions for planner/analyst/supervisor), but the *content* is
  a full JSON dump of live context, and the *output* is validated against a
  real Pydantic schema via the provider's native structured-output mechanism —
  not parsed by string matching. Failure handling is minimal but present (schema
  re-validation as a fallback) — there is no retry-on-malformed-output loop, no
  temperature backoff, no logging of raw model output on validation failure.
  Provider selection goes through `flowgentic.utils.llm_providers.ChatLLMProvider(provider=..., model=..., temperature=...)`,
  accepting `openrouter`, `chatopenai`, `ollama`.
- **`RehearsalDecisionModel`** — default/offline mode, "reliable" and
  deterministic-by-construction: implements `plan`/`analyze`/`supervise` with
  plain Python logic (e.g. supervisor picks `explore`/`balanced`/`exploit` by
  thresholding `uncertainty` against `1.0`/`0.4`) that produces the *same typed
  Pydantic objects* the live model would, so downstream code (guards, traces,
  reporting) is identical regardless of mode. **Adopt this split** as a
  template: any IMPRESS-A component with an LLM-backed decision point should
  have a scripted/deterministic stand-in implementing the exact same typed
  interface, for CI and demos that must not depend on network access or model
  nondeterminism. This is a clean, generalizable pattern independent of the
  rest of the ladder debate.
- Every LLM (or rehearsal) output, live or scripted, is immediately run through
  the same `enforce_candidate_policy` / `enforce_supervisor_policy` guard
  functions described in §3 — **there is no code path in which an LLM/agent
  decision reaches execution unguarded**, in either mode. This is the single
  strongest structural idea to adopt regardless of anything else in this file
  set: hard policy guards are unconditional, not mode-dependent.

## 8. Deployment detail — `run_*.sh`

All four launcher scripts (`run_demo.sh`, `run_radical_demo.sh`,
`run_augmented_demo.sh`, `run_agentic_demo.sh`) share one shape: resolve
`asyncflow_src`/`adr_src` from environment overrides (`ASYNCFLOW_SRC`,
`ADR_SRC`) or default sibling-repo paths (`${workspace_root}/radical/radical.asyncflow/src`,
`${workspace_root}/radical/radical.adr/src`) assuming a specific on-disk
workspace layout with flowgentic, asyncflow, and adr checked out as siblings;
resolve a `FLOWGENTIC_PYTHON` interpreter (default `${flowgentic_root}/.venv/bin/python`);
take `application`|`adr` as `$1` to select the controller; build a `PYTHONPATH`
by hand (source trees added directly, no installed packages) and `exec` the
corresponding `*_campaign.py`. No SLURM/PBS, no container, no scheduler
directives anywhere in this file set — this is entirely a local, laptop-scale
`ThreadPoolExecutor` demo. **This confirms Phase 2's finding that ORBIT alone
holds real PBS Pro / external-batch support** — nothing here touches a real
scheduler. There is no operational HPC deployment knowledge to extract from
this example; it is a pure development/presentation harness. One detail worth
reusing regardless of scheduler: `PYTHONPATH`-based source-tree linking (rather
than editable installs) as the mechanism for a multi-repo mono-workspace
development setup, since IMPRESS-A will likely also depend on
asyncflow/rhapsody/adr as sibling source checkouts during development.

## 9. Did it run — evidence from `agentic_demo_results/`

Yes — with an important caveat on what "ran" means here. Both output files are
from an actual completed run, in **rehearsal mode** (not a live LLM call):

- `campaign_summary.json`: `implementation="agentic"`, `controller="adr"`,
  `stop_reason="ADR scientific uncertainty goal reached"`, `cycles=5`,
  `simulations=20`, `best_x=2.76961` (target `TARGET=2.75`), `best_value≈0.0034`,
  `uncertainty≈0.2013` (below the `0.25` threshold, as expected), one retry
  recorded (`"retries": 1`, matching the one injected transient failure),
  `max_compute_parallelism=4` (matches `batch_size=4` fanned out concurrently),
  and `agents.model = "rehearsal-agents"` with 15 recorded structured decisions
  (5 cycles × 3 agents), each carrying its `policy_status` string (e.g.
  `"agent proposal accepted"`).
- `execution_summary.md` (Flowgentic's own introspection report): generated
  `2026-08-18 14:27:50`, total duration `2.234s`, `Total Tokens Used: 0` (expected
  under rehearsal — no live model call), 20 LangGraph nodes executed (5 cycles
  × 4 nodes: planner/simulation_executor/analyst/supervisor), per-node timing
  breakdown (e.g. `simulation_executor` totals `0.9663s` across 5 invocations,
  `planner_agent` totals `0.5070s`).

This is solid, concrete evidence the **agentic + ADR** combination runs
end-to-end and produces internally consistent numbers (retry count matches
injected failure, parallelism matches batch size, stop reason matches the
uncertainty threshold actually crossed). It is evidence for "this shape of
ADR-wrapped LangGraph loop executes correctly in rehearsal mode" — it is **not**
evidence about live-LLM behavior (temperature, malformed structured output,
provider latency/failure), since no committed results directory here reflects
`--agent-mode live`. That gap (no committed evidence of a live-LLM run) is worth
noting as something Phase 4 should generate itself before trusting the live path.

## 10. Patterns for Phase 4 — adopt / adapt / avoid

1. **Adopt — unconditional external policy guards.** Every agent/LLM decision,
   live or rehearsed, passes through a hard-coded guard function
   (`enforce_candidate_policy`, `enforce_supervisor_policy`) before touching
   execution or stop logic, and the guard emits a human-readable status string
   alongside the corrected value for the trace. Reason: this is the cleanest
   demonstrated separation between "what an LLM/agent proposed" and "what is
   allowed to happen," and it is independent of which control model or loop
   owner is in effect — map this directly onto how IMPRESS-A's five validation
   gates should relate to any `ControlPolicy.decide` output.

2. **Adopt — scripted/rehearsal stand-in with an identical typed interface.**
   `RehearsalDecisionModel` implements the exact same `AgentDecisionModel`
   protocol as the live LLM model, producing the same Pydantic types through
   deterministic logic. Reason: gives IMPRESS-A a network-free, deterministic
   CI/demo path for any LLM-backed decision point without special-casing
   downstream code.

3. **Adopt — `RetryConfig`-style typed retry primitive** (exception filter,
   attempts, backoff bounds, jitter, timeout) as the shape for IMPRESS-A's own
   retry primitive, since Phase 2 confirmed and this demo reconfirms that
   asyncflow itself has none. Reason: it's a small, complete, already-proven
   shape; no need to invent one from scratch.

4. **Adopt — `bind_agent`/`AgentComponent` adapter seam
   (`src/flowgentic/agent.py`)** as a template for wrapping any framework-
   external decision component (LLM-backed or not) as an opaque, timed,
   backend-placed async call from an application-owned loop, without letting
   that framework own the loop. Reason: this is exactly the "mine the pattern,
   don't depend on the package" recommendation Phase 2 already made for
   Flowgentic, and this is the specific piece worth mining.

5. **Adapt — ADR's `Goal`/`AnyGoal` declarative stop-condition vocabulary**
   (named, thresholded, directional metrics, combined with AND/OR semantics) as
   a model for expressing IMPRESS-A's multi-dimensional budget-ledger stop
   conditions, without adopting `Operator.run()` as the loop. Reason: it is a
   good vocabulary, cleanly separable from ADR's loop-ownership behavior.

6. **Avoid — treating a whole multi-step cycle as one opaque ADR `@act`
   action to make `Operator.run()` fit.** This demo's own adr_control.py had to
   shrink its cycle to a single black-box action to make ADR's loop ownership
   work, which only succeeds because this demo's loop has no decision points
   *inside* a cycle that ADR itself needs to see. IMPRESS-A's `Backtrack`/
   `RequestHuman` decisions occur mid-cycle and must be visible before a cycle
   completes — wrapping the whole cycle as one action would hide them from
   ADR's own goal evaluation until too late. Reason: directly conflicts with
   IMPRESS-A's requirement that control-model decisions interrupt execution
   mid-cycle; Phase 2's "keep our loop, mine ADR pieces" recommendation stands,
   now with a concrete counter-example showing why the alternative doesn't fit.

7. **Avoid — copy-pasted per-variant stop-reason/cycle loops.** Four nearly
   identical `while` loops (`run_with_application_control`,
   `run_agentic_with_application_control`, `run_augmented_with_application_control`,
   plus the ADR duplicate of the same three-way check) exist across this file
   set. Reason: this duplication is exactly the kind of drift risk IMPRESS-A's
   single fixed outer loop is designed to avoid — don't reproduce the pattern
   even though the demo's authors did, under the constraint of needing four
   independently runnable presentation paths.

## 11. What could not be determined

- **No live-LLM run evidence is committed** (`agentic_demo_results/` reflects
  rehearsal mode only) — malformed-structured-output handling, provider
  latency/failure behavior, and live nondeterminism are all undemonstrated here.
- **No RHAPSODY/real-backend behavior is exercised anywhere in this example**
  — only `LocalExecutionBackend` over a `ThreadPoolExecutor` is used. Resource
  normalization across RADICAL/Dragon shapes (Phase 2's concern) is neither
  confirmed nor refuted by this file set.
- **`augmented_demo_results/` and `demo_results/` were not present in the
  branch's file listing** (only `agentic_demo_results/` is committed under
  `examples/ai-hpc-coupling/`), so there is no committed evidence the augmented
  or plain-Flowgentic variants were actually executed and captured, only that
  their code exists and (per the README's own presentation instructions) is
  intended to be run live during a demo.
- Exact `flow.function_task` signature (decorator vs. direct-call overload
  semantics, what `service=True` actually changes) was inferred from call sites
  in this example, not verified against asyncflow's own source in this pass.
- Whether `LangraphIntegration`'s `agent_introspector` / `execution_wrappers`
  API is stable across Flowgentic versions was not checked; this is drawn from
  one snapshot on one branch (`origin/demo/radical`), which may be a working/demo
  branch rather than a released API surface.

## Top 5 concretely reusable things, ranked

1. **The unconditional external-guard pattern** (`enforce_candidate_policy` /
   `enforce_supervisor_policy` in `agent_contracts.py`) — every agent/LLM
   decision is validated and corrected outside the policy itself, with a
   human-readable status string threaded into the trace. Directly informs how
   IMPRESS-A's five validation gates should sit around `ControlPolicy.decide`.
2. **The `adr_control.py` empirical proof that `Operator.run()` requires
   shrinking the caller's cycle to one opaque action** — concrete evidence
   settling Phase 2's open loop-ownership question in favor of "keep our loop,
   mine ADR's `Policy`/`Decision`/`Goal` primitives," with a precise mechanism
   (`@act`/`@observe`/`@decide`, the `max_cycles + 1` off-by-one) now documented.
3. **The `bind_agent`/`AgentComponent` adapter seam** (`src/flowgentic/agent.py`)
   — a complete, working template for exposing any framework-external decision
   component as a backend-placed, timed AsyncFlow call without ceding loop
   ownership.
4. **The rehearsal/live decision-model split sharing one typed protocol**
   (`AgentDecisionModel` / `RehearsalDecisionModel` / `LangChainDecisionModel`)
   — reusable template for giving every LLM-backed IMPRESS-A decision point a
   deterministic, network-free stand-in with an identical interface.
5. **`RetryConfig`'s field shape** (attempts, base/max backoff, jitter, timeout,
   exception filter) as the starting point for IMPRESS-A's own retry primitive,
   since neither asyncflow nor this demo's raw-AsyncFlow path provide one.
