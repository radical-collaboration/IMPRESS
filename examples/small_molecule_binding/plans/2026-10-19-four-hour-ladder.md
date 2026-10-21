# Four-hour ladder: adaptive, pass-through, naive (smb 25)

## Why

The 1 h ladder is complete: adaptive `22927576`, pass-through `22967619`
([nonadaptive-benchmark](2026-10-17-nonadaptive-benchmark.md)) and naive/open-loop `22999614`
([naive-reference](2026-10-18-naive-reference.md)), all 1 node / 32 pipelines / 1 h.

| Minutes 10–60, per GPU-h | adaptive | pass-through | naive |
|---|---|---|---|
| passing folds | 22.5 | 51.0 | 51.4 |
| high-quality folds | 11.4 | 22.2 | 20.2 |

Both plan docs and both backlog rows close with the same caveat, and it is the same one:
**1 h is early-campaign behaviour.** The adaptive policy's guided feedback runs off ensemble
history that barely exists by minute 60, so the comparison is drawn at the point most favourable
to the policies that keep no books. The 1 h result is also a mechanism claim that is explicitly
time-dependent — the first rfd3 model tied the pool best on ligand clashes 253/256 times, and
mpnn's first candidate gave up a median 0.0132 confidence — and a deeper ensemble is exactly what
would change it.

This run extends all three to 4 h, changing nothing else.

## Change

No policy change. Three launcher/runner changes that exist so the 4 h window measures what the
1 h window did (`30dfab7`):

- **`--max-tasks` / `IMPRESS_MAX_TASKS`** overrides `PROD.max_tasks = 300`, the per-pipeline
  ensemble budget. It never bound at 1 h — the fastest pipeline reached 65 (adaptive), 43
  (pass-through), 39 (naive) — but ×4 puts adaptive over 300 inside hour 4. A pipeline that
  retires mid-run drops the node's concurrency, which is precisely what made `22970061`'s
  per-node-hour rates meaningless. **All three runs use 1200**, so the budget stays non-binding
  as it was at 1 h and routing/selection remain the only difference between them.
- **`ddict_orc_*` sweep scoped by age** (`-mmin +360`). These land in the shared submit dir, so
  with three jobs launched from one checkout a starting job would delete a running job's DDict
  metadata. The neighbouring `dragon-config -c`/`add` race needs no fix: the loader returns `{}`
  on a malformed or empty file (`dragon/infrastructure/config.py:146`), all three write the
  identical value, and single-node `dragon -s` never reads `ofi_runtime_lib`.
- **`--mem` 240G → 243G** (the node ceiling: `RealMemory` 257637 less `MemSpecLimit` 8450 =
  249187 MB) and a **`hostmem.csv`** sampler every 10 s beside `nvsmi.csv`. `seff` on the 1 h runs
  shows 208.7 / 196.2 / **224.0 GB** used of 240 — naive reached 93 %. Telemetry's
  `node_memory_utilization` lands only every ~5 min (11–12 points per hour) and oscillates
  32 → 55 → 34 → 50 % with no upward trend, which suggests transient concurrency rather than
  accumulation but is far too coarse to rely on over 4 h.

Offline checks (2026-10-19): flag and env plumbing over all five precedence cases with `PROD`
left unmutated; launcher argv correct for all three configurations; mock run clean and stopping
at its budget; 127 framework tests pass; `ruff` reports the same 20 pre-existing findings as HEAD
in this example file, none new.

## Storage pre-work

The `bdyk` inode quota is shared across `/work/nvme/bdyk` and `/work/hdd/bdyk`, and three 4 h runs
project to ~665k files against 518,964 free. Job `22726386` died exactly here. Ownership at
2026-10-19: `hooten1` 1,205,594, `mgoliyad1` 701,831, `apark4` 141,331 — **42 % of the quota is
not ours**, which is why the target is a large margin rather than a sufficient one.

Reclaimed before submitting (archive job `23017676`, prune job recorded below):

- `/work/hdd/.../impress-data-after-fixes/` — 383,415 inodes, the `22534628` snapshot, tarred
  whole to `impress_run_archive/22534628_hdd.tar.gz` and deleted. Nothing read it.
