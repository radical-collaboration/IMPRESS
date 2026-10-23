# 06 — Headless Control Protocol (Control Mode 2 / Model C)

The scientific machinery spun up in a job, exposing an interface that lets an external caller monitor it
*informedly* and steer it. **Decision: one transport-agnostic core protocol, with thin adapters.**

## 1. Why a core protocol rather than an MCP server

Part A surveyed 26 MCP entries and found **2 verified**. The healthy corner of that ecosystem is read-only
database lookup; every tool that runs real HPC computation is either absent or wrapped by unaudited third
parties. The one well-engineered exception, ChemGraph, solves the problem by *not* making MCP the
foundation: its `CGFastMCP` wraps tool calls into `TaskSpec` submissions with a disk-persisted `JobTracker`,
and MCP is the facade over that.

Defining our own protocol and adapting it outward follows the same reasoning:

- **Long-running compute does not fit a request/response tool call.** A campaign runs for hours to days.
  Any MCP exposure is necessarily submit-and-poll, which is a property of our protocol, not of MCP.
- **Three consumers, one semantics.** Pipelining-as-a-service (HTTP), MCP-like exposure, and an in-process
  HITL agent are the same operations over different wire formats.
- **MCP is young and moving.** Binding the control plane to it makes the campaign manager hostage to a
  protocol revision.

## 2. The control plane

```python
# Illustrative notation. Transport-agnostic; adapters project this outward.

class CampaignControlPlane(Protocol):
    # lifecycle
    async def submit(self, spec: CampaignSpec) -> CampaignId: ...
    async def pause(self, id: CampaignId) -> None: ...
    async def resume(self, id: CampaignId) -> None: ...
    async def stop(self, id: CampaignId, reason: str) -> CampaignSummary: ...

    # informed monitoring
    async def observe(self, id: CampaignId) -> CampaignObservation: ...
    async def events(self, id: CampaignId, since: Cursor | None) -> AsyncIterator[Event]: ...
    async def artifacts(self, id: CampaignId, sel: ArtifactSelector) -> list[ArtifactRef]: ...
    async def provenance(self, id: CampaignId, sel: RecordSelector) -> list[Record]: ...

    # steering — this is model C's decide()
    async def steer(self, id: CampaignId, directive: Directive) -> SteerResult: ...
    async def answer(self, id: CampaignId, q: QuestionId, response: str) -> None: ...
```

### `observe` is the load-bearing operation

"Informed monitoring" is the requirement, and it is a real constraint: a caller expected to steer must see
what an autonomous policy would have seen. `CampaignObservation` is therefore **the same object passed to
`ControlPolicy.decide`** — not a reduced status summary.

```python
@dataclass(frozen=True)
class CampaignObservation:
    campaign_id: CampaignId
    cycle: int
    goal: str                          # the design prompt
    objectives: list[ObjectiveSpec]
    pareto_front: list[DesignNode]     # nondominated live candidates
    population_summary: PopulationStats    # size, metric distributions, diversity
    recent_results: list[DesignNode]       # last cycle's output, with QC reports
    failures: list[FailureRecord]          # what went wrong, including suspects
    budget: BudgetLedger                   # remaining, per dimension
    tree_summary: TreeSummary              # depth, branches, backtrack points
    available_toolkits: list[ToolkitSummary]   # with skill docs
```

This symmetry is the point of the design: an external caller, an LLM oracle, and a user-supplied policy all
consume the identical observation and return the identical `Decision`. Model C is not a special case bolted
onto the side — it is the same seam, addressed remotely.

### Steering is validated like any other decision

A `Directive` becomes a `Decision`, is composed into a graph, and passes the five gates of `05`. A caller's
directive that is type-incoherent, over budget, or platform-impossible is rejected and the reason returned in
`SteerResult`. Being external confers no privilege — stated in `02 §4` and enforced here.

### Events

An append-only stream with a resumable cursor, so a caller that disconnects can catch up rather than
re-poll from scratch:

| Event | Emitted when |
|---|---|
| `CycleStarted` / `CycleCompleted` | Loop boundaries — the natural steering points |
| `DecisionRequired` | **Model C's block point** — the campaign is waiting for the caller |
| `GraphValidated` / `GraphRejected` | With gate and reason |
| `TaskStarted` / `TaskCompleted` / `TaskFailed` | Per tool invocation |
| `QCFailed` / `QCSuspect` | A node failed or is distributionally odd — the highest-value event for a human reviewer |
| `ParetoFrontChanged` | New nondominated candidate, or one displaced |
| `BudgetThreshold` | A declared fraction consumed |
| `HumanQuestionRaised` | Any policy issued `RequestHuman` |
| `StateTransition` | Degraded mode entered or left, campaign terminated |

## 3. Adapters

| Adapter | Shape | Fits |
|---|---|---|
| **In-process** | Direct Python calls | HITL agents co-located in the job; testing; the reference implementation |
| **HTTP + SSE** | REST for operations, Server-Sent Events for the stream | Pipelining-as-a-service; the most conventional consumer |
| **MCP** | Tools over submit-and-poll, mirroring ChemGraph's `JobTracker` pattern with persisted job state | "MCP-like exposure"; an external Claude-style agent driving a campaign |

Adapters translate transport only. **No adapter may add an operation absent from the core**, or the
semantics fork and the three consumers stop being the same system.

### MCP adapter specifics

The MCP adapter is where Part A's findings bite hardest, so its shape is prescribed rather than left open:

- `submit` returns a campaign id immediately; it never blocks for the campaign's duration.
- `observe`, `artifacts` and `provenance` are ordinary read tools.
- `events` is polled with a cursor, because MCP has no native long-lived stream in this deployment.
- **Job state is persisted to disk**, so a caller reconnecting after its own restart can resume — the
  explicit lesson from ChemGraph's `JobTracker` and its named orphaned-task failure mode.
- The adapter runs on a node with the right network exposure, which on leadership machines is generally not a
  compute node. Where the adapter process runs relative to the job is a **Phase 2 question** and is listed in
  `08`.

## 4. Failure of the caller

An external caller is a dependency, and dependencies disappear. The campaign declares its response at launch:

| Policy | Behaviour on caller timeout |
|---|---|
| `hold` | Checkpoint and idle awaiting reconnection. Safe for state, **wasteful of allocation** — bounded by a maximum hold time |
| `fallback` | Switch to the declared `fallback_policy` (a model-D policy), logged as an explicit state transition |
| `stop` | Checkpoint, terminate cleanly, release the allocation |

`fallback` is the recommended default for long campaigns on scarce allocations; `hold` is appropriate for
short interactive sessions. Whichever is chosen, it is declared up front and recorded in provenance — the
same discipline applied to oracle failure in `02 §3`, for the same reason.
