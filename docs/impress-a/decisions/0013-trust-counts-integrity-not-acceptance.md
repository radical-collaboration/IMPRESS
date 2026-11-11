# 0013 — Trust counts integrity, not acceptance

**Date:** 2026-10-07 · **Status:** accepted · **Amends:** [0003](0003-free-graph-composition-with-self-promoting-interlock.md)'s "clean run"

## Context
0003 promotes a composition pattern after N consecutive *clean* runs, and until now a clean run meant
every QC gate passed. On Delta that made promotion unreachable for reasons unrelated to the pattern.
Job 22702568 ran the six-stage chain five times, and all 30 tasks succeeded. The ledger nevertheless
recorded `failure, clean, failure, failure, clean`, so nothing was promoted. Every one of those
failures was a design-quality threshold:
- Boltz pLDDT 0.486 and 0.426 against 0.5;
- ipTM 0.327 against 0.4;
- LigandMPNN confidence 0.355 against 0.4;
- shape complementarity 0.519 against 0.55.

None was a tool breaking. Promotion had become a function of how hard the target is. At the observed
~43% all-gates rate, a 6-cycle campaign had a ~17% chance of ever admitting a trusted graph.

The interlock asks whether a novel composition *behaves*: whether its tools ran, produced output
and reported numbers that mean what they say. Whether the resulting design is good is a separate
question, answered by the QC verdict and the Pareto front.

## Decision
Each QC gate declares a `role` in its tool spec:
- **`integrity`** (the default): a FAIL means the tool or the pipeline broke. Examples are
  `output_present`, `has_secondary_structure`, `metrics_reported`, and the Rosetta divergence bounds.
- **`acceptance`**: a FAIL means the tool worked and the design fell short. These are the quality
  thresholds on self-reported confidence and on shape complementarity.

**Only integrity failures are evidence against a pattern.** A run is clean when no task failed and
no integrity gate failed (`runtime/executor._record_evidence`). Acceptance gates still FAIL the node,
and a FAIL node is still never eligible for the front; that invariant is untouched.

Classifying the gates surfaced a hazard. Two known-bad fixtures were caught **only** by thresholds
that would have become acceptance gates, and both recorded a run breaking, not a weak design:
- Boltz run with no ligand chain, where the adapter fell back to `iptm` and then to 0.0;
- an unparsed LigandMPNN header, where the adapter reported 0.0/0.0.

In both cases the adapter fabricated a number for a value it never read. So:
- adapters omit a value they cannot read, and never report 0.0 in its place;
- a new integrity gate, `metrics_reported`, fails when a named metric is absent or non-finite;
- `ToolSpec` validation refuses an acceptance `metric_in_range` whose metric no integrity
  `metrics_reported` gate names, so the presence check cannot be forgotten;
- every `.bad.json` fixture must fail an integrity gate unless it declares `acceptance_only: true`.

## Consequences
- Promotion is reachable on hard targets. Replaying 22702568's recorded per-task metrics through the
  new rule promotes at its third run (`tests/test_validation.py`).
- **Trust now rests on the integrity gates, and they are thin** (backlog B1: no structural gates).
  A tool emitting *well-formed, confidently-scored garbage* could already promote under 0003. Now
  one emitting *well-formed, low-scored garbage* can too, as long as it reports its numbers.
- The policies' own notion of a good run (`ExecutionResults.all_gates_passed`, used by
  `policy/explicit.py` and `policy/agentic.py`) still counts every gate. Search quality and
  pattern trust are different questions, and each uses its own answer.
- Provenance records each node's `failed_gates`, with their roles, and each admission's scrutiny.
  A run that resets trust now says why.
