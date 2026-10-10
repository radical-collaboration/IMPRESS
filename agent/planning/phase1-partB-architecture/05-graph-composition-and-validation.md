# 05 — Graph Composition and Validation

**Decision:** the agent has **free graph composition** — it composes arbitrary DAGs from the toolkit at
runtime, choosing tools and their wiring per iteration.

This is the most powerful of the three options considered and the hardest to make safe. It collides directly
with Part A's dominant finding: these tools fail *silently*, completing successfully on invalid input. A
system that lets an LLM wire arbitrary tools together and trusts exit codes will burn an allocation producing
confident nonsense.

This document is the regime that makes free composition survivable. It is not a hedge against the decision —
it is what the decision requires.

## 1. The composition pipeline

```
ExperimentIntent (abstract, from the policy)
        │
        ▼
  ┌──────────┐   composer expands intent into a concrete DAG of ToolSpec invocations
  │ COMPOSE  │
  └────┬─────┘
       ▼
  ┌──────────┐   five gates, all must pass; any failure returns to the policy
  │ VALIDATE │   1. type  2. structure  3. parameter  4. resource  5. budget
  └────┬─────┘
       ▼
  ┌──────────┐   every task agent parameterizes and checks preconditions — nothing executes
  │ DRY-RUN  │
  └────┬─────┘
       ▼
  ┌──────────┐   submit to the WorkflowEngine
  │ EXECUTE  │
  └──────────┘
```

Rejection at any gate produces a structured `ValidationFailure` naming the gate, the offending node, and the
reason. That goes back to the policy through `on_rejected` (`02 §1`), which is why every policy is required
to implement it. **A rejected graph costs nothing but a cycle** — this is the mechanism that makes free
composition affordable to get wrong.

## 2. Gate 1 — type checking

Every edge must connect a producer output to a consumer input of a unifying `ArtifactType` (`04 §4`).

This is where free composition earns its safety. Because the type lattice is scientific rather than
format-based, whole classes of error become compile-time rather than runtime:

| Illegal composition | Caught as |
|---|---|
| Feed a bare `SmallMolecule` to GROMACS | Type error — GROMACS requires `Parameterized` |
| Score an interface on a monomer `Backbone` | Type error — InterfaceAnalyzer requires `Complex` |
| Fold a `Backbone` without an intervening inverse-folding step | Type error — predictors consume `ProteinSequence` |
| Compare structures of different design lineages for self-consistency | Type-correct but *semantically* wrong — caught by gate 2 |

That last row is the honest limit of typing, which is why there are four more gates.

## 3. Gate 2 — structural checking

| Check | Rule |
|---|---|
| Acyclicity | The graph is a DAG |
| Reachability | Every node contributes to at least one declared output; no orphan subgraphs |
| Provenance coherence | A self-consistency comparison must superpose a structure against **its own lineage's** source backbone — the single most common semantically-wrong-but-type-correct composition |
| Gate completeness | Every tool's `qc_gates` are present and enabled. A tool cannot be composed with its gates stripped |
| Terminal metrics | The graph produces at least one metric named in the campaign's objectives — otherwise the cycle cannot inform the Pareto front and is wasted compute |

## 4. Gate 3 — parameter checking

Each node's arguments are validated against its `ToolSpec`:

- Every parameter within its declared range.
- No `frozen_parameters` touched — rejected with the reason recorded in the spec.
- Cross-parameter consistency where declared (e.g. a diffusion step count coherent with the noise schedule).

## 5. Gate 4 — resource feasibility

Checked against the *actual* allocation, not an idealized one:

- Requested resource shapes fit the allocation (a 4-GPU task in a 2-GPU job is refused at compose time, not
  discovered at submission).
- **GPU portability is checked against the running platform.** Part A's T6 is machine-readable here: a graph
  composing RF3 on Frontier is refused, because no HIP path exists. This is the mechanism that stops the
  portability risk (R1) from becoming a runtime surprise.
- P4 nodes are permitted only if the campaign declares external submission; their queue-wait exposure is
  estimated separately from in-allocation cost.
- P6 nodes are never scheduled — the composer inlines them. A graph that schedules a P6 tool is a composer
  bug and is rejected.

## 6. Gate 5 — budget

