# F18 — PR 1 branch-head confirmation run on Delta

**Status:** **passed** on job `22927576` (`<allocation A>`, `gpuA40x4-interactive`, gpub071, 1 node, 1 h, 32 pipelines, from `9f91e46`; 17:18:29 → 18:18:56, `TIMEOUT` 1:00:27 at the limit as planned). See [Result](#result) · **Branch:** `framework-defaults-pr1` · **Blocks:** pushing and merging PR 1 · **Items:** F18; confirms F14, F17

## Why

F1 passed on `22767771`, launched from `1372251`. Since then, two commits on the branch change
code:

- `f12c2cb`: a ruff reformat of `impress_manager.py` and one test;
- `a74b71d`:
  - **F14:** `ImpressManager(adaptive_backend=...)`. `start()` validates the name against the
    engine's backend table, and offloaded callbacks run as
    `flow.function_task(backend=self.adaptive_backend)`. The smb runner passes `"local"`.
  - **F17:** `pipeline.telemetry` returns only what the manager injects.
  - The `stdio.py` docstring and new tests.

Offline evidence is complete:
- 127 tests pass with rhapsody, and 122 pass / 5 skip with rhapsody blocked;
- ruff is clean;
- the smb mock run gives the same 124 stages and 136 adaptive decisions before and after.

Offline cannot show two things:
- that the `start()` check accepts a real Dragon + `local` engine;
- that, with the probe gone, adaptive tasks still land on `local` under Dragon.

The same run also answers F1's caveat. F1's full-window throughput was 16 % low, which was
attributed to a Dragon completion stall (smb 22) and the injected failure. This run has no
injected failure, so a run more than 10 % slow *without* a stall reopens that question.

## Run

- Shape: 1 node, 1 h, `gpuA40x4-interactive`, 32 pipelines (8 per GPU), account
  `<allocation A>`. This matches `22767771` and `22718758`.
- Launched from a clean checkout of the branch head. No failure injection.
- `IMPRESS_N_PIPELINES=32 sbatch --partition=gpuA40x4-interactive --time=01:00:00 --account=<allocation A> --job-name=impress_pr1_head delta_gpu_run.sh`,
  from `examples/small_molecule_binding/`.
- Pre-flight:
  - `git status` is clean;
  - `p1_in`…`p32_in` each hold `ALR.params`, `ALR.smiles` and `ALR_binder_design.json` (smb 9);
  - the project inode count, from `quota`, has room for ~55k files (smb 18);
  - no other job is writing under `logs/`.

## Pass criteria

Score with the F1 method: per node-h counted from minute 10. It reproduces `22718758`'s 315.5 /
94.3 / 1073.

| Check | Pass | Confirms |
|---|---|---|
| Startup | runner reaches `Active: 32 pipelines`; no `ValueError` from `_check_adaptive_backend` | F14 validation on a real engine |
| Adaptive routing | every adaptive TaskQueued has `backend=local` and label `p<N>:adaptive`; adaptive share ≤ 1 % of wall clock | F14's declared path matches what F1 measured |
| Telemetry handle | `impress.LocalStage` count = analysis calls, 1:1 with each tool stage's completions | F17: injection still reaches pipelines (a break would give 0) |
| Labels | 100 % of tasks labelled `p<N>:<stage>` or `p<N>:adaptive` | PR 1 labels unchanged |
| Failures | 0 `TaskFailed`. An smb 16 recurrence counts against smb 16/22, not PR 1 | — |
| Throughput | rfd3 and boltz per node-h over min 10–60 within 10 % of 315.5 / 94.3. Also record silences > 15 s between completions | F1's caveat |
| Storage | ~30.7 files per tool task (run dir plus session dir) | unchanged from F1 |

## After

- Add a Result section with the numbers against each criterion.
- Set F14/F17 to "confirmed on `<job>`".
- Update the smb CLAUDE.md 2026-10-15 row, which says "No Delta run".
- If it passes, push and merge PR 1, then delete the F1 and F18 rows.
- If the startup check fails, fix it, add a test, and rerun before pushing.

<a id="result"></a>
## Result — job `22927576` (scored 2026-10-15)

Scored with the F1 scripts (per node-h from minute 10). Sources: `logs/22927576/telemetry/*.jsonl`,
`logs/22927576/nvsmi.csv`, `impress_22927576.out`.

| Check | `22927576` | Reference | Verdict |
|---|---|---|---|
| Startup | `IMPRESS MANAGER STARTING`, then p1's first rfd3 at 17:18:46; all 32 pipelines active by 17:26. No `ValueError` | — | pass |
| Adaptive routing | 2043 of 2043 adaptive TaskQueued on `local`, all labelled `p<N>:adaptive`; 0.31 % of wall clock, p50 0.003 s, p99 0.041 s, max 0.103 s | F1 `22767771`: 0.47 %, p99 0.140 s | pass |
| Telemetry handle | 2043 `impress.LocalStage`, all `completed`, 0 duplicates; 1:1 with completions (backbone 321 = rfd3, sequence 972 = mpnn, packmin 303, fastrelax 228, fold 99 = boltz) | — | pass |
| Labels | 4118 of 4118 tasks labelled | — | pass |
| Failures | 0 `TaskFailed`, 0 tracebacks; no smb 16 recurrence | 0 | pass |
| Throughput (min 10–60, per node-h) | rfd3 **337.1** (+6.8 %), boltz **108.0** (+14.5 %), mpnn 1043.8 (−2.7 %) | `22718758`: 315.5 / 94.3 / 1073 | pass |
| Completion stalls > 15 s after min 10 | 2 (24 s, 17 s; 41 s total) | `22718758`: 3 (57 s); `22767771`: 8 (198 s) | no large stall |
| Storage | 60,138 run + 4,172 session files for 2075 tool tasks = **31.0/task**; 3.2 GB | F1: 30.7 | pass |

Other measurements:
- GPU busy after minute 10: mean 71–80 %, at 100 % for 44–61 % of the time, against 70–76 % on `22718758`.
- Manager: median inter-task gap 0.275 s, pipelines in a task 98.2 % of the time, local stages 0.24 % of wall clock.
- Node memory peaked at 63.1 % (ResourceUpdate), against 61.5 % on `22718758`. seff's 87 % comes from `MaxRSS`, which was ~201 GB on both earlier runs too.

**F1's caveat is settled.** With no injected failure and no smb 16 event, the branch head ran
above the reference rather than 16 % below it. That supports the F1 attribution: the shortfall
on `22767771` came from the Dragon completion stall and the lost pipelines, not from PR 1.

**F14 and F17 are confirmed on Dragon.** The branch is ready to push and merge.
