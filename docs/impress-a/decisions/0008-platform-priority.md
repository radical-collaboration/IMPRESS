# 0008 — Platform priority: Polaris/ACCESS primary, Aurora second, Frontier deprioritized

**Date:** 2026-09-21 · **Status:** accepted · **Phase:** 1 decision round

## Context
Part A targeted DOE leadership and NSF ACCESS machines, then found the portability picture inverted from
expectation. A repo-wide grep of `tools/foundry` for `hip`/`rocm`/`amd` returned **zero hits** — no code
path, no CI, no documentation — making Frontier a from-source porting spike rather than a rebuild. Aurora,
by contrast, has real first-party Intel XPU support in foundry.

## Decision
**Polaris and NSF ACCESS (Delta, Bridges-2, Expanse) are primary. Aurora is second. Frontier is
deprioritized** and no HIP spike is scheduled.

## Consequences
- `frontier` stays in the site matrix with `gpu.api: hip`, so the compose-time portability gate **refuses**
  the ML core there rather than failing at runtime — the door stays visible and shut.
- `containers/frontier/` is not created.
- If revisited: ProteinMPNN first (no cuEquivariance dependency), then RFD3 (cuEquivariance import already
  wrapped in `try/except` with a PyTorch fallback), RF3 last (hard CUDA-12 kernel dependency).
- Part A's risk R1 is accepted and scoped out rather than mitigated.
