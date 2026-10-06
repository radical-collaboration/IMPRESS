# Adaptive callback serialized the whole job (job 22534628)

**Severity:** critical · **Status:** fixed on `scaling-wide`; **validated at scale** on `22701168` (2026-10-06, 32 pipelines, 4 h)
**Evidence:** job `22534628`, 8 nodes / 32 pipelines, `TIMEOUT` at `Elapsed=12:00:10`
**Artifacts:** `<hdd work dir>/impress-data-after-fixes/smb_8node/small_molecule_binding/`

## Symptom

Job-wide throughput collapsed ~30x between hours 2 and 4 and never recovered.

| elapsed | rfd3/pipeline/h | % of 4-node baseline (11.46) |
|---|---|---|
| h0–2 | **12.05** | **105%** |
| h2–4 | 4.80 | 42% |
| h4–6 | 1.62 | 14% |
| h6–8 | 3.61 | 31% |
| h8–10 | 1.70 | 15% |
| h10–12 | 1.62 | 14% |
| **full run** | **4.24** | **37%** |

Mean GPU utilisation fell from 11.1% (h0) to **0.7%** (h4); CPU held ~46–50% on workers, 70.3% on
the Dragon primary. **The hardware was idle** — this was starvation, not contention.

Only 1 of 32 pipelines reached `max_tasks=300` (mean 227.6, min 159).

The first two hours are the important control: at 105% of the 4-node baseline, **8-node /
32-pipeline scaling itself is sound**. Everything after h2 is this defect.

## Root cause

`adaptive_decision()` in `run_small_molecule_binding.py` was declared `async def` but contained
**zero `await` in its 220-line body**, so every invocation blocked the single asyncio event loop
shared by all 32 pipelines — including task dispatch, subprocess reaping and Dragon completion
handling.

What made each invocation expensive: the `sequence` branch calls `_ensemble_selective_avg()`, which
calls `sim_fn` **once per prior ensemble entry**. `_seq_identity` → `_read_fasta_seq` did a blocking
`open()` every time, re-reading `current` on each comparison — ~540 Lustre opens per decision at
ensemble 270, against a tree of ~245k small files on HDD-backed Lustre. Total reads over a run were
O(entries²).

`_parse_pdb_ca_coords` was **already** `@lru_cache`'d, which is exactly why the `backbone` and
`fold` branches cost ~0 while `sequence` cost 4.93 of the 4.98 adaptive hours measured at h8.6.
The one uncached reader was the one that hurt.

## Measurements

Adaptive occupancy of manager wall clock:

| | n | total | occupancy | median | p90 | p99 | max |
|---|---|---|---|---|---|---|---|
| baseline `22491438` (16 pipelines) | 7238 | 0.23 h | **3.4%** | 0.002s | 0.229s | 1.36s | 9.3s |
| this run (32 pipelines) | 10655 | 8.01 h | **67.1%** | 0.005s | 0.223s | **56.0s** | **193.3s** |

Occupancy by hour: h0=1% h1=4% h2=35% h3=75% h4=95% h5=90% h6=73% h7=78% h8=87% h9=89% h10=95% h11=79%.

The median is unchanged — this is a pure **tail explosion**, the signature of a serial server
crossing saturation. At 16 pipelines the loop had 96% headroom; doubling the arrival rate against a
fixed serial resource pushed it past ρ≈1 and queueing delay went non-linear.

Corroboration that it was the loop and not the filesystem: in hour 4 *every* stage's measured median
inflated together — mpnn 17→392s (23x), packmin 8→332s (41x), filter_shape 14→445s (32x),
boltz 62→1992s (32x), rfd3 100→338s — local *and* Dragon, CPU *and* GPU, while GPUs sat at 0.7%.
Real I/O contention cannot slow a GPU task 32x with the GPU idle; a blocked event loop that cannot
reap completions inflates all of them at once.

## Cost

| | passing folds | GPU-h | GPU-h per passing fold |
|---|---|---|---|
| baseline `22491438` (4 nodes, 6.68 h) | 552 | 106.9 | **0.194** |
| this run (8 nodes, 12 h) | 577 | 384 | **0.666** |

