# Observation: what a caller is told, and when

[`resolution.md`](resolution.md) runs one direction — **toolkit, goal, budget and parameters**
become specified targets and a programmed Stage. This page runs the other: how the state of a
running campaign becomes a **`CampaignObservation`**, who is shown it, what of it survives to
disk, and by what mechanism any of it reaches a caller outside this process.

Every step says what it takes, who owns it, what it produces and what refuses it, in the
order a cycle executes them. Anything true of how a decision is *made* from an observation is
in [`control-models.md`](control-models.md) and is not repeated here. If this page and the
code disagree, the code is right and this page is a bug.

Two things to read it for. **Wiring IMPRESS-A beneath an enclosing campaign manager**, which
needs to know the cadence, the shape and the cost of being told — see
[decision 0014](../decisions/0014-an-enclosing-campaign-manager-is-not-a-control-model.md).
And **changing any of this safely**, for which the thing to preserve is named in each step:
the observation is assembled inside a window where the executor is not mutating anything, and
almost every rule below exists to keep that window shut.

```
   absorb a run ────────────────────────────────────────────────  step 1
        │  await-free: tree, ledger, provenance, _absorbed
        ▼
   observe()  ──→  CampaignObservation  ─────────────────────────  step 2
        │             (built fresh, never stored)
        ├──→  the reasoner's two halves, in-process  ────────────  step 3
        ├──→  prov_sink  ──→  the plane's event list  ───────────  steps 4, 5
        └──→  GET /observe?since=  ──→  another process  ────────  step 6
                  │
   provenance/*.jsonl, jobs/*.jsonl  ─────────────────────────────  step 7
                  │
   what a caller must do today  ──────────────────────────────────  step 8
```

---

## Step 1 — a run is absorbed, and the window is shut

**In:** `ExecutionResults` from the backend. **Owner:** `runtime/executor._absorb:522`.
**Out:** `DesignNode`s on the tree, one `results` provenance record each, and one id appended
to `_absorbed` per lineage (`:558`).

**The executor is the only writer of campaign state, and every mutating block is free of
`await`.** Its own module docstring (`runtime/executor.py:1-16`) states the rule and the
reason: *"adding an `await` inside `observe` or `_absorb` would reintroduce torn reads, and
they are nearly impossible to diagnose from provenance afterwards."* That property is a
discipline, not something the language enforces, and it is the single constraint that shapes
everything below — **an observation cannot be pushed anywhere from inside the code that
produces the state it describes.** A sink that must be awaited cannot be called here.

`_absorbed` (`:309`) is an append-only list of node ids in absorption order, and `_cursor`
(`:310`) is how far the last consumer read. Those two integers are the whole of the
campaign's notion of "what is new", and step 2 is where they are read.

## Step 2 — `observe()` assembles the snapshot

**In:** the executor's own state, plus an optional `since` watermark. **Owner:**
`runtime/executor.observe:484`. **Out:** a `CampaignObservation`
(`core/decision.py:75`).

Synchronous, read-only, and **the only place in the package that constructs one**. It
computes the Pareto front over live nodes, builds `PopulationStats` (`core/decision.py:66`)
inline, and reads `recent` out of `_absorbed[cursor:]` (`:506`) with `seq = len(_absorbed)`
(`:507`).

`since` is the one subtle parameter. Omitted, it reports from `_cursor` — what the last
consumer saw. Given, it reports from that watermark instead, **without moving the cursor**,
so an observer can read the same evidence a policy is about to read without disturbing it.
The docstring calls this parity of evidence, and [ADR 0007](../decisions/0007-transport-agnostic-control-plane.md)
makes it binding rather than incidental.

Two declared fields are never populated by this method: `failures` (`core/decision.py:87`)
and `PopulationStats.diversity` (`:71`). And one thing a reader would expect is absent — the
**parameter values a planner chose**. Those reach `stages` provenance under `mappings`
(`runtime/executor.py:962`, written at `:976`) and nowhere else, so an observation says what
a campaign found and not what it tried.

