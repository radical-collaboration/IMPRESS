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

Exactly one is active per campaign, **fixed at launch** ([decision 0005](../decisions/0005-control-model-fixed-at-launch.md)): a campaign has one
stated methodology and its results are attributable to it.

| Model | Mode | Specifier half | Planner half | Reproducible |
|---|---|---|---|---|
| **A** four-node loop | autonomous | `hypothesize → analyze` | `select_tasks → parameterize` | structurally |
| **B** oracle | autonomous | one `SPEC_SCHEMA` call per signal | one `STAGE_SCHEMA` call per round | weakly |
| **C** external steering | **headless** | a `{"role": "specifier"}` inbox | a `{"role": "planner"}` inbox | caller-dependent |
| **D** explicit policy | autonomous | Goal → Spec, deterministically | Tasks by output type | **fully** |

Model **C is the headless mode** ([decision 0002](../decisions/0002-model-c-is-control-mode-2.md)) — not an extra option bolted onto the side.

This section is the catalogue. For what each model is **shown**, what it may choose, how its reply
is constrained, and which campaign fields reach a half, see
[`control-models.md`](control-models.md); for the pipeline all of them drive — caller inputs to
specified targets to a programmed Stage — see [`resolution.md`](resolution.md).

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

Implement the two protocols — or subclass `BaseSpecifier`/`BasePlanner`, whose defaults are a
fixed Spec and a planner that gives up loudly — then add a row to `policy/registry.MODELS` with
both builders. Nothing else changes.

```python
from impress_a.core.goal import Goal
from impress_a.core.spec import Spec, Stage
from impress_a.policy import registry as reasoners     # policy/__init__ re-exports nothing
from impress_a.policy.planner import BasePlanner, PlanningContext
from impress_a.policy.planners import ThresholdPlanner
from impress_a.policy.specifier import BaseSpecifier, SpecEvidence


class MySpecifier(BaseSpecifier):
    name = "mine-spec"

    async def initial_spec(self, goal: Goal) -> Spec:
        ...                      # Goal -> Spec; see policy/specifiers/explicit.py
    # `revise` defaults to "nothing has changed my mind", which is the common case, and
    # `satisfied` to the rule-driven answer off the data registry. Overriding the second
    # means arguing a campaign's stop condition rather than computing it.


class MyPlanner(BasePlanner):
    name = "mine-plan"

    def __init__(self, stages: list[str] | None = None, base_replicas: int = 0) -> None:
        # Type-driven chain resolution and typed port wiring are correctness, not
        # strategy: compose them rather than reimplementing them, as models A, B and C do.
        self._mechanics = ThresholdPlanner(
            stages=stages, **({"base_replicas": base_replicas} if base_replicas else {}))

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        return await self._mechanics.plan(spec, ctx, lineages=2)


reasoners.MODELS["mine"] = reasoners.ReasonerModel(
    letter="mine", name="my control model", mode="autonomous",
    llm_calls=0, llm_shape="none", status="implemented",
    specifier=lambda o: MySpecifier(),
    planner=lambda o: MyPlanner(stages=o.stages, base_replicas=o.replicas),
    note="what is true of this model that a reader would otherwise have to discover")
```

`ReasonerOptions` (`o` above) is the only configuration a builder sees, and `cli.POLICIES` is
derived from `MODELS`, so the letter becomes a valid `--model` with no second list to update. A
builder that needs something only `CampaignSpec` has wants another `ReasonerOptions` field, not an
import — `policy` may import `core` only.

### Composable wrappers

A half is decorated rather than subclassed. `impress_a.policy.wrappers` provides:

- **`StageGuard`** — an unconditional external guard on a Planner half, attached by the CLI unless
  `--no-guard` is passed. It carries `forbid_tools` and **refuses rather than edits**: dropping a
  forbidden tool would leave a hole where a producer was, and a Stage is wired by port, so removing
  a task leaves its consumers pointing at nothing. Two of its predecessor's three corrections moved
  somewhere they cannot be bypassed — the **replica cap** is applied by the executor against the
  campaign's own `replicas`, and a **task serving no objective** is refused by the Reviewer's
  coverage gate — because `--no-guard` could switch both off and should never have been able to.
  `forbid_tools` itself is a stopgap for phase 10's gate 6, which refuses a mock-toolkit node under
  `tool_delivery: real` and cannot be disabled at all.
- **`LoggingSpecifier` / `LoggingPlanner`** — provenance decorators, recording that a half
  *authored* a revision or a Stage. Not redundant with the executor's own records, which say what
  it *applied*: the four-arm comparison reads the second to tell a model that proposed nothing from
  one whose proposals were refused.
- **`NullSpecifier` / `NullPlanner`** — the no-op baseline. An empty Spec makes `complete()` true,
  so the campaign ends through the designed path rather than a `Stop` the driver must recognise.

```python
pair.planner = StageGuard(pair.planner, forbid_tools=("mock_noodle",))
```

### Degraded mode is declared, not improvised

Models B and C depend on something outside the job. Both take a `fallback` (a model-D policy) activated
on oracle failure or caller timeout, and the transition is an **explicit logged state change** — never a
silent no-op that leaves an allocation idling while the campaign quietly stops adapting.

## 2. The interface frontend — control-plane adapters

One transport-agnostic protocol; adapters translate transport only ([decision 0007](../decisions/0007-transport-agnostic-control-plane.md)).
**No adapter may add an operation absent from the core**, or the semantics fork between consumers.

| Operation | Purpose |
|---|---|
| `submit` / `pause` / `resume` / `stop` | Lifecycle |
| `observe` | **Returns the same `CampaignObservation` an in-process half is given** |
| `events` | Append-only stream with a resumable cursor |
| `steer` | Inject a directive — this is model C's planning call, routed to a half by its `role` key |
| `artifacts` / `provenance` | Retrieve results and the audit trail |
| `ingest_measurement` | Out-of-band P8 arrival; accepted even after termination |

The `observe` symmetry is the point: an external caller, an LLM oracle and a user-written half all
consume the identical observation and answer in the identical vocabulary — a `SpecRevision` from the
Specifier side, a candidate `Stage` from the Planner side. "Informed monitoring" means **parity of
evidence**, not a progress bar.

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

A caller's directive is composed, type-checked, gated and budget-checked exactly as any Planner's
Stage is — including the Reviewer's coverage check against the applied Spec. A rejection comes back
to the caller through `replan` with the gate and the reason, for another turn. A caller may add and
delete objectives but may **not** declare one satisfied: satisfaction is computed, not asserted
(see [`resolution.md`](resolution.md) step 8).

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
