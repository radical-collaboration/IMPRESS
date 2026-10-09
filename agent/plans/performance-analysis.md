# Performance analysis of the Delta runs

## The problem

`performance_analysis/` was written on Delta, against the live run archive at
`$WORK_DIR/impress_a_runs`, and run exactly once. Three backlog findings came out of that single
session — A11 (the cost models now have a distribution behind them), G7 (seeds come from the run
label), G8 (hardware use is unmeasured) — and two of them are load-bearing: A11 is the reason not
to tighten `cost_model` toward measurement, and G7 is a stated caveat on the next allocation in
`plans/next-run-replicas.md`.

A number nobody can recompute is a number nobody can correct. The point of this layer is that it
is re-runnable over the archive, and that claim had never been tested: it had only ever run in the
environment it was written in, on a login node with `sacct` on the PATH.

## What the 2026-10-09 off-cluster run showed

Input: `impress_a_runs_2026-10-08.tar.gz`, the Tier A/B export — five jobs (22702568, 22726105,
22728140 trust; 22684607, 22692304 smoke), their `campaign.log`, `manifest.json`, ledger, all six
provenance streams and a full `work/` tree, plus `runs_summary.csv` and `_trust/cuda.jsonl`.
Unpacked outside the checkout; report written to `../impress-a-performance/2026-10-09/`.

**All twelve sections reproduce to the digit**, from the archive alone, with no cluster — eleven on
the first pass, and C3 once the sacct snapshot was taken on Delta and placed beside the run root:
101 timed tasks; every declared cost ≥2.25× the worst observed task; measured 0.0285 GPU-h per
six-stage chain against 0.17 declared; the first-run warm-up deltas (ligandmpnn +8.6s, packmin
+10.5s, Boltz +7.8s, rfd3 +4.3s); 17 designs over 5 distinct seeds in 21 same-seed pairs, all
sharing a length, median TM 0.82 same-seed against 0.28 otherwise, 0 byte-identical backbones,
median Cα RMSD 2.39 Å; and, from C3, the GPU-busy bound of ≤17%, CPU efficiency 42% and peak RSS
16.3 of 240 GB. One figure was wrong and is corrected in A11: rfd3 is 40–45s in **15** of 17
tasks, not 16 — the remaining two are 48.0s and the 145.7s outlier.

Two things C3 adds now that it has the allocation, both in G8: **tasks fill 95% of elapsed** in the
trust jobs, so orchestration is not the overhead worth attacking — the three idle GPUs are; and
**queue wait dwarfs the work**, 12269s / 26626s / 25278s for the first three jobs against 478s and
184s for the last two, up to 32× the campaign's own elapsed time. Unbilled, but it is the real
latency of a test cycle.

**Three defects, each invisible on Delta:**

| | |
|---|---|
| `datetime.UTC` is 3.11+ | `requires-python = ">=3.10"`, so `report.py` had only ever run on Delta's 3.12. It raised `AttributeError` on the first line of its own header. Fixed: `_dt.timezone.utc` |
| C3 reported `nan` as a finding | No `sacct.json` in the export → live query → missing binary → `{}` → still labelled `live sacct`, and the summary rendered *"at most nan% of the billed GPU time had a GPU task running"*. Fixed, and pinned by a test |
| The export recipe is missing a step | `snapshot_sacct.py` exists so the analysis works off-cluster, and the export was built without it. This is a build step, not an analysis step, and the README now says so |

## What remains

**Nothing on the sacct front.** The snapshot was taken on Delta and
`impress_a_runs_2026-10-08.tar.gz` rebuilt to carry it in the run root, verified by extracting the
rebuilt archive to a scratch directory and diffing its report against the working one — identical,
twelve sections, `sacct: snapshot`. The standing rule is that `snapshot_sacct.py` runs *before*
packing an export: nothing in the archive can stand in for it, since billed GPU time is
`gpus × allocation elapsed` and the manifest's campaign wall time is a different quantity.

**Candidate sections, in rough order of what they would settle:**

- `_trust/cuda.jsonl` is the only cross-job record of promotion and demotion — the evidence behind
  "promoted after r0002" in `plans/next-run-sustained-trust.md` and in two backlog entries — and no
  section reads it. It ships *outside* the run root, so `data.py` would have to decide whether a
  sibling of the archive is an input at all.
- A GPU sampler, once G8 is acted on rather than bounded. The bound is now firm — ≤17%, with tasks
  filling 95% of elapsed, so the headroom is entirely the three idle GPUs and not orchestration.
  Check the reference pipeline's per-job `<jobid>.gpusample.txt` before writing one.
- S5's TM-score half is the only part needing `tmtools`; everything else runs on numpy and gemmi.
  Worth knowing if that dependency ever blocks a rerun.

**What the archive will not support, and should stop being asked to.** Every interval in the report
is computed over 17 designs that S5 clusters into 5 folds, and 16 six-stage runs from a single
lineage. `replicas > 1` has never run (A10), so there is no independence to measure yet, and no
measurement has ever superseded a prediction, so calibration is still untestable. More sections
will not fix that; more draws will.

## Verification

```bash
# tests: synthetic runs in tmp_path, no run data needed
PYTHONPATH=src python3 -m pytest performance_analysis/tests -q

# the report, from an unpacked export (see performance_analysis/README.md for the venv)
PYTHONPATH=src <v>/bin/python -m performance_analysis.report \
    --runs <somewhere>/impress_a_runs --out <somewhere>/analysis
```

Green tests, exit 0 with no `FAILED` section, all twelve sections present, and the header naming
its sacct source — `snapshot` when the archive carries one, `unavailable` otherwise, never a
percentage computed from a `nan`. `pytest tests -q` and `ruff check src tests` must not
move — `performance_analysis/` is not part of the package. Nothing is written inside the checkout:
`common.make_ctx` refuses an `--out` under the repo, except the gitignored
`performance_analysis/out/`.
