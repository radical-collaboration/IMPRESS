# 0010 — One repository, one package, with a CI-enforced import contract

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1C

## Context
Part B's layers have different change rates and audiences. A multi-package workspace would isolate
dependencies — but heavy scientific tools are invoked as subprocesses or containers, not imported, so that
isolation already exists.

## Decision
A **single package** `impress_a`, with layering enforced by an import-linter rule in CI rather than by
directory convention.

Load-bearing rules: `policy ↛ tools`, `policy ↛ exec`, `compose ↛ exec`, `core` imports nothing internal.

## Consequences
- `policy ↛ tools` is what keeps control models interchangeable: policies emit abstract `ExperimentIntent`
  and cannot reach for a tool adapter.
- `compose ↛ exec` is what makes the laptop-runnable mock campaign possible.
- The only in-process scientific dependencies are the P6 tools (RDKit, Biotite, AtomWorks, US-align,
  `paretoset`), which must be co-installable with `radical.*` on Python ≥3.12.
- Revisit if policies pull in both LangGraph and Academy, or if a site needs the execution layer without the
  policy layer. Splitting later is more disruptive than starting split.
