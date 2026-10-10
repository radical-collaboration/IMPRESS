# 07 — Execution Layer Seam

**Scope note.** Phase 2 explores the RADICAL middleware in depth. This document defines only the *seam* —
what the agent requires of the execution layer and how Part A's compute patterns map onto it — so that Part B
is complete without pre-empting Phase 2's findings.

## 1. Position

```
  campaign manager  ──── validated DAG ────►  EXECUTION LAYER  ────►  rhapsody backend
        ▲                                     radical.asyncflow            │
        └──────────── typed results, QC ──────  WorkflowEngine   ◄─────────┘
```

The agent owns the `WorkflowEngine` directly. This follows from the Part B decision that **IMPRESS is a
callable composite tool, not the control plane** — we do not inherit `ImpressManager`; we build the
equivalent, informed by having read it.

## 2. What the agent requires of the execution layer

| Requirement | Why |
|---|---|
| Submit a DAG of heterogeneous tasks with dependencies | The composed graph mixes GPU inference, CPU fan-out, MPI, and inline calls |
| Async, non-blocking submission | The outer loop must observe and remain steerable while work runs |
| Per-task resource shapes | P1/P2/P3 differ in what they need from the allocation |
| Result and failure propagation | Task agents must post-process outputs and enforce QC gates |
| Backend swappability | HPC vs. edge/mock, without touching anything above |
| Cancellation | Backtracking and `stop` must terminate in-flight work |

The last two are the ones that shape the seam. Backend swappability is why the agent never names a backend;
cancellation is why submission handles are retained per graph.

## 3. Backends

Per the project's stated preferences:

| Environment | Backend |
|---|---|
| HPC | `DragonExecutionBackend` |
| Edge / laptop / mock testing | `ConcurrentExecutionBackend(ProcessPoolExecutor)` |

The mock path is not an afterthought — it is how the campaign manager, policies, composition, validation and
state model are tested without an allocation. `ToolSpec` supports this directly: a spec can declare a mock
executor so a full campaign runs end-to-end on a laptop with stubbed science, exercising every layer above
the substrate. Given the cost of HPC iteration, this is a first-class requirement.

## 4. Pattern dispatch

Part A's taxonomy is operational here: `ToolSpec.pattern` determines dispatch.

| Pattern | Dispatch | Notes |
|---|---|---|
| **P1** GPU-node-local | Task in the allocation, GPU-pinned | Contends with other P1 work; the scheduler's main packing problem |
| **P2** CPU fan-out | Parallel task set | Replica count is a natural adaptive knob |
| **P3** MPI multi-node | Task with a rank layout | Not resizable mid-run; shape fixed at submission |
| **P4** External job | Submit outside the allocation + **durable ledger entry** | Async submit/poll; survives agent restart (`03 §7`) |
| **P5** Network service | Async HTTP with backoff, caching, rate governance | Never a scheduled task |
| **P6** In-process | **Inlined by the composer — never submitted** | Scheduling overhead would exceed the work |
| **P7** Composite | Launch an IMPRESS pipeline as one task | The agent parameterizes and observes; it does not steer internal stages |

Two dispatch rules deserve emphasis because they encode Part A findings rather than convenience:

- **P6 is inlined, not scheduled.** Enforced at composition (`05 §5`); a scheduled P6 node is a composer bug.
- **P4 requires the durable ledger.** External jobs outlive the agent. Without a persisted record of job id,
  expected artifacts, and submitting context, an agent restart orphans them — ChemGraph names this exact
  failure mode, and Part A recorded it.

## 5. The P5 service governor

P5 traffic is centralized through one component rather than left to individual task agents, because the
constraints are global, not per-call:

- **Response cache on shared storage**, keyed by request. Mitigates both rate limits (R3) and re-run cost.
- **Per-service concurrency caps and backoff**, honouring `Retry-After`, as **fixed configuration the agent
  cannot raise** (`bio-databases.md`). An autonomous loop that widens its own concurrency under throttling
  converts a transient limit into abuse of shared public infrastructure.
- **Schema validation on responses**, alerting on unexpected nulls rather than propagating them — R11, whose
  AlphaFold DB sunset date has already passed.
- **ColabFold MSA server monitored as one named dependency**, since Boltz and Chai both default to it and an
  outage degrades two Core tools at once.

Notably, Part A found Boltz's own bundled client retries `RATELIMIT` in an uncapped loop. Routing P5 through
a governor means we do not inherit that behaviour from a vendored client.

## 6. Scheduler portability

Part A established that **neither prior-art execution layer speaks PBS Pro** — `PyRosettaCluster` uses
dask-jobqueue (SLURM/SGE) and AgentRosetta uses blocking `sbatch --parsable --wait`. Polaris and Aurora use
PBS Pro.

The agent therefore never emits scheduler commands. All submission goes through the rhapsody backend
abstraction, and P4 external submission is expressed as a capability request rather than an `sbatch` line.
This is the concrete reason the middleware abstraction earns its place rather than being overhead.

## 7. Deferred to Phase 2

- Which `radical.asyncflow` constructs express our DAG, and whether `executable_task` (shell-command-returning
  async functions, as IMPRESS uses) or a function-task form is right per pattern.
- `DragonExecutionBackend` configuration, resource-shape semantics, and multi-node behaviour.
- Where `radical.adr`, `flowgentic`, and `radex` fit — named for Phase 4 but not yet placed.
- Telemetry: IMPRESS's manager exposes a telemetry subscription hook; whether we adopt something equivalent.
- Whether the control-plane adapter process (`06`) runs on a compute node, a login node, or a service node.
