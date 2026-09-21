# Phase 2 — Middleware Exploration

**Project:** IMPRESS-A — autonomous protein design on HPC
**Status:** complete, 2026-09-21. Builds on [Phase 1](../). Input to Phase 4 (implementation).

## Reading order

| # | Document | Covers |
|---|---|---|
| — | [`_CONTEXT.md`](_CONTEXT.md) | The shared brief every explorer worked from |
| 1 | [`01-asyncflow.md`](01-asyncflow.md) | `radical.asyncflow` v0.5.1 — the execution/DAG layer |
| 2 | [`02-flowgentic.md`](02-flowgentic.md) | `flowgentic` v0.1.0 — LangGraph↔asyncflow bridge |
| 3 | [`03-radical-adr.md`](03-radical-adr.md) | `radical.adr` v0.1.0 — Autonomous Decision Runtime |
| 4 | [`04-rhapsody-radex-orbit.md`](04-rhapsody-radex-orbit.md) | Substrate, data exchange, brokerage |
| 5 | **[`05-integration-map.md`](05-integration-map.md)** | **Start here for conclusions.** Hypothesis verdict, the stack, M1–M7 resolved, risks |

## The hypothesis, tested

> Task execution via asyncflow; agent tasks via flowgentic; autonomous encapsulation with swappable
> policies via ADR; rhapsody not called directly.

| Leg | Verdict |
|---|---|
| asyncflow for task execution | ✅ **Confirmed** — and it genuinely supports runtime-composed DAGs, which was the central bet |
| rhapsody only via asyncflow | ❌ **Refuted for backends** (direct import required; mitigable via its registry), ✅ true for telemetry |
| flowgentic for agent tasks | ⚠️ **Partial** — serves LLM tool execution, not control policies; too immature to depend on |
| ADR for swappable policies | ⚠️ **Half right** — real policy abstraction, but its `Operator.run()` conflicts with our outer loop |

**Missed by the hypothesis:** ORBIT holds the only PBS Pro support, the only external-batch-job path
(PSI/J), and a firewall-traversing control-plane transport — three things Part B had listed as unresolved
or self-build. It moves from "reference material" to candidate dependency.

## Headline conclusions

1. **The core bet paid off.** asyncflow expresses dependencies as unawaited futures passed as arguments,
   resolved by a ready-queue scheduler — not as `await` chains in source. A runtime-composed typed DAG
   needs one generic dispatch loop, no code generation. This was the riskiest assumption in Part B.
2. **Adopt two, mine two, evaluate one.** Adopt asyncflow and rhapsody. Mine flowgentic (one ~40-line
   pattern) and ADR (policy-interface shape, `Goal` predicates, replay observer). Evaluate ORBIT.
3. **Own the outer loop.** ADR's `Operator.run()` is a complete cycle that would force our five gates,
   dry-run and interlock into `@act` bodies. Our loop carries the governance; it stays ours.
4. **Eight things we build ourselves** — durable P4 ledger, resource normalization, cycle/lineage
   bookkeeping, P5 governor, retry, the governance layer, the policy and state model, QC gates. All are
   deliberately out of scope upstream, not gaps awaiting a release.
5. **Maturity is the dominant risk.** Two components at 0.1.0 with documented-but-absent features, one
   undeclared dependency edge, one unmerged branch in a dependency's dependency.

## Method and its limits

Four agents explored in parallel against a shared context brief. All four were terminated by a session
limit; three had written their reports, so only `04` was lost and was rewritten directly by the
orchestrator from the same refcodes — at **lower depth**, and its ORBIT maturity assessment
(`ROADMAP.md`, `plans/`, tests) was **not completed**. Since ORBIT is the component whose adoption case is
strongest, that gap is the most consequential limitation of this phase and is the first item in the Phase 4
list.

Every claim cites a resolvable path; verified-from-source is distinguished from inferred throughout.
