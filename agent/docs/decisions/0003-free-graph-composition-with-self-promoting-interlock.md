# 0003 — Free graph composition, governed by a self-promoting interlock

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B (revised in the Part C decision round)

## Context
"Autonomous" was defined as workflow parameters modified at runtime. Three scopes were considered:
parameters only, parameters plus bounded topology, and free graph composition. Free composition offers the
most scientific reach and is the hardest to validate — and Part A found that silent failure, not crashing,
is the dominant hazard across the entire toolkit.

## Decision
**Free graph composition**, with a five-gate validation regime plus dry-run, and a **self-promoting
interlock** as the standing operating posture.

The interlock was chosen over two alternatives. A *temporary* allowlist switched off once validation proves
itself merely postpones the risk. *Permanent per-pattern human sign-off* eliminates it but caps the agent at
reviewed patterns, forfeiting the reason free composition was chosen.

## Consequences
- Composition patterns (tool ids plus typed edges, ignoring parameter values) are trusted or provisional.
- Provisional patterns run under a cost cap, an extended mandatory dry-run, required cross-tool consistency,
  and are auto-marked `suspect` regardless of QC outcome.
- Promotion after N consecutive clean runs; demotion on any failure. Per-pattern, per-site, in provenance.
- The trust ledger is site-scoped and spans campaigns, since one campaign may not run a pattern three times.
- **Residual risk accepted:** a *consistent* novel silent failure will promote. The interlock buys
  examination and delay, not soundness.
