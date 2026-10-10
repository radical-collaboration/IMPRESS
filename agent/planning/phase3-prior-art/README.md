# Phase 3 — Prior Art Review

**Project:** IMPRESS-A — autonomous protein design on HPC
**Status:** complete, 2026-09-21. Input to Phase 4 (implementation).

Three prior attempts at related work on the asyncflow/rhapsody stack, reviewed for transferable patterns.

## Reading order

| # | Document | Target |
|---|---|---|
| — | [`_CONTEXT.md`](_CONTEXT.md) | The shared brief every reviewer worked from |
| 1 | [`01-flowgentic-ai-hpc-coupling.md`](01-flowgentic-ai-hpc-coupling.md) | `flowgentic@origin/demo/radical:examples/ai-hpc-coupling` |
| 2 | [`02-campaign-manager-small-molecule-binding.md`](02-campaign-manager-small-molecule-binding.md) | `campaign_manager@origin/new_cm:campaigns/small_molecule_binding` |
| 3 | [`03-adr-prototype-examples.md`](03-adr-prototype-examples.md) | `radical.adr@feature/prototype:examples/` (11 examples) |
| 4 | **[`04-patterns-for-phase4.md`](04-patterns-for-phase4.md)** | **Start here for conclusions.** Pattern catalogue, adopt/adapt/avoid |

All three were read without checking out any branch — `git show` / `git ls-tree` only. Reference repos
were left untouched.

## The three findings that matter

**1. The loop-ownership question is resolved, and Phase 2's verdict is revised.**
Two reviews looked contradictory: ADR's own 11 examples all cede the outer loop to `Operator.run()`, while
campaign_manager runs it *under* its own loop. Both are true — ADR's intended usage cedes the loop, and a
downstream consumer found a way not to. The mechanism is that **`Operator.run()` is an async generator**:
`async for _snapshot in operator.run()` inside `asyncio.ensure_future(_drive())`, so the caller owns the
pump. Phase 2's "ADR owns the loop" was right about intent, overstated about mechanism.

Revised recommendation: **use ADR's `Policy` base class, skip `Operator` entirely.** campaign_manager's own
`sm_binding_operator.py` does exactly that — subclassing `radical.adr.policy.base.Policy` with
`@decide async def run(obs) -> Decision`.

**2. `campaign_manager@new_cm:src/campaign/adr/` is the best reference implementation in the whole refcode
set** — a narrow `CampaignViewProtocol` observation seam, a policy library (rule, bandit, LLM, ensemble),
composable policy decorators, a recorder, telemetry, and the supervisor. It is effectively a worked version
of Part B's policy layer. Phase 4 should read it in full before writing ours.

**3. Nobody has built the part we are building.** Across all three attempts there is **no runtime DAG
composition, no real data-driven adaptivity, no durable restart, no governance gates, and no demonstrated
control model A or C.** campaign_manager's operator is explicitly *"a dummy policy… future versions will
generate varied inputs based on completed pipeline scores."* The prior art is strong on plumbing and policy
shape and empty on exactly the territory Parts B and C occupy.

That is reassuring about non-redundancy and sobering about precedent: our highest-risk choices have none.

## Risk escalated

**M4 (cancellation) moves from open question to active risk.** No example in any of the three codebases
calls `cancel_task`/`cancel_operator`, and example 05 — named "spawn-block" — demonstrates *zero*
cancellation. Our backtracking design depends on it. Spike it against released asyncflow before committing.

## Chronology

`radical.adr` examples (Jun) → flowgentic demo (Aug) → campaign_manager (Sep). The progression is legible:
ADR's examples cede the loop, the flowgentic demo works around ceding it, campaign_manager solves it.
Where the three disagree, weight the newest.

Note also that flowgentic's `demo/radical` is **seven months newer** than its `main`, which is what Phase 2
assessed — a caveat on Phase 2's flowgentic findings.
