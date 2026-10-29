# 0005 — The active control model is fixed at launch

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
Runtime switching between control models would allow escalation (e.g. from an explicit policy to an oracle
when the policy stalls).

## Decision
The control model is named in the campaign specification and **cannot change during the campaign**.

## Consequences
- A campaign has one stated methodology and a result is attributable to it.
- Two declared-up-front mechanisms exist and are not exceptions: `fallback_policy` (a model-D policy
  activated only on oracle or caller unavailability, logged as a state transition) and `RequestHuman`
  (suspends the campaign; does not replace the policy).
- Revisit if campaigns routinely exhaust one policy's usefulness partway through; `fallback_policy` already
  proves a controlled transition is implementable.
