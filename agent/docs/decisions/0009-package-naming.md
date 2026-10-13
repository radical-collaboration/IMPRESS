# 0009 — Package naming: `impress_a`

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1C

## Context
The working name `impressa` sat one character from `impress`, while
`impress-a-refcodes/tools/IMPRESS` exists in the same workspace.

## Decision

| Role | Name |
|---|---|
| Human-facing project name | **IMPRESS-A** |
| Distribution | **`impress-a`** |
| Import package | **`impress_a`** |
| Environment variables | `IMPRESS_A_SHARED`, `IMPRESS_A_CAMPAIGNS`, `IMPRESS_A_TOOLKITS` |

## Consequences
- The underscore supplies the visual break `impressa` lacked. The hazard applied to human readers and more
  acutely to LLM agents working in this tree, where the two names are plausible completions of each other.
- `impress_a` is the idiomatic Python spelling (PEP 8); uppercase is reserved for prose and env vars.
