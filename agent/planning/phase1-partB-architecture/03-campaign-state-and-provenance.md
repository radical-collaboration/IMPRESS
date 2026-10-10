# 03 — Campaign State and Provenance

Campaign state is **a population of design lineages held as a non-destructive tree, ranked by a multi-objective
Pareto front, with a complete provenance record.**

## 1. Why this shape

Three independent reasons converge on it.

- **Protein design is irreducibly multi-objective.** A stabilized variant that loses activity is not a
  success. Collapsing ipTM, scRMSD, ΔΔG, clashscore and cost into one weighted scalar requires choosing
  weights before you know the trade-off surface, and then hides the very trade-off the campaign exists to
  discover.
- **Generative design gets stuck.** Refining one lineage walks into local optima with no escape. A population
  plus non-destructive backtracking gives the policy a way out that does not require discarding work.
- **It is proven in this exact domain.** AgentRosetta implements precisely this — a tree `Trajectory` with
  `go_back_to_step`, and Pareto-front selection over named, direction-tagged reward fields via `paretoset`
  (a lightweight, directly adoptable dependency). Part A recommended reimplementing the tree natively and
  adopting `paretoset`.

## 2. Core structures

```python
# Illustrative notation.

@dataclass(frozen=True)
class DesignNode:
    id: NodeId
    parent: NodeId | None              # None only for the root
    cycle: int                         # which outer-loop cycle produced it
    artifacts: dict[str, ArtifactRef]  # typed refs: backbone, sequence, complex, trajectory...
    metrics: dict[str, Metric]         # typed, with provenance of which tool produced each
    qc: QCReport                       # gate results; see §5
    produced_by: GraphId               # the validated DAG that created it
    decision: DecisionId               # the decision that composed that DAG
    status: Literal["live", "pruned", "failed", "promoted"]

class CampaignTree:
    """Append-only. Nodes are never mutated or deleted; status changes are new records."""
    def add(self, node: DesignNode) -> NodeId: ...
    def children(self, id: NodeId) -> list[DesignNode]: ...
    def lineage(self, id: NodeId) -> list[DesignNode]:   # root → node
    def branch_from(self, id: NodeId) -> BranchContext:  # backtracking, non-destructive
    def live(self) -> list[DesignNode]: ...
```

**Append-only is load-bearing.** Backtracking must not destroy the branch being abandoned: the policy may be
wrong, and a later cycle may want to return. It is also what makes the tree a scientific record rather than a
working set.

## 3. Objectives and the Pareto front

Objectives are **declared in the campaign specification**, each with a direction and an optional constraint:

```yaml
objectives:
  - name: sc_rmsd          # self-consistency: design → predict → superpose
    direction: minimize
    constraint: {max: 2.0}         # Å — field-standard acceptance
  - name: iptm
    direction: maximize
    constraint: {min: 0.8}
  - name: ddg
    direction: minimize            # kcal/mol, stabilizing is negative
  - name: clashscore
    direction: minimize
    constraint: {max: 10.0}
  - name: cost_node_hours
    direction: minimize            # cost is a first-class objective, not an afterthought
```

The front is recomputed after every cycle over the live population. **Constraints prune; directions rank.**
A candidate violating a hard constraint leaves the live set regardless of how well it scores elsewhere —
this is how Part A's QC thresholds become policy rather than advice.

Including `cost_node_hours` as an objective is deliberate. Part A found a seven-order-of-magnitude cost spread
between ML and physics answers to the same question; a front that ignores cost will happily recommend
saturation `cartesian_ddg`.

**The front is what the policy sees.** `CampaignObservation` carries the nondominated set, not the raw
population, plus enough distributional context to judge whether a new candidate is actually good.

## 4. Diversity monitoring

Part A noted that ESM embeddings uniquely enable something nothing else in the toolkit provides: detecting
whether the design population is **collapsing to a single mode.** A generative campaign that converges
prematurely will report improving scores while exploring nothing.

