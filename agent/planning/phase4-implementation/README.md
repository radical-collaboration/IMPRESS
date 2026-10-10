# Phase 4 — Implementation

**Project:** IMPRESS-A · **Status:** skeleton + core + running mock campaign, 2026-09-21.

## What was built

A working reference implementation of the Part B architecture, running complete campaigns
end to end on a laptop with mock tools. **All four control models implemented and passing.**

```
src/impress_a/
  core/      types, artifacts (Property/two-sources), tree, pareto, budget, qc, decision, provenance
  tools/     ToolSpec, registry, shared gate library, task agents, mock agents
  compose/   TaskGraph, composer, five validation gates, self-promoting interlock
  exec/      backend factory, resource normalization, generic DAG dispatcher, job ledger
  policy/    base + A (LangGraph four-node), B (oracle), C (external), D (explicit/replay), wrappers
  control/   transport-agnostic control plane + in-process adapter
  manager.py the outer loop
toolkits/mock/   5 mock tools incl. one that LIES, plus a conforming SKILL.md
campaigns/       mock-stabilize.yaml     sites/  local.yaml     tests/  29 tests
```

## Decisions honoured

| Decision | Implementation |
|---|---|
| LangGraph for the main loop and state | `policy/agentic.py` — `StateGraph` with hypothesize → parameterize; node 3 (run) belongs to the manager, node 4 is `interpret` |
| Academy deferred to a later phase | [`docs/academy-for-task-agents.md`](../academy-for-task-agents.md) — standing notes, with the three properties that keep the door open |
| flowgentic pinned to a commit | `pyproject.toml` extra `agentbridge`, pinned to `dd27bd8b` on `demo/radical` |
| All four control models | A, B, C, D — each runs a campaign to termination in the test suite |
| rhapsody reached by name | `exec/backend.py` resolves via `rhapsody.backends.get_backend()` from site config |

## Verification

```
$ python -m pytest tests -q
29 passed
$ python -m impress_a run campaigns/mock-stabilize.yaml --model D
```

Tests cover: the type lattice as a silent-failure guard, QC-fail exclusion from the front,
all five composition gates rejecting for the right reason, interlock promote/demote,
measurement supersession with prediction retained, non-destructive backtracking, budget
enforcement, external steering through the control plane, post-termination P8 ingestion,
provenance completeness — and **a tool that lies**, which succeeds, reports confident
numbers, and is caught only by its QC gate.

## What the build taught us

Three things reading could not establish. Details in
[`01-integration-notes.md`](01-integration-notes.md).

1. **The central bet is validated.** A DAG described as *data* dispatches to asyncflow with
   one generic factory — no code generation. Phases 2 and 3 both named this the top
   de-risking item; it works on real 0.5.1.
2. **Rhapsody backends must be awaited.** `__await__` performs state registration;
   constructing synchronously fails later with an unrelated-looking error.
3. **Part C's Python floor was wrong** (≥3.12 inherited from foundry, which runs in a
   container). Corrected to ≥3.11 for Dragon, 3.10 for the mock path.

## Bugs the first run exposed

Worth recording, because each was a design error rather than a typo:

- **Replicas collapsed into one candidate.** The composer fanned out at stage 0 then
  funnelled into a single downstream node. Fixed: `replicas` now means N *independent
  lineages*, and the manager creates one `DesignNode` per lineage.
- **Retry decisions were discarded.** `on_rejected` returned a shrunken plan that the loop
  threw away, so a campaign could spend every cycle being rejected and produce nothing.
  Fixed: bounded in-cycle retry (`max_attempts`), with each rejection handed back to the
  policy with its reason.
- **Policies knew `budget` but not `interlock`.** The interlock's cost cap is a distinct
  gate; policies now shrink on both.

## Not built

Real tool adapters (deferred by scope), HTTP+SSE and MCP control-plane adapters
(in-process only), cycle-boundary checkpoint/restart (the ledger and provenance exist; the
resume path does not), and the P5 governor. The T3/T4 test tiers need an allocation.

**Cancellation remains the open risk.** Phase 3 escalated it: no prior art exercises it,
and backtracking depends on it. This implementation backtracks by branching the tree, which
does not require cancelling in-flight work — so the risk is deferred, not resolved.
