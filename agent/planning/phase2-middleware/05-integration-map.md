# 05 — Integration Map and Verdict

Synthesis of `01`–`04`. What IMPRESS-A is actually built on, what it builds itself, and where the stated
expectation held or did not.

---

## 1. Verdict on the hypothesis

> Task execution via **asyncflow**; agent tasks via **flowgentic**; autonomous encapsulation with swappable
> policies via **radical.adr**; **rhapsody** not called directly, accessed via asyncflow.

| Leg | Verdict | Basis |
|---|---|---|
| Task execution via asyncflow | ✅ **Confirmed, and stronger than expected** | The `WorkflowEngine` genuinely supports a **runtime-composed** DAG. Dependencies are expressed by passing unawaited futures as call arguments and resolved by a ready-queue scheduler — not by literal `await` chains in source. A single generic dispatch loop suffices; no code generation, AST work or templating. |
| rhapsody reached only via asyncflow | ❌ **Refuted for backends**, ✅ true for telemetry | asyncflow ships only `NoopExecutionBackend` and `LocalExecutionBackend` (`backends.py:25,168`) and does not declare rhapsody as a dependency. Every HPC example does `from rhapsody.backends import ...`, constructs the backend, and passes it to `WorkflowEngine.create(backend=...)`. Telemetry *is* intermediated — `flow.start_telemetry()` wraps `rhapsody.telemetry.manager.TelemetryManager` internally. |
| Agent tasks via flowgentic | ⚠️ **Partially — and it conflates two of our layers** | flowgentic really does route a LangGraph tool call through asyncflow as a task. It does **not** implement control policies, decision objects, cycle/backtrack/stop semantics, task-agent phasing, or QC gates. |
| Swappable policies via ADR | ⚠️ **Half right — real abstraction, structural conflict** | ADR has a genuine `Policy`/`@decide`/`Decision` abstraction, the best evidence in the refcode set for what a policy layer should look like. But `Operator.run()` owns a complete outer loop of its own, which collides with ours. |

**The correction that matters most:** rhapsody is a **first-class, directly-named dependency** of our backend
construction, not a hidden implementation detail. The mitigation is cheap — rhapsody's
`BackendRegistry.get_backend(name, **cfg)` (`backends/discovery.py:169`) resolves a backend from a *string*,
so `sites/*.yaml` can name `dragon` or `concurrent` and our code never writes `import rhapsody`. That
recovers the spirit of the hypothesis without pretending the dependency is absent.

**The finding the hypothesis missed entirely:** ORBIT is more central than "reference only." It holds the
only PBS Pro support in the stack, the only external-batch-job path (PSI/J), and a firewall-traversing
control-plane transport — three things Part B had listed as unresolved or self-build.

---

## 2. The recommended stack

| Part B layer | Component | Disposition |
|---|---|---|
| Interface — headless control plane (mode 2) | **ORBIT** broker/endpoint + FastAPI/SSE gateway | **Evaluate for adoption.** Solves M6. Cost: operating a broker. Maturity unverified. |
| Control policy (models A/B/D) | **Ours**, informed by ADR | **Build.** Mine ADR's policy-interface shape, `Goal`/`AllGoal`/`AnyGoal` stop predicates, and `RecordingObserver`/`replay_trace`. Do **not** call `Operator.run()`. |
| Campaign manager — the outer loop | **Ours** | **Build.** Non-negotiable: our loop carries the governance. |
| Campaign state, Pareto, provenance | **Ours** | **Build.** Nothing in the stack provides it. |
| Composition + five validation gates + interlock | **Ours** | **Build.** ADR offers only thin action-shape validation. |
| Toolkits, `ToolSpec`, task agents | **Ours**; optionally flowgentic's bridge pattern | **Build**, reimplementing flowgentic's ~40-line decorator with our phasing built in. |
| LLM integration for policies / LLM task agents | **LangGraph** (+ LiteLLM), used directly | **Adopt directly**, not through flowgentic. |
| Execution — DAG, scheduling, futures | **radical.asyncflow** | **Adopt.** The confirmed leg. |
| Substrate — backends | **rhapsody**, via `get_backend()` from site config | **Adopt**, named in config not code. |
| External batch jobs (P4) | **ORBIT** `plugin_psij` + `BatchSystem` (PBS Pro / SLURM) | **Evaluate.** The only implementation that exists. |
| On-prem LLM serving | **rhapsody** `DragonVllmInferenceBackend` | **Useful** for control model B degraded mode. |
| In-memory data exchange | **radex** | **Out of scope.** |
| Telemetry | asyncflow `start_telemetry()` → rhapsody | **Adopt** as an event source for the control plane. |

