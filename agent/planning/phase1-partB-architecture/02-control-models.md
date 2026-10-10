# 02 — Control Models

Four models of control over the autonomous workflow. **Exactly one is active per campaign, fixed at launch.**
Model C is control mode 2 (headless); A, B and D run in control mode 1 (autonomous).

## 1. The shared contract

Every model implements one interface. This is what makes the models interchangeable without touching the
campaign manager, the state model, the toolkit, or the execution layer.

```python
# Illustrative notation, not an implementation.

class ControlPolicy(Protocol):
    name: str
    async def decide(self, obs: CampaignObservation) -> Decision: ...
    async def interpret(self, results: ExecutionResults,
                        obs: CampaignObservation) -> Interpretation | None: ...
    async def on_rejected(self, decision: Decision, reason: ValidationFailure) -> Decision: ...
```

`interpret` is optional; the default is deterministic metric extraction performed by task agents. A policy
overrides it only when the *interpretation itself* is a judgement call (policy A's node 4; policy B).

`on_rejected` is mandatory and easy to overlook: validation can refuse a composed graph, and every policy
needs a defined response to "your proposed experiment is illegal, too expensive, or type-incoherent."

### The Decision type

```python
Decision = (
    ComposeAndRun(intent: ExperimentIntent, rationale: str)
  | Backtrack(node_id: NodeId, rationale: str)
  | RequestHuman(question: str, context: dict)   # HITL / mode 2
  | Stop(reason: str)
)
```

`ExperimentIntent` is *abstract* — "design 200 binders against this hotspot, fold and filter them, keep the
Pareto-nondominated" — not a concrete DAG. Turning intent into a validated graph is the manager's job (`05`),
which keeps every policy out of the business of knowing tool invocation details.

---

## 2. Model A — explicit four-node agentic loop

The four nodes named in the specification, mapped onto the manager's cycle:

| Node | Maps to | What it does |
|---|---|---|
| 1. Interpret data → hypothesize / choose experiments | `decide` (part 1) | Reads the observation; forms a hypothesis about what would improve the front |
| 2. Parameterize a workflow | `decide` (part 2) | Turns the hypothesis into an `ExperimentIntent` with concrete parameter choices |
| 3. Run the workflow | manager `execute` | Not the policy's work — the manager and execution layer own this |
| 4. Analyze the workflow | `interpret` | Judges what the results *mean* for the next hypothesis, beyond the metrics |

Node 3 belongs to the manager, not the policy. Stating that plainly avoids a design in which the policy
reaches into execution — the separation is what lets policies be swapped.

**Character.** A structured, inspectable loop. Each node is a bounded LLM call with a declared input and
output schema, so a campaign's reasoning is auditable node by node. Nodes 1, 2 and 4 are separately
promptable, separately testable, and separately cacheable.

**Cost.** Three LLM calls per cycle (plus retries). At Sonnet 5 pricing this is negligible against the compute
it steers (see Part A, T5).

**Failure behaviour.** A node that fails schema validation is retried with corrective feedback, bounded —
AgentRosetta's parse-retry pattern, which `04` recommends reusing. Exhausting retries escalates to the
degraded-mode policy.

**Choose A when** you want the campaign's reasoning to be legible and reproducible in structure, and you are
willing to constrain the agent to a fixed cognitive shape.

---

## 3. Model B — external heavyweight oracle

Describe the state of the campaign and the needs of the next task to a frontier LLM and let it work through
the data.

**Character.** One call per cycle, much larger context, far less imposed structure than A. The oracle sees a
rich rendering of the observation — Pareto front, recent lineages, metric distributions, failures, budget —
and returns a decision with a rationale.

**Direct precedent exists and should be studied, not reinvented.** IMPRESS's
`examples/protein_binding/protein_binding_run.py` already does a minimal version of this: a static prompt
plus formatted ensemble distributions, an `anthropic.AsyncAnthropic` call, and a routing decision. It works,
and it demonstrates the shape. It also shows exactly what to improve:

| Precedent behaviour | Problem | Part B requirement |
|---|---|---|
| Decision parsed by exact string match (`"A new sequence should be sampled."`) | Brittle; a reworded reply silently becomes the other branch | **Structured output** with schema validation, bounded retry on parse failure |
| Binary refine-or-resample | Cannot express backtracking, stopping, or novel experiments | Full `Decision` type |
| No retry or backoff | Demonstrated failure mode (R7) | Backoff honouring `Retry-After`; distinguish 429 from 529 |
| Exception swallowed by the manager's `try/except`; pipeline continues **unadapted** | Silent loss of adaptivity — the campaign looks healthy and is no longer steering | Oracle failure is an **explicit, logged state transition** to degraded mode, never a silent no-op |
| No prompt/response logging, no pinned model id | Campaign is not reconstructable (R8) | Full provenance: pinned dated model id, sampling params, prompt and response |
| `max_tokens=256` | Truncates rationale | Size to the decision schema; stream if large |

**Degraded mode is mandatory, not optional.** The oracle is a P5 dependency on a remote service; this very
project lost four subagents to HTTP 429 in one session. When the oracle is unavailable, the campaign must
either fall back to a declared deterministic policy (a model-D instance supplied as `fallback_policy`) or
checkpoint and hold — and it must say which, loudly. A multi-GPU allocation idling silently on a network
error is the worst available outcome.

**Choose B when** the problem benefits from open-ended reasoning over rich state and you accept lower
structural reproducibility in exchange.

---

## 4. Model C — external caller steering (= control mode 2)

The scientific machinery is exposed headless; an external agent supplies the decisions.

`decide` does not compute — it **blocks on the control plane** until the caller supplies a directive, or a
declared timeout fires. The campaign is otherwise identical: same state, same composition, same validation,
same execution.

```
external caller ──steer(directive)──→ CampaignControlPlane ──→ decide() unblocks ──→ Decision
                ←──observe()/events()── (Pareto front, metrics, budget, failures)
```

Three consequences worth stating:

1. **The caller is subject to the same validation.** A directive that composes to an illegal, type-incoherent,
   or over-budget graph is rejected exactly as an LLM policy's would be, and the rejection is returned to the
   caller through `on_rejected`. Being external confers no privilege.
2. **Timeout policy must be declared at launch.** An external caller that goes away must not strand a job
   holding nodes. Options: hold-and-checkpoint, fall back to a declared policy, or stop cleanly.
3. **This is the HITL path too.** A human-in-the-loop agent is just a caller that happens to have a person
   behind it. `RequestHuman` from any policy routes through the same interface.

Protocol and adapters: `06`.

---

## 5. Model D — user-supplied explicit adaptive policy

Deterministic or statistical policies written by the user, implementing the same `ControlPolicy` interface.
**No LLM involved.**

Representative implementations:

| Policy | Fit |
|---|---|
| Threshold / rule cascade | "If scRMSD < 2 Å and ipTM > 0.8, promote; else resample." Encodes an established protocol directly. |
| Multi-armed bandit over tool choices | Learns which generation settings pay off within a campaign |
| Bayesian optimization over the parameter space | Continuous parameters with expensive evaluations — a natural fit |
| Evolutionary / genetic | Population is already the state model; mutation and crossover over design lineages |
| Replay | Re-execute a recorded decision sequence from provenance — the mechanism for exact campaign reproduction |

**Model D is not the fallback option; it is the scientific control.** A campaign run under D with a fixed seed
is reproducible end to end, which makes it the baseline against which A and B must justify their cost. The
replay policy is also how a provenance log becomes an executable artifact rather than a record.

**Choose D when** the decision procedure is known, when reproducibility is paramount, or when establishing a
baseline.

---

## 6. Comparison

| | A — 4-node loop | B — oracle | C — external caller | D — explicit policy |
|---|---|---|---|---|
| Control mode | 1 (autonomous) | 1 (autonomous) | **2 (headless)** | 1 (autonomous) |
| LLM calls / cycle | ~3 (bounded) | 1 (large) | 0 (local) | 0 |
| Reproducible | structurally | weakly | depends on caller | **fully** |
| Open-endedness | medium | **high** | caller-dependent | low |
| Auditability | **high** (per node) | medium (one rationale) | high (directives logged) | **high** |
| Primary failure mode | node schema violation | API outage (R7) | caller disappears | policy bug |
| Fallback | degraded policy | degraded policy (required) | declared timeout behaviour | none needed |

## 7. Selection and provenance

The active model is named in the campaign specification and **cannot change during the campaign.** This is a
deliberate scientific-integrity choice: a campaign has one stated methodology, and a result is attributable to
it. Switching policies mid-run would make a campaign's provenance a narrative rather than a record.

Two mechanisms exist inside the fixed-model constraint and are **not** exceptions to it, because both are
declared up front:

- **`fallback_policy`** — a model-D policy declared at launch, activated only on oracle or caller
  unavailability, logged as an explicit state transition with its trigger and duration.
- **`RequestHuman`** — any policy may pause and escalate. This suspends the campaign; it does not replace the
  policy.

Every decision is recorded with: the policy that produced it, its rationale, the observation hash it saw, and
— for LLM policies — the pinned dated model id, sampling parameters, and full prompt and response (`03`).
