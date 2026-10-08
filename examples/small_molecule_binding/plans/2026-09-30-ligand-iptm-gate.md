# `fold_min_ligand_iptm` is disabled — data supports turning it on

**Severity:** low · **Status:** open, needs a human decision on the threshold
**Evidence:** job `22534628`, 624 Boltz co-folds
**Artifacts:** `.../impress-data-after-fixes/smb_8node/small_molecule_binding/logs/22534628/`

## Context

`PROD` in `run_small_molecule_binding.py` sets `fold_min_ligand_iptm = None`, which disables the
gate. `ligand_iptm` is Boltz-2's protein–ligand *interface* confidence — a capability plain
AlphaFold2 never had, since it did not fold the ligand at all. Right now the fold stage gates on
`complex_plddt` only, which is a whole-complex confidence and can look good while the interface
itself is poorly resolved.

## Data (624 folds, full 12 h run)

| metric | min | p25 | med | p75 | max | mean |
|---|---|---|---|---|---|---|
| `complex_plddt` (×100) | 45.8 | 87.6 | **93.3** | 95.9 | 98.1 | 90.1 |
| `ligand_iptm` | 0.257 | 0.809 | **0.870** | 0.925 | 0.982 | 0.853 |

Cumulative pass fractions:

| `ligand_iptm` ≥ | folds | share |
|---|---|---|
| 0.7 | 581 / 624 | **93.1%** |
| 0.8 | 486 / 624 | 77.9% |
| 0.9 | 216 / 624 | 34.6% |

For reference the current pLDDT gate (`fold_min_plddt = 75.0`) passes 577 / 624 = 92.5%.

## Why this is worth doing

62.8% of folds (392 / 624, spread across 31 of 32 pipelines) already clear **both**
`complex_plddt ≥ 90` and `ligand_iptm ≥ 0.8`, so the ensemble is genuinely producing
well-resolved interfaces — the gate would not be starving the pipeline, it would be removing the
tail that the pLDDT gate currently lets through.

The bottom of the `ligand_iptm` distribution is the interesting part: min 0.257 with a passing
`complex_plddt` means the protein folded confidently and the ligand placement did not. Those
models currently feed guided backbone feedback (`rfd3_input_pdb`) on equal footing with good ones.

## Recommendation

Set `fold_min_ligand_iptm = 0.7`. It costs ~6.9% of folds, is well below the median (0.870), and
targets exactly the failure mode the metric exists to catch. 0.8 is defensible but drops 22% of
folds — a large behavioural change to make on one campaign's data.

**Do not bundle this with the serialization fix.** It changes which designs pass, so it needs its
own before/after comparison on a campaign where throughput is not also changing.

## How to verify after changing it

1. Confirm `adaptive_decision`'s `fold` branch rejects on `ligand_iptm` (log line should show
   `passed=False` for a fold with high pLDDT and low `ligand_iptm`).
2. Compare high-quality yield (`plddt ≥ 90 and ligand_iptm ≥ 0.8`) per GPU-hour against this run's
   392 / 384 GPU-h = 1.02 per GPU-h. The gate should raise it, not just cut the denominator.
