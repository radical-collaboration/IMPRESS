# Pluggable Frontends

IMPRESS-A has two independent frontend axes. Both plug into the same engine; neither requires changes
below the layer it occupies.

```
        ┌──── INTERFACE FRONTEND ─────┐        who talks to the campaign
        │  in-process · HTTP+SSE · MCP │
        └──────────────┬───────────────┘
                       │  CampaignControlPlane (one protocol)
        ┌──────────────┴───────────────┐
        │     DECISION FRONTEND        │        who decides what runs next
        │   A · B · C · D · your own   │
        └──────────────┬───────────────┘
                       │  ControlPolicy (one protocol)
        ════════════════════════════════        everything below is shared
          manager · compose · validate
          tools · exec · rhapsody backends
```

## 1. The decision frontend — control models

Exactly one is active per campaign, **fixed at launch** (`docs/decisions/0005`): a campaign has one
stated methodology and its results are attributable to it.

| Model | Mode | What `decide` does | Reproducible |
|---|---|---|---|
| **A** four-node loop | autonomous | A LangGraph `StateGraph`: hypothesize → parameterize. Auditable node by node | structurally |
| **B** oracle | autonomous | One structured call to a heavyweight LLM over rich campaign state | weakly |
| **C** external steering | **headless** | Blocks on the control plane until a caller supplies a directive | caller-dependent |
| **D** explicit policy | autonomous | Deterministic or statistical: rules, bandit, Bayesian optimization, replay | **fully** |

Model **C is the headless mode** (`docs/decisions/0002`) — not an extra option bolted onto the side.

### One contract

```python
class ControlPolicy(Protocol):
    name: str
    async def decide(self, obs: CampaignObservation) -> Decision: ...
    async def interpret(self, results, obs) -> str | None: ...          # optional
    async def on_rejected(self, decision, failure) -> Decision: ...     # mandatory
```

`Decision` is a closed union: `ComposeAndRun | Backtrack | RequestHuman | Stop`. Policies emit **abstract
intent**, never a concrete DAG — that is what keeps them out of tool-invocation details and genuinely
swappable.

`on_rejected` is mandatory and easy to overlook. Validation can refuse a composed graph, and every policy
needs a defined answer to "your proposed experiment is illegal, too expensive, or type-incoherent."

### Writing your own

Subclass `BasePolicy`, implement `decide`, register it. Nothing else changes.

```python
from impress_a.policy.base import BasePolicy
from impress_a.core.decision import ComposeAndRun, ExperimentIntent, Stop

class MyPolicy(BasePolicy):
    name = "mine"
    async def decide(self, obs):
        if obs.cycle >= 5:
            return Stop(reason="enough")
        return ComposeAndRun(intent=ExperimentIntent(
            goal=obs.goal, stages=["generate", "design", "fold", "score"], replicas=2))
```

### Composable wrappers

Policies decorate rather than inherit. `impress_a.policy.wrappers` provides:

- **`RuleCorrectionsPolicy`** — an unconditional external guard that validates and corrects *every*
  decision before it reaches composition. Separation of authority: the policy proposes, the guard
  disposes.
- **`LoggingPolicy`** — provenance decorator.
- **`NullPolicy`** — no-op baseline and control.

```python
policy = LoggingPolicy(RuleCorrectionsPolicy(MyPolicy(), max_replicas=8), sink)
```

### Degraded mode is declared, not improvised

Models B and C depend on something outside the job. Both take a `fallback` (a model-D policy) activated
on oracle failure or caller timeout, and the transition is an **explicit logged state change** — never a
silent no-op that leaves an allocation idling while the campaign quietly stops adapting.

## 2. The interface frontend — control-plane adapters

One transport-agnostic protocol; adapters translate transport only (`docs/decisions/0007`).
**No adapter may add an operation absent from the core**, or the semantics fork between consumers.

| Operation | Purpose |
|---|---|
| `submit` / `pause` / `resume` / `stop` | Lifecycle |
| `observe` | **Returns the same `CampaignObservation` a policy's `decide` receives** |
| `events` | Append-only stream with a resumable cursor |
| `steer` | Inject a directive — this is model C's `decide` |
| `artifacts` / `provenance` | Retrieve results and the audit trail |
| `ingest_measurement` | Out-of-band P8 arrival; accepted even after termination |

The `observe` symmetry is the point: an external caller, an LLM oracle and a user-written policy all
consume the identical observation and return the identical `Decision`. "Informed monitoring" means
**parity of evidence**, not a progress bar.

| Adapter | Status | Fits |
|---|---|---|
| in-process | implemented | HITL agents co-located in the job; tests; the reference implementation |
| HTTP + SSE | not yet built | Pipelining-as-a-service |
| MCP | not yet built | An external agent driving a campaign, submit-and-poll |

### Steering carries no privilege

A caller's directive is composed and passed through all five validation gates exactly as any policy's
decision would be. Rejections come back through `on_rejected` with the gate and reason.

## 3. The substrate is pluggable too

Backends are selected **by name** from site configuration and resolved through
`rhapsody.backends.get_backend()`, so no backend class is named outside `exec/backend.py`:
`concurrent` for laptop and mock, `dragon` / `radical` / `dask` on HPC.