## Step 3 — the two halves are shown it, whole

**In:** the observation. **Owner:** `runtime/roles.py:86` (`obs = await session.observe()`,
once at the top of every turn). **Out:** `SpecEvidence` (`policy/specifier.py:36`) and
`PlanningContext` (`policy/planner.py:37`).

Both wrappers **hold** the observation rather than summarising it — `SpecEvidence`'s own
docstring says `observation` *is* the object `observe()` returned, not a digest of it. So
there is exactly one description of campaign state in the system, and a reasoner, an external
caller and a test all read the same fields. That is what makes the control models comparable:
a difference in their behaviour is a difference in judgement, not in what they were told.

**What refuses a second shape here:** nothing mechanical. The discipline is the import
contract — `policy` may import `core` and nothing else (`tests/test_layering.py`), so a half
cannot reach the executor to ask a narrower question.

## Step 4 — provenance is mirrored to one slot

**In:** every provenance record. **Owner:** `runtime/executor._log:313`. **Out:** a write to
`provenance/<kind>.jsonl`, then a call to `prov_sink` if one is set.

```python
def _log(self, kind: str, record: dict[str, Any]) -> None:
    self.prov.append(kind, record)
    if self.prov_sink is not None:
        self.prov_sink(self.spec.campaign_id, kind, dict(record))
```

This is **the only hook out of a running campaign**, and it is one slot, not a list. It is
synchronous, so a sink that must await cannot be one; and it is unguarded, so a sink that
raises takes the campaign down with it — unlike the reasoner's sink, which catches
(`policy/reasoning.py:175`). Two call sites assign it and neither checks for the other:
`control/plane.py:104` and `cli/__init__.py:887`. Last writer wins, silently (finding 3).

## Step 5 — the event stream is that mirror, kept in memory

**In:** `prov_sink` calls. **Owner:** `control/plane.InProcessControlPlane.emit:112`, into
`self._events` (`:94`). **Out:** `events()` (`:143`), by cursor page or as a tail.

`_events` is a `dict[str, list[Event]]` in the serving process. It is unbounded, never
persisted and lost when the process exits. `events(stream=True)` polls its own list every
50 ms, and the SSE layer polls that at 100 ms (`control/http.py:151`). The method's own
docstring is honest about it: it polls *"because provenance is appended to rather than
published. A push-based source would replace the body of this loop and nothing else."*

**What refuses an addition here:** ADR 0007 — *no adapter may add an operation absent from
the core protocol.* A new way to be told would be a change to `CampaignControlPlane`, not an
adapter's business.

## Step 6 — the observation crosses a process boundary intact

**In:** `GET /campaigns/<cid>/observe?since=`. **Owner:** `control/http.py:200` server side,
`ControlPlaneClient.observe:304` client side. **Out:** the same `CampaignObservation`, rebuilt
from `model_dump(mode="json")`.

This already works and is exercised end to end. It is the only machine-readable, serialisable
description of campaign state the system has, and anything that wants to tell a caller
something should start from it rather than invent a second vocabulary.

Its cost is the other half of the fact. The payload embeds the whole `ToolkitView` — every
`TaskCard`, and **each toolkit's full `SKILL.md` text** (`tools/view.view_of:67`) — plus
the applied `Spec` and every `DesignNode` on the front, rebuilt on every call, with no
projection and no field selector. `ToolkitView.skills` is read by no prompt and no consumer
(`resolution.md` finding 6), so the largest part of what crosses the wire is read by nothing
at either end.

## Step 7 — what is actually durable

**In:** records from `_log` and the two ledgers. **Owner:** `core/provenance.append:24`,
`exec/ledger.py`, `exec/task_ledger.py`. **Out:** append-only JSONL under the campaign root.

