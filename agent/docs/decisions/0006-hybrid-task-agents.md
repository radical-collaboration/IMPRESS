# 0006 — Task agents are hybrid, declared per tool

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
Task agents own pre-processing, parameterization, execution and post-processing for a tool. They could be
uniformly deterministic, uniformly LLM-driven, or chosen per tool.

## Decision
**Per tool**, declared in `ToolSpec.agent` as `deterministic` or `llm`.

## Consequences
- Cost and determinism stay predictable: most of the toolkit is deterministic.
- LLM agents are reserved for tools whose parameterization is itself authorship — RosettaScripts protocol
  composition, ligand setup, unanticipated failure triage.
- **QC gates are deterministic in both cases.** An LLM may author a protocol; it does not judge whether the
  result passed its clash check.
- `execute()` is not overridable by tool adapters — pattern dispatch belongs to the execution layer.
