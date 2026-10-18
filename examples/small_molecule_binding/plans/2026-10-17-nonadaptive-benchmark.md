# Non-adaptive benchmark: 1 node, 1 h, 32 pipelines (smb 23)

## Why

The adaptive workflow needs a baseline that differs from it only in routing. The adaptive
reference is framework F18's `22927576`: 1 node, 1 h, `gpuA40x4-interactive`, 32 pipelines
(8 per GPU), staggered start. It gave rfd3 337.1, boltz 108.0 and mpnn 1043.8 per node-h from
minute 10, with 0 failures
([pr1-head-confirmation](../../../plans/2026-10-15-pr1-head-confirmation.md#result)).

`run_nonadaptive.py` could not serve as that baseline. It predated every runner fix since
2026-10-04:
- one Dragon backend, with no `local` backend;
- every pipeline read `p1_in`, from a hardcoded list of 21 indices;
- no argv config;
- no GPU pinning (smb 10);
- no staggered start (smb 14, which OOM-killed `22714785`);
- no telemetry and no `runner_status`.

## Change

- `run_small_molecule_binding.py --nonadaptive` swaps `adaptive_decision` for
  `nonadaptive_decision`, logs a `[POLICY]` line, and changes nothing else.
- Under `delta_gpu_run.sh`, `IMPRESS_NONADAPTIVE=1` forwards that flag as argv.
- `run_nonadaptive.py` is deleted.
- The policy is **pass-through**: every backbone goes rfd3 → mpnn/packmin × `num_refine_cycles`
  → fastrelax → filter_shape → boltz → a fresh unguided rfd3.
  - Analysis pass/fail is logged and never acted on.
  - There are no sequence retries, no fastrelax/interface escalation and no guided feedback.
- Thresholds stay `PROD`, so pass rates are directly comparable.

Offline check (2026-10-17): the mock run with the pass-through policy completed 20 backbones, each
running rfd3, mpnn, packmin, mpnn, packmin, mpnn, fastrelax, filter_shape, boltz. It produced 0
`[adaptive/` lines and 0 guided rfd3. Framework tests: 127 passed.

## Run

From `examples/small_molecule_binding/` on branch `smb-nonadaptive-benchmark`:
```
IMPRESS_N_PIPELINES=32 IMPRESS_NONADAPTIVE=1 sbatch --partition=gpuA40x4-interactive \
  --time=01:00:00 --account=<allocation A> --job-name=impress_nonadaptive delta_gpu_run.sh
```
Pre-flight (2026-10-17):
- clean tree;
- `p1_in`…`p32_in` hold `ALR.params`, `ALR.smiles` and `ALR_binder_design.json`;
- project inodes at 1.92M of the 2.55M soft limit, which leaves room for ~630k;
- no other job running.

Job: _pending_

## Comparison

Scored with the F18 method: per node-h from minute 10. The scoring script must reproduce
337.1 / 108.0 / 1043.8 on `22927576` before its numbers for this run are trusted.

| Metric | `22927576` (adaptive) | this run |
|---|---|---|
| rfd3 / boltz / mpnn per node-h | 337.1 / 108.0 / 1043.8 | |
| boltz per rfd3 | 0.31 (99 / 321) | |
| folds passed / pass rate | | |
| median `complex_plddt`, `ligand_iptm`; high-quality on both | | |
| passing folds per GPU-h | | |
| GPU busy, stalls > 15 s, `TaskFailed` | 71–80 %, 2, 0 | |
| policy task share of wall clock | 0.31 % | |

Caveat: 1 h with a ~4 min stagger measures early-campaign behaviour. The adaptive policy's
ensemble history, which drives guided feedback, barely builds in that time.

<a id="result"></a>
## Result

_pending_
