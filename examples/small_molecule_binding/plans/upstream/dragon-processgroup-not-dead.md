# Dragon: `ProcessGroup manager is not in state State.DEAD` kills live pipelines mid-run

**Component:** dragonhpc 0.14.1 `dragon.native.process_group`, reached through rhapsody 0.5.0
`DragonExecutionBackend` (`rhapsody/backends/execution/dragon.py`)
**Severity:** high — it cost a whole adaptive run (`23020138`, 10 of 32 pipelines) and made
`22970061` unscoreable (18 of 32). It is now the largest single threat to this campaign's validity.
**Status:** four occurrences characterised from job logs; cause not confirmed in-process, not
reported upstream
**Evidence:** `impress_<job>.out` and `logs/<job>/telemetry/*.jsonl` for the jobs below, all
archived under `/work/hdd/bdyk/hooten1/impress_run_archive/`

## What we saw

A tool task raises `RuntimeError('ProcessGroup manager is not in state State.DEAD')`. Under
smb 15 a failed stage kills its whole pipeline, so each raise costs a pipeline for the rest of
the run. The node, the other pipelines and the engine all carry on normally.

| Job | Node | Pipelines, 4 GPU | When | Burst | Raises | Stages hit | Pipelines lost |
|---|---|---|---|---|---|---|---|
| `22970061` | gpub002 | 32, 1 h | min 9 | 00:27:26–00:27:36, **10 s** | 34 | boltz 8, rfd3 6, fastrelax 3 | **18 of 32** |
| `23020138` | gpub051 | 32, 4 h | min 23 | 16:12:02–16:12:18, **16 s** | 12 | rfd3 6 | **10 of 32** |
| `23020140` | gpub061 | 32, 4 h | min 72 | 18:12:21, **single** | 2 | fastrelax 1 | **1 of 32** |
| `23020139` | gpub072 | 32, 4 h | — | none | 0 | — | 0 |

What the four runs establish:

- **It is not node-specific.** Four different nodes, three affected.
- **It is not stage-specific.** rfd3, boltz and fastrelax have all raised it. Those run on
  different backends' paths (rfd3/boltz are GPU tasks, fastrelax is CPU), so it is not a property
  of one tool or one script.
- **It is not load-specific in any obvious way.** `23020139` ran the identical 32-pipeline
  configuration concurrently with `23020140` and never saw it.
- **It arrives as one burst, then stops.** Every occurrence is a single window of 16 s or less,
  with nothing before or after in a 4 h run. It is not a slow degradation.
- **Blast radius varies by two orders of magnitude** — 1 pipeline to 18 — and does not obviously
  track the burst length (34 raises in 10 s cost 18 pipelines; 12 raises in 16 s cost 10).
- **It is not the stagger.** `23020140` was 72 min in, long past the 7 min ramp.

## Why it matters here

Per-node-hour is this campaign's headline metric, so a run that loses pipelines mid-flight stops
being comparable with one that does not. `22970061` was recorded inconclusive for exactly this
reason. `23020138` completed its 4 h but spent ~97 % of the window at 22 pipelines rather than 32,
so it is a usable data point at a different operating point, not a comparator — it had to be
re-run as `23029475`.

The cost is amplified by **smb 15**: nothing retries or re-seats a pipeline whose stage raised.
A single transient fault is therefore permanent for that pipeline. If smb 15 were fixed, these
four events would have cost four brief stalls instead of 29 pipeline-runs.

## What we have not done

- No `py-spy dump` against a live manager during a burst — the bursts are under 20 s in 4 h runs,
  so catching one needs a watcher armed in advance rather than a manual attempt.
- Not traced into `dragon.native.process_group` to see which state the manager was actually in,
  or which side observed the transition.
- Not established whether the raise means the task's work was lost. In `23020138` all six raises
  were `rfd3`, the same stage as smb 16 (rfd3 reported failed *after* writing all its outputs),
  so some of these tasks may have completed their work before the error surfaced. Worth checking
  the task dirs of a failed pipeline against a successful one.

## Next

1. Arm a watcher that greps the live job log for `ProcessGroup manager` and immediately
   `py-spy dump`s the runner — the burst is short, so this cannot be done by hand.
2. Check whether a raising task left complete outputs on disk (ties to smb 16).
3. Fix smb 15 regardless. It converts every transient backend fault into a permanent loss of
   concurrency, and it is the reason a 10 s event costs 56 % of a run.
