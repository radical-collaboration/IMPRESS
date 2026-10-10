# 0004 — Campaign state is a population with a Pareto front and backtracking

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
Alternatives were a single refined lineage (as in the IMPRESS precedent) or a population ranked by a
scalarized score.

## Decision
A **non-destructive tree of design lineages**, ranked by a **multi-objective Pareto front**, with
backtracking to any earlier node.

## Consequences
- Objectives are declared with directions and hard constraints; constraints prune, directions rank.
- Cost is a first-class objective, not an afterthought — Part A found a seven-order-of-magnitude spread.
- QC verdict gates front eligibility: a node failing its gates never ranks, whatever its scores.
- Append-only storage; backtracking never destroys the abandoned branch.
- Adopts AgentRosetta's proven pattern; `paretoset` is a directly adoptable dependency.
- The front is **not monotonic** once measurements arrive (see 0012).
