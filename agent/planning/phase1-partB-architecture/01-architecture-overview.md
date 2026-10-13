# 01 — Architecture Overview

**Phase 1, Part B — IMPRESS-A agent architecture**

## 1. What the system is

An agent that conducts **scientific exploration of protein design space** on HPC, given a design prompt such
as *"stabilize the given protein."* It is autonomous in the project's specific sense: workflow parameters —
and, per the Part B decision, workflow *topology* — are modified at runtime in response to production data.

The system is **not** a pipeline with a smart scheduler. It is a campaign manager that repeatedly decides
what experiment to run next, composes a workflow to run it, executes that workflow on HPC, interprets the
result, and updates a population of design candidates.

## 2. Decisions fixed before design

| Question | Decision | Consequence |
|---|---|---|
| Control modes vs. control models | **Model C *is* control mode 2** | Autonomous mode runs policy A, B, or D. Headless mode *is* policy C. Three autonomous policies, one headless. |
| IMPRESS's role | **A callable composite tool (P7), not the control plane** | We build our own campaign manager on `radical.asyncflow`. `ImpressManager` and `adaptive_fn` are prior art, not inherited infrastructure. |
| Task agents | **Hybrid, declared per tool** | Each `ToolSpec` states whether its task agent is deterministic code or LLM-driven. Cost and determinism stay predictable. |
| Control model selection | **Fixed at launch** | One campaign, one stated methodology. No mid-run policy switching. |
| Mutation scope | **Free graph composition** | The agent composes arbitrary DAGs from the toolkit at runtime. Powerful; requires the validation regime in `05`. |
| Campaign state | **Population + Pareto front, with backtracking** | Multi-objective, non-destructive tree. Follows AgentRosetta's proven pattern. |
| Headless interface | **Transport-agnostic core + adapters** | One control protocol; MCP, HTTP, and in-process are facades over it. |

## 3. Layered structure

```
┌──────────────────────────────────────────────────────────────────────┐
│  INTERFACE                                                           │
│  Mode 1: autonomous (self-governing job)                             │
│  Mode 2: headless — CampaignControlPlane + adapters (MCP/HTTP/proc)  │  → 06
├──────────────────────────────────────────────────────────────────────┤
│  CONTROL POLICY  (exactly one, fixed at launch)                      │
│  A: explicit 4-node agentic loop                                     │
│  B: external heavyweight oracle                                      │  → 02
│  C: external caller steering        (= mode 2)                       │
│  D: user-supplied explicit policy                                    │
├──────────────────────────────────────────────────────────────────────┤
│  CAMPAIGN MANAGER  — the outer loop; owns the cycle                  │  → 01 §4
├──────────────────────────────────────────────────────────────────────┤
│  CAMPAIGN STATE — design tree, Pareto front, provenance, budget      │  → 03
├──────────────────────────────────────────────────────────────────────┤
│  GRAPH COMPOSITION + VALIDATION — typed DAG, dry-run, budget guard   │  → 05
├──────────────────────────────────────────────────────────────────────┤
│  TOOLKITS + TASK AGENTS — ToolSpec registry, skill docs,             │
│  per-tool agents: pre-process → parameterize → execute → post-process│  → 04
├──────────────────────────────────────────────────────────────────────┤
│  EXECUTION LAYER — radical.asyncflow WorkflowEngine                  │  → 07
├──────────────────────────────────────────────────────────────────────┤
│  SUBSTRATE — rhapsody backends                                       │
│  HPC: DragonExecutionBackend · edge/mock: ConcurrentExecutionBackend │
└──────────────────────────────────────────────────────────────────────┘
```

The important property: **the policy layer is the only thing that changes between control models.** Everything
below it is shared. A campaign running policy D exercises exactly the same state, composition, validation,
task-agent, and execution machinery as one running policy B.

## 4. The outer loop

One cycle, identical across control models. Only `decide` and the optional `interpret` differ.

```
                 ┌────────────────────────────────────────────┐
                 │                                            │
                 ▼                                            │
   observe ─→ DECIDE ─→ compose ─→ validate ─→ execute ─→ analyze ─→ update
   (state)   (policy)   (DAG)     (typed,     (asyncflow) (metrics  (tree,
                                   budgeted,               + QC      Pareto,
                                   dry-run)                gates)    provenance)
                                      │                                  │
                                      └── reject ──→ back to DECIDE      │
                                                                         ▼
                                                                   terminate?
```

| Step | Owner | Description |
|---|---|---|
| **observe** | manager | Build a `CampaignObservation`: Pareto front, recent results, budget remaining, diversity, failures. |
| **decide** | **policy** | Return a `Decision`. The only model-specific step. |
| **compose** | manager | Turn the decision's abstract intent into a concrete typed DAG of tool invocations. |
| **validate** | manager | Type-check, cycle-check, resource-feasibility, budget estimate, dry-run parameterization. Rejection returns to `decide` with the reason. |
| **execute** | execution layer | Submit the DAG to the `WorkflowEngine`; dispatch per compute pattern P1–P7. |
| **analyze** | task agents | Post-process each tool's output, extract typed metrics, **enforce QC gates**. |
| **update** | manager | Insert nodes into the design tree, recompute the Pareto front, append provenance, decrement budget. |
| **terminate?** | manager | Goal satisfied, budget exhausted, stagnation, explicit stop, or unrecoverable failure. |

### Why validation sits between compose and execute

Free graph composition means the agent can propose a workflow no human reviewed. Part A's dominant finding
was that these tools fail *silently* — they complete successfully on nonsense. A composed graph must
therefore be proven legal before it consumes allocation time, and proven correct after it runs. `05` details
the regime; the loop above shows where it binds.

## 5. Where the two control modes differ

Both modes run the same loop on the same machinery. They differ in **who closes it**.

| | Mode 1 — autonomous | Mode 2 — headless (= policy C) |
|---|---|---|
| Job shape | Agent is the primary task of the HPC job; self-governing | Workflow is spun up in a job; exposes a control interface |
| `decide` implemented by | Policy A, B, or D, in-process | An external caller, over the control protocol |
| Termination | Agent decides | Caller decides, or declared budget |
| Failure of the decider | Degraded-mode fallback policy (R7) | Campaign holds at a safe point awaiting the caller |
| Use cases | Unattended overnight/multi-day campaigns | Pipelining-as-a-service, MCP-like exposure, HITL steering |

"Informed monitoring" in mode 2 means the caller can retrieve the same `CampaignObservation` the autonomous
policy would have seen — not a progress bar. A caller steering the campaign must have the evidence to steer
it well. That requirement shapes `06`.

## 6. What Part B does not decide

- Which asyncflow constructs express the DAG, and how rhapsody backends are configured — **Phase 2**.
- Whether policy A's four nodes are built on LangGraph or Academy agents — **Phase 4**.
- Repository layout, module boundaries, packaging — **Part C**.
- Any code.