| file | holds |
|---|---|
| `provenance/campaign.jsonl` | the spec, goal, objectives and budget, once at start |
| `provenance/specs.jsonl` | each Spec generation and its rationale |
| `provenance/graphs.jsonl` | each composed graph, its signature, trust and estimate |
| `provenance/stages.jsonl` | the deployed Stage — **the only record of chosen parameters** |
| `provenance/executions.jsonl` | settlement and run-finished events |
| `provenance/results.jsonl` | one row per absorbed node: QC verdict, failed gates, metrics |
| `provenance/tasks.jsonl` | per task, including `cost_estimated` and `cost_measured` |
| `provenance/decisions.jsonl` | the reasoner's transcript |
| `provenance/transitions.jsonl` | promotions, demotions, stops, losses |
| `jobs/ledger.jsonl`, `jobs/tasks.jsonl` | run and task state, folded on read |

`append` opens, writes and closes per record, so a record is durable when the call returns.
The log is truth; checkpoints are an index.

**There is no `observations.jsonl`.** An observation is computed on demand and discarded, so
cycle N's view of the campaign cannot be read back — it has to be re-derived from `graphs`,
`results`, `executions` and `specs`. Nothing today needs to replay one, which is why this is
recorded as a property rather than fixed.

## Step 8 — so what must a caller do today

**In:** a wish to be told. **Out:** one of three unsatisfying options.

| option | how | what it costs |
|---|---|---|
| Assign `prov_sink` | `mgr.prov_sink = fn`, as `cli/__init__.py:887` does for the log heartbeat | one slot, synchronous, unguarded; the caller must reconstruct cycles from provenance records |
| Run `impress-a serve` and poll | `serve_campaign:459`, then `GET /observe` | a second process and a socket, and the whole `ToolkitView` on every poll |
| Hold the manager and schedule a task | `mgr.observe()` through the `_DELEGATED` allowlist (`manager.py:46`) | the caller must write the pump, and nothing tells it when something landed |

The third is the one that works, and the precedent for it is already in the tree.
`cli._heartbeat:755` does exactly this for logging, and its docstring states the licence:
*"Reads only the executor's synchronous snapshot API. Its mutating blocks are await-free by
invariant, so a heartbeat scheduled between them can never see a torn state."* A pump that
awaits a sink **outside** the executor is a heartbeat with a sink instead of a logger, and it
needs nothing added to the executor at all.

---

## What the observation plane does not enforce

Eleven places where the implementation does not do what a reader of the design would
reasonably assume. Each is verified against the source at the anchor given. **Read this
section before changing any step above.**