Each cycle computes an embedding-space diversity statistic over the live population and surfaces it in the
observation. Sustained collapse is a signal the policy can act on — force exploration, backtrack, or widen
sampling temperature — and a termination condition if it persists.

## 5. QC reports as first-class state

Part A's dominant finding was that these tools **fail silently**. A `QCReport` is therefore attached to every
node and is not optional:

```python
@dataclass(frozen=True)
class QCReport:
    gates: dict[str, GateResult]     # gate name → pass | fail | not_run, with the observed value
    verdict: Literal["pass", "fail", "suspect"]
    notes: list[str]
```

`suspect` matters as much as `fail`. A structure that passes every hard gate but sits far outside the
population's metric distribution is not obviously wrong and not obviously right; surfacing it lets the policy
investigate rather than silently promote it.

A node whose QC verdict is `fail` is never eligible for the Pareto front, no matter its scores. This is the
single most important coupling between Part A's findings and Part B's design.

## 6. Provenance

The provenance log is **append-only, on the shared filesystem, written before the action it describes
completes.** It is the record that makes a campaign reconstructable, and R8 makes it a scientific-integrity
requirement rather than an engineering nicety.

| Record | Contents |
|---|---|
| `CampaignRecord` | Spec, objectives, active control model, declared budget, `fallback_policy`, start time, software versions |
| `DecisionRecord` | Policy name, observation hash, `Decision`, rationale. For LLM policies: **pinned dated model id**, sampling params, full prompt, full response, token usage |
| `GraphRecord` | The composed DAG, its validation result, its cost estimate |
| `ExecutionRecord` | Per-task: tool id and version, resolved parameters, **model checkpoint hash**, resource shape, wall-clock, exit status |
| `ResultRecord` | Emitted artifacts, extracted metrics, QC report |
| `StateTransition` | Policy degradations, HITL escalations, budget threshold crossings, termination |

Two requirements that are easy to get wrong:

- **Pin the dated model id, never an alias.** An alias silently changes what the campaign was steered by.
- **Record tool versions and checkpoint hashes at execution time**, not from config. Part A found
  `foundry install` cannot detect a truncated download — every `REGISTERED_CHECKPOINTS` entry has
  `sha256=None`. Hashing the checkpoint actually loaded is the only way to know what ran.

The log is what makes model D's **replay policy** possible: a recorded `DecisionRecord` sequence can be
re-executed to reproduce a campaign exactly, turning provenance from a record into an executable artifact.

## 7. Checkpointing and recovery

The campaign must survive its job being killed — by walltime, preemption, or node failure.

| When | What is persisted |
|---|---|
| After every cycle | Full `CampaignTree`, Pareto front, budget ledger |
| **Before every oracle call** | Campaign state (R7 — an API failure must not lose the cycle's work) |
| On every P4 submission | Durable external-job ledger entry (job id, expected artifacts, submitting node) |
| On every state transition | Immediately |

Recovery reloads the tree and the job ledger, reconciles any external jobs that completed or died while the
agent was gone, and resumes at the next cycle boundary. **Cycle boundaries are the only recovery points** —
a partially executed graph is re-run rather than resumed, because a partially-complete DAG whose task agents
did not all run their QC gates is exactly the silent-failure case we refuse to accept.

## 8. Budget

Budget is tracked as a ledger with several independent dimensions, any of which can terminate a campaign:

| Dimension | Why it is separate |
|---|---|
| Node-hours (GPU) | The scarce resource on the allocation |
| Node-hours (CPU) | Rosetta and MD consume this independently |
| Wall-clock | The job has a hard walltime regardless of consumption |
| Oracle calls / tokens | Bounds model B, and bounds cost |
| External (P4) jobs submitted | Queue-wait exposure, and courtesy to the scheduler |
| P5 requests per service | Courtesy and rate-limit compliance (R3) |

Every composed graph is cost-estimated against Part A's T5 table before submission and refused if it would
exceed a remaining budget. Budget is also an objective (§3), so the policy is pushed toward cheap experiments
rather than merely stopped at the wall.
