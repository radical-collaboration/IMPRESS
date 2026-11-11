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
- `policy ↛ tools` is what keeps control models interchangeable: a reasoner emits **abstract intent**
  and cannot reach for a tool adapter.

  **Amended 2026-11-08 (phase 11).** That intent was `ExperimentIntent`, returned from
  `decide(obs) -> Decision`. Both are gone: a reasoner is now a **Specifier** emitting a
  `SpecRevision` and a **Planner** emitting a `Stage` of `TaskMapping`s, and the Stage is what
  "abstract intent" names. The rule is unchanged and the reason is unchanged — a `TaskMapping`
  carries a tool id, declared parameters and typed port references, never an adapter, a command
  line or a resource shape.

  `ExperimentIntent` itself **survives, deliberately, as a composer input** rather than as
  anything a reasoner returns. `Composer.compose` takes a chain and a replica width, which is
  what two non-policy callers need: `impress-a trust --assert` computes a pattern signature at
  a declared width (and the signature includes replica multiplicity, so the width is not
  optional), and `impress-a validate-tasks` runs a chain once to prove each Task on real
  hardware. Neither is a decision about a campaign, so neither needs a Planner — and inventing
  one for them would mean a validation pass whose result depended on which reasoner validated
  it. `tests/test_layering.py::test_the_decision_union_is_gone_and_nothing_imports_it` pins
  both halves of this: the union is gone, and that one type is not.

- **A new layer, `analysis`, with one rule of its own:** it may not import `policy` or `control`.
  A scorer that could reach a reasoner could score a campaign by asking it, and the whole method
  of the four-arm comparison is that figures come from the executor's own provenance, the ledgers
  and the artifacts on disk — never from an arm's bookkeeping.
- `compose ↛ exec` is what makes the laptop-runnable mock campaign possible.
- The only in-process scientific dependencies are the P6 tools (RDKit, Biotite, AtomWorks, US-align,
  `paretoset`), which must be co-installable with `radical.*` on Python ≥3.12.
- Revisit if policies pull in both LangGraph and Academy, or if a site needs the execution layer without the
  policy layer. Splitting later is more disruptive than starting split.
