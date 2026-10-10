# 0007 — One transport-agnostic control plane, with adapters

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1B

## Context
Headless mode must serve pipelining-as-a-service, MCP-like exposure, and an in-process HITL agent. Part A
surveyed 26 MCP entries and verified 2; every tool running real HPC computation was absent or wrapped only
by unaudited third parties.

## Decision
Define **one core `CampaignControlPlane` protocol**; MCP, HTTP+SSE and in-process are thin adapters over it.
No adapter may add an operation absent from the core.

## Consequences
- `observe()` returns the **same `CampaignObservation`** a policy's `decide` receives — informed monitoring
  means parity of evidence, not a progress bar.
- MCP exposure is necessarily submit-and-poll, a property of long-running compute rather than of MCP.
- The project is not hostage to MCP protocol revisions.
- Measurement ingestion later lands naturally on the same plane (0012).
