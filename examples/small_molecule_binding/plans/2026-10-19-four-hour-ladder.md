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

Jobs: (to be recorded at submission).

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

## Result

(to be filled in after the runs)
