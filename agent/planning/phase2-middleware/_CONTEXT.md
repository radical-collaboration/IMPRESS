# Phase 2 shared context (read this first)

## Project
IMPRESS-A — an autonomous protein-design agent for HPC. Phase 1 is complete: Part A (toolkit, 40 briefs),
Part B (agent architecture), Part C (project structure). Phase 2 explores the RADICAL middleware to decide
what the agent is actually built on.

## The architecture you are mapping onto (Part B, condensed)

**Outer loop**, one cycle: `observe → decide → compose → validate → execute → analyze → update → terminate?`
Only `decide` differs between control models.

**Control models** — exactly one per campaign, fixed at launch. All implement one `ControlPolicy` protocol
(`decide`, optional `interpret`, mandatory `on_rejected`) returning
`ComposeAndRun | Backtrack | RequestHuman | Stop`:
- **A** explicit four-node agentic loop (hypothesize → parameterize → run → analyze)
- **B** external heavyweight LLM oracle
- **C** external caller steering — *this IS headless control mode 2*
- **D** user-supplied explicit policy (rules, bandit, Bayesian opt, evolutionary, replay)

**Campaign state** — append-only tree of design lineages, multi-objective Pareto front, backtracking,
full provenance, cycle-boundary checkpointing, multi-dimensional budget ledger.

**Composition** — the agent composes *arbitrary typed DAGs* at runtime from a tool registry, passing five
validation gates (type, structure, parameter, resource, budget) plus a dry-run, governed by a
self-promoting interlock (novel patterns run capped + auto-`suspect`, promote after N clean runs).

**Task agents** — per tool, hybrid (deterministic or LLM-driven, declared in `ToolSpec`), with four phases:
pre-process → parameterize → execute → post-process (post-process enforces QC gates).

**Compute patterns** (dispatch depends on these):
- P1 GPU-node-local in-job · P2 CPU fan-out in-job · P3 MPI multi-node in-job
- P4 **external HPC job** — submitted outside the allocation, needs a durable job ledger, outlives the agent
- P5 network service over HTTPS — needs a governor: caching, fixed concurrency caps, backoff
- P6 in-process — **must never be scheduled**, inlined
- P7 composite pipeline (IMPRESS pipelines launched as one task)
- P8 external experiment (robotic lab; days–weeks latency, out-of-band; forward-declared, unused)

**Headless control plane (mode 2)** — one transport-agnostic protocol
(`submit/observe/events/steer/pause/resume/stop/artifacts/provenance/ingest_measurement`) with thin adapters
(in-process, HTTP+SSE, MCP). `observe()` must return the *same* observation object a policy's `decide` sees.

## Platform decisions
Polaris + NSF ACCESS (CUDA) **primary**; Aurora (Intel XPU) second; **Frontier deprioritized**.
Compute nodes have full outbound HTTPS egress. Schedulers: PBS Pro (Polaris, Aurora) and SLURM (ACCESS).
Preferred backends: `DragonExecutionBackend` on HPC; `ConcurrentExecutionBackend(ProcessPoolExecutor)` for
edge/laptop/mock testing.

## The hypothesis you are testing (the user's stated expectation — validate or refute it)
- Task execution via **asyncflow**
- Agent tasks via **flowgentic**
- Autonomous encapsulation with swappable policies via **radical.adr**
- **rhapsody is NOT called directly** — it is reached through asyncflow (its repo is reference only)

Treat this as a hypothesis, not a given. If the code supports it, say so with evidence. If it does not —
if a layer is missing, overlapping, immature, or if a component does something different from its name —
say that plainly with file-level evidence. A refutation backed by code is more valuable than agreement.

## Open questions carried from Part B
- **M1** Which asyncflow constructs express a runtime-composed typed DAG? `executable_task` (async fn
  returning a shell command string, as IMPRESS uses) vs. a function-task form — which per pattern?
- **M2** `DragonExecutionBackend` configuration, resource-shape semantics, multi-node behaviour.
- **M3** Where do adr / flowgentic / radex / orbit actually fit?
- **M4** Is cancellation adequate for backtracking and `stop`?
- **M5** Telemetry — IMPRESS's manager exposes a subscription hook; is there an equivalent worth adopting?
- **M6** Where does the control-plane adapter process run — compute, login, or service node?
- **M7** Is P4 external submission expressible through a backend, or does it need a separate path?

## Ground rules
- Reference code is **READ-ONLY**: `<workspace>/impress-a-refcodes/middleware/`. Never modify it.
- Cite real file paths and quote real code. Paths must resolve on disk.
- Distinguish **verified from source** vs. **inferred**. Say when something is undocumented or immature.
- Version numbers matter: note them. `flowgentic` and `radical.adr` are both at 0.1.0 — if they are early,
  say what is actually implemented versus aspirational.
