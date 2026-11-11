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

Job: `22967619` (submitted 2026-10-17).

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
## Result — job `22967619` (scored 2026-10-17)

`TIMEOUT` at 01:00:27 on gpub015, as planned. 0 `TaskFailed`, 0 tracebacks. The log shows
`[POLICY] nonadaptive_decision`, 32 pipelines and the same 60 s stagger as the reference.

The scoring script is `score_run.py`, kept outside the repo. It reproduces `22927576` as 337.0 /
107.9 / 1043.5 against F18's 337.1 / 108.0 / 1043.8, and also reproduces its stalls, policy share
and GPU busy figures. The window runs from minute 10 to the last telemetry event, 0.834 h for
both runs. A fold is the best-`complex_plddt` model of one boltz task, timed by its confidence
file.

| Metric (min 10–60) | `22927576` adaptive | `22967619` pass-through | ratio |
|---|---|---|---|
| rfd3 / mpnn / boltz per node-h | 337.0 / 1043.5 / 107.9 | 262.7 / 526.5 / 265.1 | 0.78 / 0.50 / 2.46 |
| boltz per rfd3 | 0.32 | 1.01 | |
| folds / passed (pass rate) | 90 / 75 (83.3 %) | 222 / 170 (76.6 %) | |
| high quality (pLDDT ≥ 90, ligand ipTM ≥ 0.8) | 38 (42 % of folds) | 74 (33 %) | |
| median `complex_plddt` / `ligand_iptm` | 89.6 / 0.836 | 86.7 / 0.810 | |
| **passing folds per GPU-h** | 22.5 | **51.0** | **2.27×** |
| **high-quality folds per GPU-h** | 11.4 | **22.2** | **1.95×** |
| GPU busy (mean / at 100 %) | 70–81 % / 44–61 % | 58–62 % / 36–38 % | |
| completion stalls > 15 s | 2 (41 s) | 8 (150 s) | |
| policy task share of wall clock | 0.31 % (2043) | 0.28 % (1774) | |

Whole-run totals for `22967619`: 240 folds, 185 passed and 80 high quality. The analysis stages
logged 17 backbone, 106 fastrelax, 30 interface and 55 fold failures. Under pass-through every
one went straight to the next stage.

**Over this 1 h window, pass-through routing produces about 2× the high-quality folds per GPU-h
of adaptive routing.**
- The adaptive policy spends about 3.7 mpnn per rfd3 on sequence retries and fastrelax/interface
  resequencing, and sends only a third of its backbones to boltz.
- Pass-through runs 2 mpnn per backbone and folds every one.
- Gating does raise quality per fold: the pass rate is 83 % against 77 %, and the high-quality
  share is 42 % against 33 %. That gain is too small to pay for the extra work.

Other observations:
- GPU busy fell by about 15 points while output rose. Each pass-through backbone also runs
  fastrelax and filter_shape on the CPU, so fewer GPU tasks are in flight at once. The GPU was
  not the binding limit for this policy.
- There were more Dragon completion stalls (8 against 2) but none over 30 s (smb 22).
- Memory peaked at 196 GB of 240 (seff). CPU efficiency was 59 %. The run directory holds
  1.6 GB.

Limits of the comparison:
- One run of each policy.
- The window is 1 h, which is early-campaign behaviour. The adaptive policy's guided feedback
  depends on ensemble history that barely exists by minute 60. A multi-hour pair is needed
  before saying pass-through wins in steady state.
- High-quality per GPU-h is the right headline only if downstream capacity is not the limit.
  Pass-through hands on more folds, and a larger share of them are weak.

Figure: `figures/nonadaptive_benchmark.py` (house style; panels: cumulative passing and
high-quality folds, tool throughput, pLDDT × ipTM per fold).