- the five live runs in `logs/` — tarred one per job, then pruned **in place to their scoring
  kernel**: `telemetry/`, `nvsmi.csv`, and `p*/*_boltz/out/.../confidence_*.json`. Verified
  against the figure and scoring globs: all 230 confidence files `nonadaptive_benchmark.py` reads
  for `22999614` survive, and nothing else under a boltz dir does. `score_run.py` times folds by
  the confidence file's `getmtime`, which an in-place prune preserves.

This convention is new — the 2026-10-08 cleanup kept nothing and required untarring to re-score.

## Run

From `examples/small_molecule_binding/` on `smb-nonadaptive-benchmark`, partition `gpuA40x4`
(non-interactive), submitted in priority order:

```sh
COMMON="--partition=gpuA40x4 --time=04:00:00 --account=bdyk-delta-gpu"
IMPRESS_N_PIPELINES=32 IMPRESS_MAX_TASKS=1200 \
  sbatch $COMMON --job-name=impress_adapt4h delta_gpu_run.sh
IMPRESS_N_PIPELINES=32 IMPRESS_MAX_TASKS=1200 IMPRESS_NONADAPTIVE=1 \
  sbatch $COMMON --job-name=impress_pass4h delta_gpu_run.sh
IMPRESS_N_PIPELINES=32 IMPRESS_MAX_TASKS=1200 IMPRESS_NONADAPTIVE=1 IMPRESS_SELECTION=first \
  sbatch $COMMON --job-name=impress_naive4h delta_gpu_run.sh
```

No concurrency cap is configured — `gpua40x4qos`, the `normal` QOS and both account associations
set no `MaxJobsPU`, `MaxSubmitPU`, `MaxTRESPU` or `GrpJobs` — so all three should run at once.
Fallback for the third is `--account=bblj-delta-gpu`; lower fairshare, so expect a later start,
and say so in the write-up if it sampled the cluster at a different time. Cost is 48 GPU-hours
against balances of 18,737 (`bdyk`) and 2,852 (`bblj`).

Jobs, submitted 2026-10-19 15:38: **`23020138`** adaptive, **`23020139`** pass-through,
**`23020140`** naive. All three `PENDING` on `bdyk-delta-gpu`.

