# IMPRESS framework — backlog tracker

Open work for the framework itself (`src/impress/`): lifting fixes proven in the examples into
`ImpressBasePipeline`, `ImpressManager` and the asyncflow interface, so each example stops
rediscovering them. One line per item; details live in the linked doc. Keep `Status` current, and
delete rows once the change is merged **and** a run confirms it.

Example-specific work is tracked separately, e.g.
[small_molecule_binding/plans/BACKLOG.md](../examples/small_molecule_binding/plans/BACKLOG.md)
(cited below as "smb N").

Origin: the categorised, ranked plan of 2026-10-08. PR 1 (Tier 1, `7327c84` onwards) **merged to
`main` as PR #72 (`9a413cd`, 2026-10-21)**: stdio captured by default, `{pipeline}:{stage}` task
labels, stderr tail on failure, `impress.LocalStage` for local tasks, `logged_command`, adaptive
functions as declared engine tasks (F19, F20), and the `DragonExecutionBackendV3` import fix.

Tier = (measured impact or failure prevented) × (examples that benefit) ÷ effort; 1 is highest.

F14–F17 come from the 2026-10-15 review of PR 1 against asyncflow 0.5.1's own patterns
(`examples/04-concurrent_backends.py`): where the engine now has an idiom, the escape goes
back. See [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md).

