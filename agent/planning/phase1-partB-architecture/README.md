# Phase 1, Part B — Agent Architecture

**Project:** IMPRESS-A — autonomous protein design on HPC
**Status:** complete, 2026-09-21. Builds on [Part A](../phase1-partA-toolkit/). Input to Part C.

## Reading order

| # | Document | What it covers |
|---|---|---|
| 1 | [`01-architecture-overview.md`](01-architecture-overview.md) | **Start here.** Layers, the outer loop, the two control modes. |
| 2 | [`02-control-models.md`](02-control-models.md) | Models A–D, the shared `ControlPolicy` contract, selection and provenance. |
| 3 | [`03-campaign-state-and-provenance.md`](03-campaign-state-and-provenance.md) | Design tree, Pareto front, QC as state, provenance, checkpointing, budget. |
| 4 | [`04-toolkit-and-task-agents.md`](04-toolkit-and-task-agents.md) | `ToolSpec`, hybrid task agents, toolkits and skill docs, artifact types. |
| 5 | [`05-graph-composition-and-validation.md`](05-graph-composition-and-validation.md) | Free composition and the five-gate regime that makes it survivable. |
| 6 | [`06-headless-control-protocol.md`](06-headless-control-protocol.md) | Control mode 2 / model C: the core protocol and its adapters. |
| 7 | [`07-execution-layer-seam.md`](07-execution-layer-seam.md) | What the agent requires of asyncflow/rhapsody. Seam only — Phase 2 goes deeper. |
| 8 | [`08-open-questions.md`](08-open-questions.md) | Hand-off to Part C, Phase 2, Phase 4 — and gaps unresolved within Part B. |
| 9 | [`09-measurement-and-experimental-seam.md`](09-measurement-and-experimental-seam.md) | One property, two sources: designing surrogates so robotic-lab measurements can replace them. Adds pattern **P8**. |

## Decisions this design rests on

| Question | Decision |
|---|---|
| Control modes vs. models | **Model C *is* control mode 2.** A, B, D run autonomous; C is headless. |
| IMPRESS | **A callable composite tool (P7), not the control plane.** We build our own manager on `radical.asyncflow`. |
| Task agents | **Hybrid, declared per tool** in `ToolSpec`. |
| Control model selection | **Fixed at launch.** One campaign, one methodology. |
| Mutation scope | **Free graph composition.** |
| Campaign state | **Population + Pareto front, non-destructive backtracking.** |
| Headless interface | **Transport-agnostic core + adapters** (in-process, HTTP+SSE, MCP). |

## The design in one page

An outer loop runs one cycle repeatedly: **observe → decide → compose → validate → execute → analyze →
update → terminate?** Only `decide` differs between control models, which is what makes them
interchangeable — a campaign under a user-written policy exercises identical machinery to one under a
frontier oracle.

State is a **non-destructive tree of design lineages** ranked by a **multi-objective Pareto front** with cost
as a first-class objective. QC reports are part of state, and a node failing its gates never reaches the
front regardless of its scores. That coupling is the main structural consequence of Part A.

The agent composes **arbitrary typed DAGs** from the toolkit at runtime. Every graph passes five gates —
type, structure, parameter, resource, budget — then a dry-run in which every task agent parameterizes without
executing. Rejection costs a cycle and returns a reason to the policy, which is what makes free composition
affordable to get wrong.

Each tool carries a `ToolSpec` declaring its types, compute pattern, resource shape, GPU portability,
varyable and **frozen** parameters, QC gates, known silent failures, and cost model. Tools are grouped into
toolkits with agent-facing **skill documents** that initialize expected behaviour before the first decision.

## How Part A shaped Part B

Part B is not a fresh design; nearly every structural choice traces to a Part A finding.

| Part A finding | Consequence in Part B |
|---|---|
| Silent failure is the dominant hazard | QC gates are mandatory in `ToolSpec`, enforced by task agents, part of campaign state, and a hard filter on the Pareto front |
| Seven-order-of-magnitude cost spread | Cost is a declared objective *and* a validation gate; budget is a multi-dimensional ledger |
| The self-consistency loop is the scientific core | Elevated to canonical skill-doc content; provenance-coherence is its own structural check |
| Frontier has no HIP path for the ML core | GPU portability is machine-readable in `ToolSpec` and checked at compose time against the running platform |
| MCP cannot carry HPC execution (2 of 26 verified) | Transport-agnostic core protocol; MCP is one adapter |
| Neither prior-art execution layer speaks PBS Pro | The agent never emits scheduler commands; everything goes through the rhapsody abstraction |
| ColabFold MSA server is a shared single point of failure | Centralized P5 governor with caching, fixed concurrency caps, and named-dependency monitoring |
| Ligand parameterization fails silently in six ways | `SmallMolecule` and `Parameterized` are distinct artifact types — a type error, not a runtime corruption |
| IMPRESS's oracle precedent works but is brittle | Model B's requirements are written as a point-by-point improvement on it |
| AgentRosetta's tree + Pareto patterns | Adopted directly as the campaign state model |

## Honest assessment

**Free graph composition was the most powerful option available and the hardest to validate.** It was chosen
deliberately, and `05` is the regime that makes it workable rather than a hedge against it. The operating
posture is the **self-promoting interlock** (`05 §10`): novel compositions are never blocked and never
trusted on sight — they run under a cost cap, an extended dry-run, and mandatory `suspect` marking, and
promote to trusted automatically after N clean runs, demoting again on any failure. It buys examination and
delay, not soundness: a *consistent* novel silent failure will still promote.

Three further limits are stated rather than buried: the agent cannot author enzyme-design hypotheses, and
budget estimates are unmeasured literature figures pending calibration. The third — that the loop closes
*in silico* only — is now partly addressed: `09` defines the measurement seam so that developability
surrogates can be superseded by robotic-lab assays without redesigning the campaign model. Closing the
design–build–test–learn loop remains a larger project than Phase 1.