`23020138` was then lost to the Dragon fault (BACKLOG 26) and re-run on 2026-10-20 as
**`23029475`** (clean, 32/32 — the comparator this plan needed) with **`23029868`** alongside as
insurance against a repeat. See the [clean ladder result](#result2); the
[first-three result](#result) below is kept because `23020138` is still a usable data point at a
different operating point.

Pre-flight at submission:
- clean tree at `fbbb097` on `smb-nonadaptive-benchmark`;
- 768,433 inodes free of the 2,550,000 soft limit, against a ~665,000 projection. Under the
  800,000 gate because job `23019576` had not yet finished re-archiving the `22534628` snapshot,
  but the margin *improves* during the runs: they accumulate ~166k files/h over 4 h, while the
  snapshot deletion frees 383,415 within the hour;
- `p1_in`…`p32_in` all hold `ALR.params`, `ALR.smiles` and `ALR_binder_design.json`, one distinct
  checksum each across all 32 (BACKLOG 9 — the launcher does not check this itself, and an
  incomplete input dir silently cost `22670942` seven of its eight pipelines);
- `WORK_DIR`, `FOUNDRY_SIF_PATH`, `MPNN_DIR` and `BOLTZ_CACHE` set in the submitting shell, so
  `--export=ALL` carries them and all three use the shared `foundry.sif` rather than each
  extracting a sandbox to `/tmp`;
- launcher audited for shared-submit-dir writes: every one is per-job scoped or idempotent, and
  the `ddict_orc_*` sweep is age-scoped.

`sbatch --test-only` estimated 2026-10-21T00:33 for both allocations, with 1,488 jobs pending
against 263 running on the partition — so there was no queue advantage in splitting across
`bblj-delta-gpu`, and all three went to `bdyk`. Treat that estimate as an upper bound: on
2026-10-06 `--test-only` said Oct 25 for one allocation and the real start was the same morning.

## Comparison

Scored the F18 way, per node-h from minute 10 (the stagger at 32 pipelines on 4 GPUs is
`((32-1)//4)*60 = 420 s`). **Report surviving pipelines per 10-minute bucket beside every rate** —
the `22970061` lesson — and report per-hour rates rather than one 4 h average, since whether the
gap holds over time is the entire question.

| Metric | adaptive 4 h | pass-through 4 h | naive 4 h | 1 h values |
|---|---|---|---|---|
| rfd3 / mpnn / boltz per node-h | | | | 337.0/1043.5/107.9 · 262.7/526.5/265.1 · 252.6/505.3/252.6 |
| boltz per rfd3 | | | | 0.32 · 1.01 · 1.00 |
| folds / passed (pass rate) | | | | 90/75 (83.3 %) · 222/170 (76.6 %) · 212/171 (80.7 %) |
| high quality | | | | 38 (42.2 %) · 74 (33.3 %) · 67 (31.6 %) |
| **passing folds per GPU-h** | | | | 22.5 · 51.0 · 51.4 |
| **high-quality folds per GPU-h** | | | | 11.4 · 22.2 · 20.2 |
| peak ensemble per pipeline | | | | 65 · 43 · 39 |
| host RAM peak (`hostmem.csv`) | | | | 208.7 · 196.2 · 224.0 GB (`seff`) |
| `TaskFailed`, stalls > 15 s | | | | 0/2 · 0/8 · 0/— |

Also check the `[selection/backbone]` and `[selection/sequence]` lines: whether the near-identical
candidate pools of hour 1 stay that way over 4 h is the mechanism behind the 1 h tie, and the
thing most likely to move.

<a id="result2"></a>
## Result — the clean ladder (scored 2026-10-20)

`23029475` re-ran adaptive with **0 `TaskFailed` and 32 of 32 pipelines alive**, so this is the
comparison the campaign was for. `23029868`, submitted as insurance, lost 3 pipelines (p14, p18,
p27) and serves as a replicate.

| Metric (min 10–240) | **adaptive `23029475`** | pass-through `23020139` | naive `23020140` |
|---|---|---|---|
| pipelines surviving | 32 of 32 | 32 of 32 | 31 of 32 |
| rfd3 / mpnn / boltz per node-h | 344.1 / 1067.2 / 144.3 | 271.0 / 540.2 / 269.4 | 273.4 / 545.9 / 274.7 |
| boltz per rfd3 | 0.42 | 0.99 | 1.00 |
| folds / passed (pass rate) | 552 / 507 (**91.8 %**) | 1030 / 814 (79.0 %) | 1050 / 805 (76.7 %) |
| high quality | 326 (**59.1 %**) | 342 (33.2 %) | 317 (30.2 %) |
| median `complex_plddt` / `ligand_iptm` | **93.3** / 0.868 | 87.0 / 0.819 | 86.3 / 0.810 |
| passing folds per GPU-h | 33.1 | **53.2** | 52.5 |
| **high-quality folds per GPU-h** | 21.3 | **22.4** | 20.7 |
| policy task share of wall clock | 0.48 % | 0.30 % | 0.30 % |

### The 1 h penalty was an artefact of the window

High-quality folds per GPU-h, and the pass-through-to-adaptive ratio:

| window | adaptive | pass-through | ratio |
|---|---|---|---|
| 1 h (`22927576`) | 11.4 | 22.2 | **1.95×** |
| 4 h, faulted (`23020138`, 22 pipelines) | 17.8 | 22.4 | 1.26× |
| 4 h, **clean** (`23029475`, 32 pipelines) | **21.3** | 22.4 | **1.05×** |

At 4 h all three sit within 8 % of each other and **adaptive beats naive** (21.3 vs 20.7).

**Per hour of the run, adaptive starts worst and ends best:**

| high-quality folds per GPU-h | adaptive | pass-through | naive |
|---|---|---|---|
| hour 0–1 | **7.8** | 19.5 | 15.0 |
| hour 1–2 | 23.0 | 20.5 | 20.3 |
| hour 2–3 | 25.5 | 24.0 | 24.8 |
| hour 3–4 | **25.8** | 23.8 | 20.0 |

Adaptive climbs monotonically — 7.8 → 23.0 → 25.5 → 25.8 — overtakes both baselines in hour 2 and
leads for the rest of the run. The baselines flatten around 20–24 with no trend. **The 1 h
benchmark measured adaptive during its single worst hour**, which is exactly the "early-campaign
behaviour" caveat that smb 23 and 24 both flagged and neither could test. The policy needs
ensemble history, hour 1 is when it has none, and the 2× penalty recorded at 1 h is not a
property of the policy at all.

Do not over-read the last hour: these are single runs, and naive's 24.8 → 20.0 drop between hours
3 and 4 is within the noise one run supports. The monotone adaptive trend across four hours is
the solid part; "adaptive leads by 2 points in hour 4" is not.

### The replicate agrees to 0.4 %

`23029868` lost 3 pipelines, so per-GPU-h is not comparable, but per pipeline-hour is:

| run | pipelines | high-quality folds per pipeline-h |
|---|---|---|
| `23029475` | 32 | **2.664** |
| `23029868` | 29 | **2.675** |

Two runs, different nodes (gpub098 / gpub027), different surviving pipeline counts, agreeing to
0.4 %. The 21.3 figure is reproducible rather than a lucky run.

### What adaptive buys, and what it costs

It is **not** a free win. Adaptive yields 33.1 passing folds per GPU-h against 53.2 — it folds
0.42 boltz per rfd3 where the baselines fold ~1.0, and spends ~3.1 mpnn per rfd3 on retries and
resequencing. What it buys is quality: a 91.8 % pass rate against 79 %, a **59.1 % high-quality
share against 33 %**, and a median `complex_plddt` of 93.3 against 87.0.

So the headline depends on the bottleneck, and that should be stated wherever the number appears:

- **If downstream triage is the limit** — someone has to look at every fold — adaptive is at
  parity on high-quality yield while handing on **half** as many folds to sift, and those folds
  are better. That is a clear win.
- **If GPU time is the limit and all passing folds are equally useful**, pass-through still wins
  on volume, 53.2 against 33.1.

Pass-through vs naive is unchanged by the longer window: 53.2 vs 52.5 passing folds per GPU-h is
still a tie, and pass-through's edge on high quality (22.4 vs 20.7) matches its 1 h margin. Four
hours of deeper search does not make within-stage picking start to matter.

<a id="result"></a>
## Result — first three runs (scored 2026-10-19)

All three reached `TIMEOUT` at 4 h as planned. **`23020138` is not a clean comparator**: the
Dragon `ProcessGroup` fault (BACKLOG 26) hit it at minute 23 and killed 10 of 32 pipelines in a
16 s burst, so it spent ~97 % of the window at 22. It is re-run as `23029475`, with `23029868`
submitted alongside as insurance against a repeat.

| Metric (min 10–240) | `23020138` adaptive | `23020139` pass-through | `23020140` naive |
|---|---|---|---|
| pipelines surviving | **22** of 32 | 32 of 32 | 31 of 32 |
| rfd3 / mpnn / boltz per node-h | 290.8 / 912.8 / 117.1 | 271.0 / 540.2 / 269.4 | 273.4 / 545.9 / 274.7 |
| boltz per rfd3 | 0.40 | 0.99 | 1.00 |
| folds / passed (pass rate) | 449 / 415 (**92.4 %**) | 1030 / 814 (79.0 %) | 1050 / 805 (76.7 %) |
| high quality | 272 (**60.6 %**) | 342 (33.2 %) | 317 (30.2 %) |
| median `complex_plddt` / `ligand_iptm` | **93.3** / 0.864 | 87.0 / 0.819 | 86.3 / 0.810 |
| **passing folds per GPU-h** | 27.1 | **53.2** | 52.5 |
| **high-quality folds per GPU-h** | 17.8 | **22.4** | 20.7 |
| per pipeline-h: passing / high quality | 4.93 / **3.23** | 6.65 / 2.80 | 6.78 / 2.67 |
| host RAM peak (`hostmem.csv`) | 168.4 GB (69 %) | 165.8 GB (68 %) | 170.4 GB (70 %) |
| `TaskFailed` | 10 | **0** | 2 |
| policy task share of wall clock | 0.41 % | 0.30 % | 0.30 % |

### The 1 h result does not survive the longer window

High-quality folds per GPU-h, 1 h → 4 h:

| | adaptive | pass-through | naive |
|---|---|---|---|
| 1 h | 11.4 | 22.2 | 20.2 |
| 4 h | **17.8** (+56 %) | 22.4 (+1 %) | 20.7 (+2 %) |

**Adaptive improves with time; the policies that keep no books do not.** The pass-through to
adaptive ratio falls from **1.95× to 1.26×**. That is the mechanism both earlier plan docs
predicted and could not test: adaptive's guided feedback runs on ensemble history, which barely
exists at minute 60. Pass-through and naive have nothing to accumulate, and accumulated nothing.

Adaptive reached that while **handicapped by 10 lost pipelines**. Per pipeline-hour it already
leads on quality — 3.23 high-quality folds against 2.80 and 2.67.

**This is not yet a claim that adaptive wins.** Per-pipeline flatters it: 22 pipelines on 4 GPUs
is less contention per pipeline, so that normalisation is unfair in adaptive's favour exactly as
per-GPU-h is unfair against it. The defensible statement is narrower: *the ~2× gap measured at
1 h is an artefact of the window, and the true 4 h gap is at or below 1.26×.* `23029475` settles
it at 32 pipelines.

Pass-through vs naive is unchanged by the longer window: 53.2 vs 52.5 passing folds per GPU-h is
still a tie, and pass-through's 8 % edge on high quality (22.4 vs 20.7) matches its 1 h margin.
Four hours of deeper search does not make within-stage picking start to matter.

### Host RAM: the 93 % high-water mark was a measurement artefact

The new `hostmem.csv` sampler (1,440 samples per run) peaks at **68–70 %** of the 243 GB request,
while `seff` reports 82–92 % for the same runs — a gap of 31–54 GB. `seff`'s Memory Utilized is
MaxRSS summed across processes, which double-counts pages shared between the many concurrent tool
subprocesses. The telemetry's `node_memory_utilization`, sampled every ~5 min, agreed with
`hostmem.csv` all along; `seff` was the outlier.

Over a 4× longer window the peak rose only from ~135 GB (1 h) to ~170 GB, so this is a
concurrency ceiling rather than accumulation. **The `--mem` headroom concern was overstated**, and
host RAM is not the binding constraint at 32 pipelines. The `240G → 243G` change was harmless but
unnecessary.

### Other observations

- **Storage, measured:** the three runs cost 671,412 inodes against a 665,032 projection — linear
  extrapolation from the 1 h runs was accurate to 1 %. Adaptive is the expensive one (282,695
  paths against ~192k), because retries mean more tasks per fold.
- `23020139` ran **0 `TaskFailed` across 4 h and 32 pipelines**, so the stack is sound; the fault
  is sporadic rather than load-induced.
- The policy callback stayed cheap at 4 h: 0.30–0.41 % of wall clock over ~7,400 calls per run,
  against the 67.1 % that capped `22534628`.

### Limits

- One run per configuration, and the adaptive one is compromised.
- `23020138` and `23020139` overlapped in time; `23020140` started later. Different nodes
  throughout (gpub051 / gpub072 / gpub061).
- Quality is still Boltz self-confidence, not an experimental result.

### Data and the next session

All three runs are archived as per-pipeline part sets under
`/work/hdd/bdyk/hooten1/impress_run_archive/` (6.0 G, 99 parts, entry counts verified exact
against the live trees), and the live `logs/` trees are pruned to their scoring kernels —
`telemetry/`, `nvsmi.csv`, `hostmem.csv` and the per-fold `confidence_*.json` at their original
paths. Scoring and figures work on the cluster unchanged; anything else, including the
`[selection/*]` lines and the mpnn candidate pools, exists only in the tarballs.

**`ANALYSIS_BRIEF.md`** in that directory carries the brief for the session that picks this up
after download: what is settled and must not be re-derived, the five open questions, the scoring
conventions, the traps (pipeline survival, the two normalisations, `seff`'s memory overcount, the
equal-window rule) and the defects that shape the data.