| # | Item | Tier | Status | Doc |
|---|---|---|---|---|
| F2 | Per-task resources translated per backend: thread caps and GPU pinning (`_tool_task_description` in smb). `gpus_per_rank` is silently ignored by Dragon in discontinuous_scaffolds | 2 | open | [pr2](2026-10-08-framework-pr2.md#f2) |
| F3 | `register_pipeline_tasks()` runs in `__init__` before subclass attributes and `self.logger` exist; crashed `22692267` | 2 (bug) | open | [pr2](2026-10-08-framework-pr2.md#f3) |
| F4 | `start()` returns no per-pipeline results; no test that the manager exits when every pipeline fails (smb 20) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f4) |
| F5 | Telemetry defaults (`checkpoint_interval`, `resource_poll_interval`, absolute path) and a bounded shutdown helper (smb 2) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f5) |
| F6 | Engine `work_dir` should be the job dir, so captured stdio (now on by default) stays with the run (smb 21) | 2 | open; more urgent now that PR 1 captures every task's stdio | [pr2](2026-10-08-framework-pr2.md#f6) |
| F7 | Document and adopt the two-backend engine layout (`compute` + `local` thread pool) in all runners | 2 | adopted everywhere, **awaiting a Delta run**. `protein_binding` and `discontinuous_scaffolds` now build `compute` + a `local` thread pool and declare their adaptive callback on it (F19). smb's `run_nonadaptive.py` is gone (merge `d571de2`): its pass-through policy is now `run_small_molecule_binding.py --nonadaptive`, which declares that body on the runner's own `local` pool, and that part is **confirmed on `23074256`** (1736/1736 callbacks on `local`; [nonadaptive-under-f19](../examples/small_molecule_binding/plans/2026-10-20-nonadaptive-under-f19.md#result)); `docs/concepts/architecture.md` carries the layout and the declaration. Row stays until a run confirms it | [pr2](2026-10-08-framework-pr2.md#f7) |
| F8 | Task-directory helper: `taskcount` + `{n}_{stage}/in,out` is repeated 7× in smb and 8× in discontinuous | 3 | open | [pr3](2026-10-08-framework-pr3.md#f8) |
| F9 | Adaptive function exceptions are logged and swallowed; the pipeline continues on stale state | 3 | open | [pr3](2026-10-08-framework-pr3.md#f9) |
| F10 | Staggered pipeline start as a manager option (smb `start_delay`; OOM on `22714785` without it) | 3 | open | [pr3](2026-10-08-framework-pr3.md#f10) |
| F11 | Stage-failure policy: `expected_outputs` / retries (smb 15, 16; protein_binding `s5`) | 4 | open, needs design and a reproducer | [deferred](2026-10-08-framework-deferred.md#f11) |
| F12 | Event-driven manager loop instead of 0.5 s polling | 4 | open, not a measured bottleneck | [deferred](2026-10-08-framework-deferred.md#f12) |
| F13 | asyncflow upstream: wrong backend name on lifecycle events, no `node_id`, `fut.cancel()` always uses the default backend, executable tasks labelled `bash`, `LocalExecutionBackend` drops a command's quoting and ignores per-task `env` | — | upstream; no framework code | [deferred](2026-10-08-framework-deferred.md#f13) |
| F15 | Dev path on asyncflow's own `LocalExecutionBackend`, plus a non-rhapsody variant of the stdio integration test: without rhapsody the suite is 115 passed / 5 skipped, and the skips are PR 1's own defaults | 2 | split. Part 2, the test variant: fixed on the PR 1 branch (`a74b71d`). Part 1, the runner swap: **blocked upstream**, because `LocalExecutionBackend` drops a command's quoting and ignores per-task `env` (F13 asks 4 and 5) | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f15) |
| F16 | Local stages as `function_task`s on a named backend, retiring `wrap_local_task` and the `impress.LocalStage` schema | 3 | open, needs decision (trace-schema break); blocked on F13's cancel bug | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f16) |

## Order

1. PR 2: F2–F7. F3 and F4 first (bug fix, then a test that may move
   smb 20 to teardown).
2. PR 3: F8–F10.
3. F11 and F12 once smb 15/16 have a reproducer; F13 goes to the asyncflow maintainers, and
   F16 and F15 part 1 wait for its answer.

**asyncflow 0.6.0 survey (2026-10-21, checkout `175cf76`).** The checkout moved from `038d52a`
(0.5.1) to 0.6.0, including a task→component handling refactor. Everything F14–F20 rely on
survives, with line numbers shifted ~23 — the table in
[adaptive-wrapper-retirement](2026-10-21-adaptive-wrapper-retirement.md#f20) lists each one.
**None of F13's asks 1, 3, 4 or 5 are fixed in 0.6.0** (lifecycle events still name the default
backend, as both F19 acceptance runs show; `_tel_executable` still prefers `executable` over
`name`; `LocalExecutionBackend` still `" ".join`s a command and still passes no `env=`), so F15
part 1 and F16 stay blocked — no need to re-check. Note the venv still has the
`radical_asyncflow-0.5.0` dist, so the test suite and the F19 acceptance runs exercised 0.5.0;
upgrading is its own decision.

Each PR also migrates the examples off the code it replaces, updates `docs/`, and adds a revision
row to each touched example's CLAUDE.md.

## Closed

Closed by PR #72 (`9a413cd`, merged 2026-10-21), each with the run that confirmed it.

- **F1**: PR 1 acceptance on Delta. Passed on `22767771`; the full-window shortfall was attributed
  to a Dragon completion stall. Doc: [pr1-delta-acceptance](2026-10-08-pr1-delta-acceptance.md#result)
- **F14**: declared, not probed, adaptive backend (`a74b71d`). Confirmed on `22927576`, then
  **superseded by F19**, which removed the `adaptive_backend=` kwarg it added. Doc:
  [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f14)
- **F17**: `pipeline.telemetry` returns only the injected handle (`a74b71d`). Confirmed on
  `22927576` (`LocalStage` 1:1). Doc: [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f17)
- **F18**: PR 1 branch-head confirmation. Passed on `22927576`: 0 failures, rfd3 337.1 / boltz
  108.0 per node-h. Doc: [pr1-head-confirmation](2026-10-15-pr1-head-confirmation.md)
- **F19**: adaptive functions passed as declared asyncflow tasks (`22a1f82`). Passed on `23062773`
  and `23065238`: every adaptive task on `local`, rfd3 / boltz within 10 % of F18, and adaptive
  share 0.28 % / 0.35 % against the restated ≤ 0.5 % bar. Its pass-through counterpart was
  confirmed on `23074256` (smb 23). Doc: [f19-delta-acceptance](2026-10-20-f19-delta-acceptance.md#rerun)
- **F20**: the declared-task contract moved into a `PipelineSetup` validator (`0446e96`). No Delta
  run, by design. Its one unrun criterion, the smb mock comparison, was run 2026-10-21 on merge
  `0cefeb2` of `main` into `smb-benchmark-f19`. In all three modes (adaptive, `--nonadaptive`,
  `--nonadaptive --selection first`), the stage sequences and decision lines were identical to
  the pre-merge head `fd01231`, apart from the scratch run path. Adaptive was also identical to
  PR 1's head `4011f0d`. pytest 128 passed / 0 skipped with rhapsody present. Doc:
  [adaptive-wrapper-retirement](2026-10-21-adaptive-wrapper-retirement.md#result)

## Conventions

- Cite the job ID behind every claim, as the example backlogs do.
- A framework default changes every example at once. State the behaviour change in the PR body and
  in `docs/concepts/architecture.md`, and give an opt-out.
- Keep PR #60's rule: the caller owns the `WorkflowEngine`; the manager never creates or shuts it down.
