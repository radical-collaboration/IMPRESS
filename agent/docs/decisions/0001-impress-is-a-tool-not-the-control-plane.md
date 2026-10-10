# 0001 — IMPRESS is a callable tool, not the control plane

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
IMPRESS is an async adaptive-pipeline framework already wired to `radical.asyncflow.WorkflowEngine` and
`rhapsody.backends.*`, with a working per-pipeline `adaptive_fn` hook and even an LLM-oracle precedent in
`examples/protein_binding/protein_binding_run.py`. It was therefore a plausible candidate to serve as this
project's orchestrator.

## Decision
IMPRESS is a **coarse-grained composite tool (pattern P7)**. We build our own campaign manager directly on
`radical.asyncflow`. `ImpressManager` and `adaptive_fn` are prior art to learn from, not infrastructure to
inherit.

## Consequences
- The agent owns the `WorkflowEngine` and the outer loop.
- IMPRESS pipelines are registered like any other tool; nothing in the registry knows they are special.
- The Python floor conflict (IMPRESS ≥3.9, foundry ≥3.12) dissolves at the process boundary — see 0010.
- The oracle precedent informs control model B's requirements rather than supplying its implementation.
