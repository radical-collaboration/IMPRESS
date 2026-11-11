# 0014 — An enclosing campaign manager is a caller, not a control model

**Date:** 2026-11-10 · **Status:** accepted · **Relates to:** [0001](0001-impress-is-a-tool-not-the-control-plane.md), [0002](0002-model-c-is-control-mode-2.md), [0007](0007-transport-agnostic-control-plane.md)

## Context
IMPRESS-A is meant to be invoked by an agentic caller, and an important class of caller is
orchestrating many heterogeneous workflows toward a higher campaign goal with IMPRESS-A as one
constituent among them. The canonical such superstrate is AuCaM
(`radical-project/campaign_manager`), which launches a workflow as an `async def` taking a
reporter, sizes it from a declared cost, and reads its progress back through `reporter.emit()`.

The tempting reading is that this is control model C — we already have a headless mode, an
external half and a control plane, so an outer manager would be one more external caller. That
reading is wrong, and the distinction is worth a record because every design that follows from
it differs. Model C is a **reasoner** over `CampaignSession`: it publishes Specs, submits
Stages, answers a rejection through `replan`, and is refused by the same six gates as any
policy. An enclosing campaign manager does none of those things. It launches, bounds a budget,
allots resources, pauses, cancels, and reads reports. It has opinions about *whether this
campaign deserves to be running*, and none about which tool runs next.

Two facts fix the shape of the integration. **The caller has no preflight protocol:** AuCaM's
`declared_spending`, `spending_limit` and `resources` are static dicts fixed when the caller
builds its own spec, so nothing can be negotiated at launch. And **the observation already
crosses a process boundary** (`control/http.py:200`), so being told does not need a new
operation — see [`observation.md`](../reference/observation.md).

## Decision
An enclosing campaign manager owns one whole IMPRESS-A campaign as a single subordinate
workflow — launching it, bounding its budget and resources, pausing and cancelling it, and
reading one projected observation per absorbed cycle — and is therefore **not** control model
C: it steers no Spec and plans no Stage, `CampaignControlPlane` gains no operation, and the
preflight handshake is a caller-side function call made before the caller's own spec exists.

Concretely:

- **One invocation is one whole campaign.** Its own cycle loop, its own termination. 0001 is
  untouched: the agent still owns the `WorkflowEngine` and the outer loop, and the executor
  still decides when the campaign has ended, because budget, stagnation and repeated failure
  are facts about state only it holds.
- **The handshake is `impress-a offer`**, a synchronous function of a toolkit and a campaign
  spec with no campaign to address. It is not a plane operation, and 0007 is not in play. It
  reports a cost model and the goal vocabulary the toolkit can address, and it reports its
  **basis**: declared figures sit multiples above measurement on purpose, because they feed
  gates that *refuse* graphs, so an offer states what it is and never passes for a prediction.
- **Being told is a projection, not an operation.** A caller receives a digest of the
  `CampaignObservation` that `observe()` already returns, taken by a pump that reads the
  executor's await-free snapshot API and awaits its sink outside the executor. No `await`
  enters a mutating block, and 0007 stays out of play for the same reason adding a field to
  the observation does (`core/decision.py:127-131`).
- **An enclosing owner gets no privilege over campaign state**, which is 0002's rule extended
  rather than bent. A caller's spending limit arrives as a *budget*: it narrows
  `CampaignSpec.budget`, and is then enforced by `reserve` and gate 5 against the same
  estimate as any policy's. The campaign refuses its own unaffordable graph before a task
  runs, rather than being cancelled from outside after one has.
- **Pause gates admission only.** In-flight runs are allowed to finish, because cancellation
  is advisory and a reclaimed GPU is not something this system can promise. A paused campaign
  therefore keeps spending for up to one cycle, and the offer declares that.

## Consequences
- **An outer manager is told measured cost, not declared.** `BudgetLedger.spent` holds the
  declared figure (`runtime/executor.py:1127`), which is inflated deliberately, so reporting
  it upward would misinform the caller by the full headroom and leave its own learned-cost
  estimate permanently wrong. `ExecutionResults.cost_measured` is already summed per run and
  folded into no ledger; this decision makes aggregating it part of the integration.
- **Our tasks are invisible to the caller's per-task telemetry.** We build our own engine
  through the only sanctioned constructor, and the loop that owns an engine must be the loop
  that uses it — two allocations were lost to learning that (jobs 22328172, 22328262). So
  spending must travel in our own reports. Sharing an engine with an enclosing manager is a
  separate question and is not answered here.
- **Liveness runs outward, not inward.** `control_liveness_timeout_s` cannot protect a
  campaign under an enclosing manager, because `observe()` refreshes the clock it reads
  (`runtime/executor.py:489`) and a pump that polls `observe()` holds it open forever. The
  adapter therefore does not register a control plane — which is also what would arm the
  bound — and relies on the caller's own stale timeout. Recorded as finding 7 of
  [`observation.md`](../reference/observation.md).
- **A second superstrate costs an adapter, not a redesign.** The pump reports to a sink
  protocol that names no AuCaM vocabulary, so an off-process variant — a campaign inside its
  own `sbatch`, reporting over Redis or Dragon — is another adapter over the same seam.
- The MCP adapter 0007 anticipated is still unbuilt, and this decision does not change what it
  would be: submit-and-poll over the same core operations.