---

## 3. What we build ourselves

None of these are gaps waiting to be filled upstream — all are explicitly out of scope for the middleware.

| # | Component | Why nothing provides it |
|---|---|---|
| 1 | **Durable P4 job ledger** | asyncflow state is in-process and cleared at shutdown; rhapsody has no persistence. P4 must outlive the agent. |
| 2 | **Resource normalization** | RADICAL takes `{"ranks","gpus_per_rank"}`; Dragon takes `process_template(s)`. No common vocabulary exists. `ToolSpec.resources` → per-backend translation is ours. |
| 3 | **Per-cycle / per-lineage bookkeeping** | asyncflow's UID namespace is flat and global (`task.NNNNNN`); there is no way to enumerate "tasks of cycle 7". Needed for backtracking and cancellation. |
| 4 | **P5 governor** | Caching, fixed concurrency caps, `Retry-After` backoff. Nothing upstream addresses network-service etiquette. |
| 5 | **Retry policy** | asyncflow has **no retry primitive at all**. |
| 6 | **Five validation gates, dry-run, self-promoting interlock, budget guard** | ADR validates action shape only, and on failure *raises*, terminating its loop rather than routing to `on_rejected`. |
| 7 | **`ControlPolicy` + `Decision` union + campaign tree + Pareto front + provenance** | ADR's `Decision` is a flat action bag with no `Backtrack`/`RequestHuman` and no `interpret`/`on_rejected`. |
| 8 | **QC gates and task-agent phasing** | Neither flowgentic nor anything else provides pre/parameterize/post structure. |

---

## 4. Part B's open questions, resolved

| # | Question | Resolution |
|---|---|---|
| **M1** | Which asyncflow constructs express a runtime-composed DAG? | **Resolved.** `executable_task` (async fn returning a shell command string), `function_task`, `prompt_task`. Dependencies are unawaited futures passed as arguments. Runtime composition works via one generic dispatch loop. *Caveat:* a dependency future passed positionally does not auto-inject its resolved value — the task function must `await` it explicitly. Codify as a `ToolSpec` convention. |
| **M2** | Dragon config, resource semantics, multi-node | **Resolved, negatively.** Resource shapes are backend-specific and mutually incompatible. We must normalize. Dragon needs Python ≥3.11; example uses `DragonExecutionBackendV3` while `__init__` exports `DragonExecutionBackend` — pin deliberately. |
| **M3** | Where do adr / flowgentic / radex / orbit fit? | **Resolved.** See §2. ADR → mine for patterns. flowgentic → mine one pattern. radex → out of scope. ORBIT → promoted to candidate dependency. |
| **M4** | Cancellation adequate for backtracking and `stop`? | **Partially.** asyncflow exposes cancellation through `@flow.block` handles, so the composer must consistently wrap each cycle/lineage in a block to get a usable handle. Caution: ADR depends on an **unmerged asyncflow branch** (`feature/enable_block_cancellation`) — do not build on ADR's cancellation surface. |
| **M5** | Telemetry | **Resolved.** `flow.start_telemetry(**cfg)` + `telemetry.subscribe(fn)`, wrapping rhapsody's `TelemetryManager`. Suitable as a control-plane event source. Requires `rhapsody-py[telemetry]` **even on the mock path**, which slightly compromises a fully rhapsody-free laptop configuration. |
| **M6** | Where does the control-plane adapter run? | **Resolved (candidate).** ORBIT endpoints dial the broker over a single **outbound** WebSocket, so no compute node needs to accept inbound connections. The FastAPI/SSE gateway with drop-oldest backpressure maps onto Part B `06`'s event stream. |
| **M7** | Is P4 expressible through a backend? | **Resolved.** **Not through rhapsody** — no backend has any external-batch path, and scheduler knowledge is delegated to RADICAL-Pilot. It exists in **ORBIT**: `plugin_psij` (`submit_job`/`get_job_status`/`cancel_job`/`submit_tunneled`) over `BatchSystem(ABC)` with `PBSProBatchSystem` and a SLURM implementation. |