| # | the reasonable assumption | what the code does | anchor | item |
|---|---|---|---|---|
| 1 | An observation reports what went wrong, and how diverse the population is | `failures` and `PopulationStats.diversity` are **declared and never populated** by the only method that builds one | `core/decision.py:87,71`, `runtime/executor.py:493-519` | G |
| 2 | A campaign's own view of itself at cycle N can be read back | **No observation is ever persisted.** Nine provenance kinds, none of them observations; cycle N's view must be re-derived from four other files | `core/provenance.py:22`, `runtime/executor.py:484` | G |
| 3 | A campaign can be watched by more than one listener | `prov_sink` is **one slot, synchronous and unguarded**. `control/plane.py:104` and `cli/__init__.py:887` both assign it, last writer wins, so attaching a monitor silently evicts the log heartbeat — and a sink that raises stops the campaign, where the reasoner's sink catches | `runtime/executor.py:313-321`, `policy/reasoning.py:175` | G |
| 4 | The event stream is a stream | `_events` is an unbounded in-memory list, never persisted, lost on exit; "streaming" is a 50 ms poll of that list with a 100 ms poll on top | `control/plane.py:94,160-167`, `control/http.py:151` | G |
| 5 | An observation says what the campaign tried, not only what it found | **Chosen parameter values are absent.** They reach `stages` provenance under `mappings` and no observation field, so a caller sees scores without the knobs that produced them | `runtime/executor.py:962,976` | G, and `resolution.md` finding 7's neighbour |
| 6 | The payload carries what its consumers read | It embeds every `TaskCard` **and each toolkit's whole `SKILL.md`**, plus the applied `Spec` and the full front, rebuilt per call with no projection — and `ToolkitView.skills` is read by nothing at either end | `tools/view.py:67`, `runtime/executor.py:490-519` | G |
| 7 | Watching a campaign is free of consequence | **`observe()` refreshes the liveness clock.** `touch()` sets `_last_contact`, and `_control_lost_for` is what drains and stops a campaign whose caller vanished. The coupling is deliberate — the Listener polls `observe()` every cycle, so no heartbeat operation was added — but the consequence is that a **purely passive observer keeps drain-and-stop from ever firing**, which is exactly the shape of a caller that watches without steering | `runtime/executor.py:489,448-455,458-482` | G |
| 8 | Spending reported to a caller is spending | `BudgetLedger.spent` is **declared cost, not measured**: `_settle` settles `results.cost`, documented *"DECLARED, summed - unchanged on purpose"*. Declared figures sit multiples above measurement deliberately, because they feed gates that *refuse* graphs. `cost_measured` is summed per run already and folded into no ledger, so **an outer manager told our spend is told the inflated figure**, and can never learn a truer one | `runtime/executor.py:1127`, `exec/dispatch.py:34-38` | E2, A11 |
| 9 | A `TaskCard` carries the cost terms its spec declares | `tools/view.py:46-48` passes `burn_rate=` and `max_commitment=` to a model that **declares neither field**, and pydantic's default `extra` is `ignore`, so both are silently discarded. `core/budget.py:67` documents the rule `min(goal.budget[d], card.max_commitment[d])` against a field that cannot exist | `tools/view.py:46-48`, `core/toolkit.py:59-78` | D1, realised in our own code rather than in a user's YAML |
| 10 | A caller can project a burn-down from what it is told | There is no rate. `BudgetLedger` is constructed without `walltime=`, so `burn_rate()` returns empty permanently and `project()` is inert. Limits, spent and holds cross; a rate does not | `runtime/executor.py:230`, `core/budget.py:160,172` | E |
| 11 | The chain that runs is the chain the campaign declared | `_admit_once` composes against the **whole `Registry`** and reports `available: self.reg.ids()`; nothing restricts a submitted Stage to `spec.stages`. The bound holds by construction for the shipped planners, whose `ToolkitView` is narrowed — it is not a gate, and anything pricing a campaign from `stages` is relying on that | `runtime/executor.py:617-638`, `tools/view.py:55` | G, and `resolution.md`'s *"available means three different things"* |

One asymmetry that is **by design** and is listed so it is not mistaken for the above. Gate 1
does not check that a required root port was satisfied — the loop is a literal `pass`
commented *"roots may be satisfied from campaign inputs"* (`compose/validate.py:81`) — because
input data arrives through `params:` rather than as typed reference data. That is
`resolution.md` finding 1, and it belongs to resolution rather than to observation; it appears
here only because a caller reading `unsatisfied_root_ports` off an offer is reading a
computation, not a gate.

---

## Seeing it on disk

Every step's output except step 2's is in provenance, which is the only way to check this
page rather than trust it. `impress-a mock-lab --only arms --stage sweep` writes one campaign
per arm in about half a minute with no allocation.

| step | where it landed |
|---|---|
| 1 | `provenance/results.jsonl` — one row per absorbed node |
| 2 | **nowhere** — finding 2 |
| 3 | `provenance/decisions.jsonl` — what each half was asked and answered |
| 4, 5 | `provenance/*.jsonl` is the record; the event list is memory only |
| 6 | the campaign's `control_plane.url`, written `0600` under `serve` |
| 7 | the table in step 7 |
| 8 | the `heartbeat +…` lines in a run log, which is step 8's third option already working |

A step whose output cannot be pointed at in one of those files is a step this page has
described wrongly — step 2 included, and that is finding 2 rather than an exception.
