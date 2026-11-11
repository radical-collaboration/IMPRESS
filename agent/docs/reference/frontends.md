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
                       │  Specifier + Planner (two protocols)
        ════════════════════════════════        everything below is shared
          manager · compose · validate
          tools · exec · rhapsody backends
```

## 1. The decision frontend — control models

Exactly one is active per campaign, **fixed at launch** (`docs/decisions/0005`): a campaign has one
stated methodology and its results are attributable to it.

| Model | Mode | Specifier half | Planner half | Reproducible |
|---|---|---|---|---|
| **A** four-node loop | autonomous | `hypothesize → analyze` | `select_tasks → parameterize` | structurally |
| **B** oracle | autonomous | one `SPEC_SCHEMA` call per signal | one `STAGE_SCHEMA` call per round | weakly |
| **C** external steering | **headless** | a `{"role": "specifier"}` inbox | a `{"role": "planner"}` inbox | caller-dependent |
| **D** explicit policy | autonomous | Goal → Spec, deterministically | Tasks by output type | **fully** |

Model **C is the headless mode** (`docs/decisions/0002`) — not an extra option bolted onto the side.

### Two contracts, and why not one

```python
class Specifier(Protocol):
    name: str
    async def initial_spec(self, goal: Goal) -> Spec: ...
    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision: ...
    async def satisfied(self, spec: Spec, ev: SpecEvidence) -> list[str]: ...

class Planner(Protocol):
    name: str
    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None: ...
    async def replan(self, stage, rejection, spec, ctx) -> Stage | None: ...
```

There was one contract, `decide(obs) -> Decision`, and it was deleted in phase 11. It answered
"what should the campaign be trying to achieve" and "which tool should run next" in a single
call, so nothing in a transcript could say which half of a control model earned its cost — and
that is precisely what a four-arm comparison of control models has to be able to say.

A reasoner still emits **abstract intent**, never a concrete DAG: a `Stage` of `TaskMapping`s,
which the composer turns into a typed graph. That is what keeps a reasoner out of
tool-invocation details and genuinely swappable, and `tests/test_layering.py` asserts the
import contract that enforces it — `policy` may import `core` and nothing else.

`replan` is the counterpart of the old mandatory `on_rejected`: validation can refuse a composed
graph, and every Planner needs a defined answer to "your proposed experiment is illegal, too
expensive, or type-incoherent". Returning `None` — "I have no better Stage" — is a valid answer
and ends the campaign with the gate that refused it named.

### Writing your own

Implement the two protocols (or subclass `BaseSpecifier`/`BasePlanner`, whose defaults are a
fixed Spec and a planner that gives up loudly), add a row to `policy/registry.py` with both
builders, and register it. Nothing else changes.

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
| HTTP + SSE | implemented (`control/http.py`) | A reasoner outside the allocation; pipelining-as-a-service |
| MCP | not yet built | An external agent driving a campaign, submit-and-poll |

The HTTP adapter is exercised end to end by `tests/test_http_adapter.py` on loopback, deliberately:
a transport nothing runs looks finished while rotting. It is built on `asyncio.start_server` rather
than a web framework, speaks JSON plus one SSE stream, and is **not public-facing** — no auth, no TLS,
bind it to localhost or a private interface.

Run operations are part of the **core** protocol, not something a transport adds: `submit_run`,
`list_runs`, `run_result`, `cancel_run`. Admission is synchronous — `202` with a run id, or `409` with
the `ValidationFailure` that refused it — because a rejection severed from the request that caused it
leaves nothing to bound retries against.

### Steering carries no privilege

A caller's directive is composed and passed through all five validation gates exactly as any policy's
decision would be. Rejections come back through `on_rejected` with the gate and reason.

## 3. The substrate is pluggable too

Backends are selected **by name** from site configuration and resolved through
`rhapsody.backends.get_backend()`, so no backend class is named outside `exec/backend.py`:
`concurrent` for laptop and mock, `dragon` / `radical` / `dask` on HPC.


## Running the two processes

The interface frontend described above is reachable from a shell as of phase 7 of
`plans/control-plane-refactor.md`. Until then it was reachable only from `tests/`, and this
document described it as implemented anyway (backlog C5).

```bash
impress-a serve campaigns/<spec>.yaml            # execution: executor, Reviewer, Deployer,
                                                 # Runner, the one asyncflow engine. No reasoner.
# it prints: campaign <id> serving on http://127.0.0.1:<port>
impress-a control --connect <url> --campaign <id> --model D
```

Three things worth knowing before using it.

**Loopback is the security boundary.** The plane has no auth and no TLS, so both ends belong on
the same compute node; `--host` exists for a deliberate choice rather than a casual one
(backlog C7).

**The execution side keeps the engine, and only the engine's loop matters.**
`WorkflowEngine.__init__` captures the loop it is built on, and an engine built elsewhere
dispatches nothing while looking healthy - two allocations were lost to that. The control
process has its own loop and never touches an engine, which is why it is free to have one.

**A lost control process drains and stops.** `control_liveness_timeout_s` on the campaign spec
bounds the silence; on expiry the executor stops admitting, lets in-flight work finish and be
absorbed, and stops with a reason naming the loss. Draining rather than aborting is deliberate:
cancellation is advisory, so that work will finish whether or not anyone collects it.

**`impress-a run --model C` is refused**, because `run` attaches no plane and model C means an
external caller steers. It used to time out every five seconds and run its fallback, reporting
a model-D campaign as model C (backlog C6).
