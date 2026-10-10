# Framework PR 3 (Tier 3): task dirs, adaptive errors, staggered start

**Status:** open, design only · **Items:** F8–F10 · **Depends on:** PR 2 (F3 moves registration, which F8 builds on)

<a id="f8"></a>
## F8 — Task-directory helper

**Evidence.** smb (7×) and discontinuous (8×) repeat the same bookkeeping:
```
self.taskcount += 1
taskdir = f"{base}/{name}/{self.taskcount}_{stage}"
os.makedirs(f"{taskdir}/in"); os.makedirs(f"{taskdir}/out")
```
smb's `_FASTA_SEQ_CACHE` memo is sound only because that pattern makes every output path write-once (smb CLAUDE.md, 2026-09-30 row).

**Change.**
- Add `ImpressBasePipeline.new_task_dir(stage, root=None) -> TaskDir(path, in_dir, out_dir, index)`. The base owns `taskcount`.
- Document the write-once guarantee as a framework invariant.
- Migrate both examples. Keep each one's directory layout byte-identical, since `validate_run.py` and the archive tooling read it.

**Test.**
- Unit tests for numbering and directory creation.
- The smb mock run's tree listing is identical before and after.

<a id="f9"></a>
## F9 — Adaptive errors reach the pipeline

**Evidence.**
- `ImpressManager._run_adaptive_fn` logs an exception and then releases the barrier.
- The pipeline continues with whatever `next_step` it had before. In smb's state machine that repeats the last stage indefinitely, or until `max_tasks`.
- PR 1 moved adaptive functions into worker threads, which makes this kind of silent failure easier to miss.

**Change.**
- Store the exception on the pipeline, and re-raise it from `run_adaptive_step()`.
- Add `ImpressManager(adaptive_errors="raise" | "log")`, defaulting to `"raise"`. Make the default change explicit in the PR.

**Test.** An adaptive function that raises makes `run_adaptive_step()` raise in the pipeline, and with `"log"` it does not.

<a id="f10"></a>
## F10 — Staggered start as a manager option

**Evidence.**
- Every smb pipeline starts with rfd3 (~9.5 GB host RAM each).
- 32 pipelines started together OOM-killed a node in 2 min (`22714785`).
- smb's runner computes `start_delay = ((N-1)//slots)*60` and `run()` sleeps on it.
- Any workflow whose first stage is memory-heavy needs the same thing.

**Change.**
- `ImpressManager.start(..., stagger=(group_size, seconds))` delays creating each group's pipeline tasks, and logs the schedule.
- Remove `start_delay` from smb's `run()` and runner.

**Test.**
- Unit: with a fake clock, the start times of groups are spaced by `seconds`.
- Delta: the next 8-per-GPU run's host-RAM peak is no worse than `22718758` (62 %).