---

## 5. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| **X1** | **Maturity.** flowgentic 0.1.0 (no PyPI, git-URL dep, zero tests on the path we'd use, MCP documented-but-absent, Academy path broken); ADR 0.1.0 (no tags, breaking changes in its own unreleased CHANGELOG, MCP server imports empty stub modules). | **High** | Depend on neither. Mine patterns; reimplement narrowly. |
| **X2** | **ORBIT maturity unverified.** Its apparent fit is strong and its `ROADMAP.md`, `plans/` and tests went unread when the exploring agent was terminated. | **High** | Targeted follow-up before any adoption decision. Named in §7. |
| **X3** | **Resource-shape divergence** across backends in the same release. | Medium | Own the normalization layer; treat `sites/*.yaml` `resource_defaults` as required, not convenience. |
| **X4** | **No durability anywhere in the stack.** | Medium | Build the P4 ledger and cycle checkpointing as designed in Part C `03`. Already planned. |
| **X5** | **Docs ahead of code**, verified in at least two places (ADR's MCP server; flowgentic's `AGENT_TOOL_AS_MCP` missing from the enum). | Medium | Verify any middleware claim against source before relying on it. This report did; future phases must too. |
| **X6** | **Broker operation** is a standing operational commitment if ORBIT is adopted. | Medium | Decide who runs it and where before committing. |
| **X7** | **Undeclared / optional dependency edges** — asyncflow imports rhapsody without declaring it; rhapsody↔ORBIT couple bidirectionally through optional extras. | Low–Medium | Pin all four explicitly in our own environment spec rather than relying on transitive resolution. |

---

## 6. What changes in Parts B and C

Phase 2 validated the architecture rather than overturning it. Four adjustments:

1. **Part B `07`** — restate the backend seam: rhapsody is a directly-named dependency reached via
   `get_backend()` from site config, not hidden behind asyncflow. Add the resource-normalization layer as
   an explicit component.
2. **Part B `07`** — P4 dispatch gains a concrete candidate implementation (ORBIT PSI/J), replacing "needs
   its own path, mechanism TBD."
3. **Part B `06`** — the control plane gains ORBIT as a candidate transport, and M6 is answered.
4. **Part C `04`** — `sites/*.yaml` should carry a backend *name* plus a normalized resource block, and
   the environment spec must pin asyncflow, rhapsody, and (if adopted) ORBIT explicitly.

No Part B decision is reversed. The layering held: policies stay ignorant of tools, composition stays
execution-agnostic, and the outer loop remains ours.

---

## 7. For Phase 4

Ordered by what most reduces uncertainty.

1. **Assess ORBIT properly.** The one real gap in Phase 2. Read `ROADMAP.md`, `plans/`, `DEPLOYMENT.md`
   and its tests; establish maturity, operational burden, and whether `plugin_psij` works on Polaris.
   It is simultaneously the highest-value and least-verified component.
2. **Spike the generic dispatch loop** — our typed DAG → asyncflow futures — on `ConcurrentExecutionBackend`.
   This validates M1 end to end on a laptop and is the cheapest possible test of the core bet.
3. **Decide LangGraph vs. Academy directly.** flowgentic imports both but only LangGraph works there, which
   is weak evidence. ChemGraph (Part A) demonstrates LangGraph at scale with SQLite checkpointing and
   `interrupt`-based HITL. Evaluate on our own requirements.
4. **Build the resource-normalization layer early** — everything downstream depends on its vocabulary.
5. **Pin everything.** Four fast-moving packages, two at 0.1.0, one undeclared edge, one unmerged branch
   in a dependency's dependency.
