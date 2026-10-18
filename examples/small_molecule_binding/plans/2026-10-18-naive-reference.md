# Naive (open-loop) reference: 1 node, 1 h, 32 pipelines (smb 24)

## Why

[nonadaptive-benchmark](2026-10-17-nonadaptive-benchmark.md) removed *routing* feedback and found
pass-through at 51.0 passing / 22.2 high-quality folds per GPU-h against adaptive's 22.5 / 11.4
(`22967619` vs `22927576`). But pass-through is still a **greedy** workflow: each analysis stage
picks the best candidate its tool produced, so metrics keep steering the work.

The live selection points, confirmed against `logs/22967619`:

| Stage | Pool | Picked by |
|---|---|---|
| `analysis_backbone` (`small_molecule_binding.py:810`) | 4 rfd3 models | fewest ligand clashes, then lowest `max_ca_deviation` |
| `analysis_sequence` (`:936`) | 40 LigandMPNN candidates in cycle 0 (10 batches × `num_seqs=4`), 4 later | highest `overall_confidence`; also sets `best_packed_pdb`, so it picks the structure every later stage uses |
| `analysis_fold` (`:1167`) | 1 model | **already a no-op** — `scripts/boltz.sh:85` defaults `--diffusion_samples 1` |

This run is the third point: open-loop, where no metric influences anything.

## Change

`selection` kwarg on `SmallMoleculeBindingPipeline` — `"best"` (default) or `"first"`:

- `analysis_backbone` takes `sorted(json_files)[0]` (`*_model_0`).
- `analysis_sequence` takes the first `id=` record in sorted-filename order (`id=1`).
- `analysis_fold` is unchanged, with a comment saying why: one model per task, nothing to choose.
  If `--diffusion_samples` ever rises it becomes a third selection point and must honour the kwarg.
- `mock.py`'s `analysis_sequence` mirrors it, so mock runs still exercise the real behaviour.
  Its `analysis_backbone` synthesises one model, so there is nothing to select there.
- Both modes also record the pool's best value (`pool_best_clashes`/`pool_best_dev`,
  `pool_best_confidence`) in `last_analysis_metrics`. Metrics only; nothing reads them. This is
  what lets the write-up say how much quality the picking was buying.

`--selection {best,first}` on the runner (named in the `[POLICY]` line);
`IMPRESS_SELECTION=first` on `delta_gpu_run.sh`.

**Candidate pools are deliberately unchanged.** The naive run still generates 4 backbones and 40
sequences and throws the rest away. Keeping compute per backbone identical is what makes
throughput comparable; shrinking the pools would confound the measurement.

Offline checks (2026-10-18):
- mock with `--selection first` chose `binder_id_1` 60/60; with `best`, `binder_id_3` (the
  highest confidence, 0.5670). Stage sequence identical in both: 180 stages, same order.
- a mock run of unmodified HEAD gives the same 180 stages and the same `binder_id_3` as
  `--selection best`, so the default path is untouched.
- framework tests 127 passed; no new ruff findings in `small_molecule_binding.py` (52 → 51
  pre-existing) or `mock.py` (19 → 19).

## Run

From `examples/small_molecule_binding/` on `smb-nonadaptive-benchmark`:
```
IMPRESS_N_PIPELINES=32 IMPRESS_NONADAPTIVE=1 IMPRESS_SELECTION=first \
  sbatch --partition=gpuA40x4-interactive --time=01:00:00 \
  --account=<allocation A> --job-name=impress_naive delta_gpu_run.sh
```
Pre-flight (2026-10-18): clean tree; `p1_in`…`p32_in` populated; project inodes 1.96M of the
2.55M soft limit, ~588k free (`22967619` cost ~36.5k files / 1.6 GB); no other job queued or
running.

Job: _pending_

## Risk: this run may lose pipelines

Taking `model_0` regardless of clashes feeds structurally bad backbones downstream, and
[smb 15](BACKLOG.md) says a failed stage kills its whole pipeline (`'NoneType' object is not
subscriptable`). If pipelines die, effective concurrency falls and per-node-h rates stop being
comparable. The watch flags `TaskFailed` immediately, and scoring reports surviving pipelines
alongside the rates — a run that loses half its pipelines is evidence about open-loop fragility,
not a throughput measurement.

## Comparison

Scored the F18 way: per node-h from minute 10 to the last telemetry event. Same script as
smb 23, which reproduces `22927576` as 337.0 / 107.9 / 1043.5 against F18's 337.1 / 108.0 /
1043.8.

| Metric | `22927576` adaptive | `22967619` pass-through | this run (naive) |
|---|---|---|---|
| rfd3 / mpnn / boltz per node-h | 337.0 / 1043.5 / 107.9 | 262.7 / 526.5 / 265.1 | |
| folds / passed (pass rate) | 90 / 75 (83.3 %) | 222 / 170 (76.6 %) | |
| high quality (pLDDT ≥ 90, ipTM ≥ 0.8) | 38 (42 %) | 74 (33 %) | |
| **passing folds per GPU-h** | 22.5 | 51.0 | |
| **high-quality folds per GPU-h** | 11.4 | 22.2 | |
| surviving pipelines, `TaskFailed` | 32, 0 | 32, 0 | |
| `pool_best` − chosen, per stage | — | — | |
| GPU busy (mean) | 70–81 % | 58–62 % | |

Caveat, as for smb 23: 1 h with a ~4 min stagger is early-campaign behaviour, and this is one run
per configuration.

<a id="result"></a>
## Result

_pending_
