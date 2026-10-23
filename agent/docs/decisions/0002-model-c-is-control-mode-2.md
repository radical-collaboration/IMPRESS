# 0002 — Control model C *is* control mode 2

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
The specification named two control modes (autonomous, headless) and four control models (A: four-node
loop, B: oracle, C: external caller steering, D: explicit policy). Whether these were orthogonal axes was
ambiguous.

## Decision
They are not orthogonal. **Model C is the headless mode.** Autonomous mode runs A, B or D; headless mode
is C.

## Consequences
- Three autonomous policies and one headless mode, rather than eight combinations.
- Model C's `decide` blocks on the control plane instead of computing.
- An external caller is subject to the same validation as any policy — being external confers no privilege.
- HITL is a special case of C: a caller with a person behind it.
