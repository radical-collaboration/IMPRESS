# `fastrelax` passes 58% — the real scientific bottleneck

**Severity:** medium · **Status:** open, needs a human decision on thresholds
**Evidence:** job `22534628`, full 12 h
**Artifacts:** `.../impress-data-after-fixes/smb_8node/small_molecule_binding/`

## The funnel

| stage | pass | total | rate |
|---|---|---|---|
| backbone | 1545 | 1626 | 95.0% |
| sequence | 5035 | 5035 | 100% (gate is similarity, not quality) |
| **fastrelax** | **709** | **1219** | **58.2%** |
| interface | 625 | 709 | 88.2% |
| fold | 576 | 623 | 92.5% |

`fastrelax` rejects **510** attempts and drives **833** escalations to a fresh backbone — by far the
largest source of discarded work in the pipeline. Every other gate passes ≥88%.

## What this costs

A `fastrelax` failure does not just discard that attempt: it either burns an MPNN resequencing cycle
or throws away the backbone entirely and restarts at `STEP_RFD3`. With 833 escalations against 1626
total backbones, **roughly half of all backbones generated were abandoned at this stage**.

The non-improvement short-circuit (CLAUDE.md 2026-09-09) is working as designed — it is what keeps
those 510 failures from each consuming 5 resequencing retries. This item is not a bug report against
that logic; it is the observation that the gate itself is where the science is being lost.

## Current thresholds (PROD)

| kwarg | value | comment in source |
|---|---|---|
| `fastrelax_max_fa_rep` | 100.0 | class default is 150.0 |
| `fastrelax_max_score` | -250.0 | "data range -193 to -510" |
| `fastrelax_max_interact` | -8.0 | "p75 = -8.8" |

`fastrelax_max_interact = -8.0` is set at roughly the 75th percentile of observed interaction
energy, so by construction ~25% of attempts fail that metric alone. `fastrelax_max_score = -250.0`
sits inside a -193…-510 range. Both were tuned on earlier, smaller campaigns.

## What to do next

This needs an analysis pass, not a guess. The failing-metric breakdown is recoverable from the run
log — `adaptive/fastrelax` failure lines carry the full metrics dict, e.g.

```
[adaptive/fastrelax] ... metrics={'pass': False, 'total_score': -537.0, 'interact': -21.8,
                                  'fa_rep': 115.7, 'rmsd': 0.152}
```

Steps:

1. Parse every `adaptive/fastrelax ... passed=False` line from
   `impress_22534628.out` and attribute each failure to which of
   `interact` / `total_score` / `fa_rep` actually breached.
2. Plot each metric's distribution against its threshold. A metric that fails on >50% of attempts
   is mis-set, not selective.
3. Check the joint distribution — a backbone failing all three is a genuinely bad backbone; one
   failing only `fa_rep` by a few REU is probably a threshold artifact.
4. Only then propose new values, and re-run one campaign with the old and new gates to compare
   *downstream* yield (passing folds, high-quality folds), not just the fastrelax pass rate. Loosening
   a gate trivially raises its own pass rate while pushing the failures downstream to `interface`.

## Caution

Do not tune this on the same campaign that validates the serialization fix. Throughput and gate
behaviour must not change together, or neither result is interpretable.
