# 0012 — One property, two sources; forward-declare pattern P8

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1 decision round

## Context
Developability surrogates (solubility, expression, aggregation) were added to close a Part A coverage gap,
with the requirement that they be designed so they can later be replaced or supplemented by tools querying
experimental results from a **robotic lab**.

## Decision
A predicted value and a measured value for the same quantity are **the same `Property` type with different
`source`, `authority` and `confidence`** — not two unrelated quantities. Objectives are declared against the
property *name*, never its source.

**Pattern P8 (external experiment)** is added to the taxonomy as a forward declaration: latency of days to
weeks, out-of-band completion, routinely outliving the campaign. Nothing in the current roster is P8.

## Consequences
- A campaign objective is satisfiable by a surrogate today and an assay tomorrow with no spec change.
- Measurements supersede predictions for ranking; the prediction is retained, because a systematic
  surrogate-versus-assay gap is itself the calibration signal.
- The Pareto front is **not monotonic** — a node promoted on an optimistic prediction can be demoted by its
  own assay.
- `ingest_measurement` is added to the control plane; measurements are accepted even after campaign
  termination, which is why campaign storage is append-only on a shared filesystem.
- **Not** a closed design–build–test–learn loop: nothing here selects designs for assay or manages samples.