**2x the hardware delivered 1.05x the output — 3.4x worse cost-efficiency.**

## Fix

Two changes, both needed.

**1. Memoise the reader** (`small_molecule_binding.py`). `_FASTA_SEQ_CACHE` keyed on path, which is
sound because every task writes into its own `{taskcount}_{taskname}/` directory and `taskcount`
increments for every HPC task — no FASTA path is written twice. Negative results are deliberately
not cached, so a missing file does not pin the failure for the rest of the run. Turns total reads
from O(entries²) into O(entries).

Also raised `_parse_pdb_ca_coords`'s `lru_cache` 512 → 4096: the manager process is shared by all
pipelines, so the live working set is (ensemble entries) × (n_pipelines), and 512 thrashed at 32.
~14 KB per cached CA trace, so 4096 costs ~57 MB of a 240 GB node.

**2. Get off the event loop** (`run_small_molecule_binding.py`). `adaptive_decision()` is now a thin
`async` wrapper that `await asyncio.to_thread(_adaptive_decision_sync, pipeline)`. Safe because the
body only reads `pipeline.state` and assigns `pipeline.state[...]` / `pipeline.next_step`, and
`ImpressManager` awaits each pipeline's adaptive task before advancing that pipeline
(`src/impress/impress_manager.py:100-116`), so there is no concurrent writer to the same state.

With (1) the body is already fast; (2) is the belt-and-braces half that keeps a future similarity
metric which reintroduces I/O from taking the whole job down again.

## Validation done

- 12/12 adaptive branch cases (all six steps × pass/fail) produce identical
  `(next_step, seq_retry_count, rfd3_input_pdb)` with the cache on vs monkeypatched off.
- `_read_fasta_seq` memo == fresh read; negative results confirmed uncached.
- A concurrent heartbeat task ticks during a cold 1200-entry decision (0 ticks would mean it still
  blocks).

## Acceptance test — passed (`22701168`, 2026-10-06)

| Measure | Required | `22701168` (8 nodes / 32 pipelines / 4 h) |
|---|---|---|
| Adaptive occupancy | < 10 % | **0.96 %** (13,074 paired `.out` calls; telemetry gives 0.81 %) |
| p99 per call | < 2 s | **0.071 s** (max 0.79 s) |
| rfd3/pipeline/h beyond hour 2 | ≥ 11 | **16.28** in h2, **15.19** in h3; 15.71 overall |
| GPU utilisation | no decay toward ~1 % | 9–15 % per node in every hour |
| GPU-h per passing fold | vs baseline 0.194 | **0.160** (802 of 871 folds passed) |

This run also had the later delegation (`59a9e20`) and GPU spread (`854ecd6`) changes, so the gain is not attributable to this fix alone. The collapse mechanism, the callback saturating the loop, is gone either way. Details: [scale-gate](2026-10-06-scale-gate.md).

## Original acceptance criteria

Re-run the occupancy measurement against the next 32-pipeline campaign: pair
`Adaptive function started/completed for: pN` in the `.out` file, sum the durations, divide by span.

**Accept if occupancy < 10% and p99 per-call < 2s** (baseline 3.4% / 1.36s; this run 67.1% / 56.0s).

**Scale target:** sustained ≥ 11 rfd3/pipeline/h *beyond hour 2* — i.e. the h0–2 rate of 12.05 holds
for the whole run — and GPU utilisation no longer decaying toward ~1%. Compare passing folds per
GPU-hour against the baseline's 0.194.

## Correction to the CLAUDE.md 2026-09-28 row

That row projected the `local_task`-on-primary load at ~124% (oversubscribed) for 32 pipelines.
It did not happen: per-node CPULoad was **26.0–34.7 of 64**, with the Dragon primary `gpub068` at
34.68 — only ~4 cores above the mean. The primary-node ceiling is real but still not binding at 32
pipelines. The actual ceiling was the single-threaded manager.