Every node is cost-estimated from its `cost_model` (Part A's T5) and summed. The graph is refused if the
estimate exceeds remaining budget in any dimension (`03 §8`).

This gate is where Part A's seven-order-of-magnitude cost spread is enforced rather than merely documented.
A policy proposing saturation `cartesian_ddg` across 3,800 mutations is told, concretely, that it would cost
thousands of CPU-hours against a remaining budget of tens — and `on_rejected` gives it the numbers to
propose the cheap-screen-then-confirm alternative instead.

## 7. Dry-run

Validation proves the graph is *legal*. Dry-run proves each task agent can actually parameterize it.

Every task agent runs pre-process and parameterize **without executing**: staging paths resolve, input
conversions succeed, `preconditions` hold, checkpoints exist and hash as expected, concrete arguments are
constructible. Tool-native validation is used wherever it exists — Part A found RosettaScripts supports
`-validate_and_exit`, and AgentRosetta already uses exactly this before committing to a real run.

Dry-run catches the errors typing cannot: a missing checkpoint, an unreadable input, a protocol that is
syntactically invalid, a ligand whose parameterization fails.

## 8. Post-execution: the QC layer

Validation is necessary and insufficient. A graph can be legal, affordable, and dry-run clean, and still
produce garbage — that is precisely Part A's finding.

Three layers of post-execution defence, in order:

| Layer | Owner | What it catches |
|---|---|---|
| **Tool-level QC gates** | task agent post-process | Known, tool-specific silent failures from the `ToolSpec` — a structure with no secondary structure, an affinity prediction on an out-of-regime ligand, a ΔΔG failing its free antisymmetry self-check |
| **Cross-tool consistency** | manager analyze | Agreement between independent tools that should agree — ESMFold vs. Boltz on the same sequence, ThermoMPNN vs. Stability Oracle on the same mutation. Disagreement marks a node `suspect` |
| **Distributional** | manager analyze | A candidate far outside the population's metric distribution. Not necessarily wrong — could be the breakthrough — but never silently promoted |

A node failing layer 1 is `fail` and never reaches the Pareto front. Layers 2 and 3 produce `suspect`, which
is surfaced to the policy rather than suppressed.

## 9. What this regime does and does not buy

Stated plainly, because free composition was chosen with open eyes.

**It prevents:** type-incoherent workflows, missing QC gates, frozen-parameter tampering, resource-infeasible
graphs, platform-impossible graphs, budget overruns, and every silent failure Part A catalogued per tool.

**It does not prevent:** a scientifically pointless but perfectly legal experiment. Nothing here stops the
agent from composing a valid workflow that answers a question not worth asking. That is a *policy* quality
problem, addressed by skill documentation (`04 §3`), by the objectives and Pareto front pushing toward the
declared goal, and by the budget making waste self-limiting.

**The residual risk is novel silent failure** — a failure mode no `ToolSpec` anticipated, in a tool
combination no human reviewed. Cross-tool consistency and distributional checks are the general defences,
but they are statistical, not sound. This is the genuine cost of free composition over a fixed graph, and it
should be stated in any scientific write-up of a campaign rather than discovered by a reviewer.

**Mitigation: the self-promoting interlock, §10.** It is a permanent gate, not temporary scaffolding, and
it does not require a human to approve each new composition.

## 10. The self-promoting interlock

**Decision.** Novel compositions are never blocked and never trusted on sight. They run under extra
scrutiny, and a composition pattern earns trusted status mechanically by accumulating clean runs.

This is deliberately neither of the two obvious postures. A *temporary* allowlist that is eventually
switched off globally means that, after the switch, a genuinely novel composition runs unexamined — the
risk is postponed, not managed. A *permanent per-pattern sign-off* never accepts that risk but caps the
agent at human-reviewed patterns, which gives back most of the reason free composition was chosen over a
fixed graph. The interlock keeps the agent's ability to invent an unanticipated experiment while ensuring
nothing unreviewed is ever quietly believed.

### Pattern identity

A **composition pattern** is the graph's shape, not its parameter values: the ordered multiset of tool ids
and the typed edges between them. `RFD3 → MPNN → Boltz-2 → US-align` is one pattern whether it runs 10
designs or 1,000. Parameters are already governed by declared ranges (gate 3), so patterns are the right
granularity for trust — otherwise every parameter change would reset it.

### Two tiers

| | **Trusted** | **Provisional** (any pattern not yet trusted) |
|---|---|---|
| Seeded from | Canonical sequences in the toolkit skill documents | Everything else, including anything the policy invents |
| Cost ceiling | Normal budget rules | **Capped fraction of remaining budget** (default 10%) |
| Dry-run | Standard | **Mandatory and extended** — every task agent, no skips |
| Result marking | Normal QC verdict | **Auto-marked `suspect` regardless of QC outcome** |
| Cross-tool consistency | Where available | **Required** — the graph must produce at least one independently checkable quantity |
| Pareto eligibility | Immediate | Eligible, but carries its provisional provenance into the front |
| Concurrency | Unrestricted | One provisional pattern in flight at a time |

The `suspect` marking is the heart of it. Part B `03 §5` already defines `suspect` as *surfaced to the
policy, never silently promoted*. A provisional pattern's results are therefore visible as
not-yet-trustworthy to whatever is steering — an LLM policy sees it in the observation, an external caller
sees it in `observe()` and in a `QCSuspect` event. Novelty becomes something the campaign reasons about
rather than something it fails to notice.

### Promotion

A provisional pattern promotes to trusted when **N consecutive clean runs** accumulate (default N=3),
where a clean run means: every QC gate passed, no cross-tool inconsistency, no distributional outlier
among its outputs, and actual cost within tolerance of the estimate.

Promotion is **per-pattern, per-site, and recorded in provenance** as a state transition. Per-site because
a pattern proven on Polaris says nothing about the same pattern on Aurora, where a different GPU backend
and different tool builds are in play.

**Demotion is symmetric and matters as much as promotion.** A trusted pattern that produces a QC failure,
a cross-tool inconsistency, or a significant cost-estimate miss returns to provisional immediately. Trust
decays on evidence rather than persisting because it was granted once.

### Where the trust ledger lives

Alongside campaign state but **scoped to the site, not the campaign** — pattern trust accumulated across
campaigns is exactly what makes the mechanism worth having, since a single campaign may not run any pattern
three times. It is an append-only log like everything else, which keeps it auditable and replayable.

### What this does not solve

The residual risk in §9 is reduced, not eliminated. A novel silent failure that is *consistent* — one that
passes every gate, agrees with a correlated tool, and looks distributionally ordinary on all three runs —
will promote. The interlock buys examination and delay, not soundness. Two honest consequences: N should be
raised for patterns whose outputs feed irreversible or expensive commitments, and cross-tool consistency
should be weighted conservatively until tool independence is better understood (`08`).
