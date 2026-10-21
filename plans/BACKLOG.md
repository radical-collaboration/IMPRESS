# IMPRESS framework — backlog tracker

Open work for the framework itself (`src/impress/`): lifting fixes proven in the examples into
`ImpressBasePipeline`, `ImpressManager` and the asyncflow interface, so each example stops
rediscovering them. One line per item; details live in the linked doc. Keep `Status` current, and
delete rows once the change is merged **and** a run confirms it.

Example-specific work is tracked separately, e.g.
[small_molecule_binding/plans/BACKLOG.md](../examples/small_molecule_binding/plans/BACKLOG.md)
(cited below as "smb N").

Origin: the categorised, ranked plan of 2026-10-08. PR 1 (Tier 1) is on branch
`framework-defaults-pr1` (`7327c84`): stdio captured by default, `{pipeline}:{stage}` task labels,
stderr tail on failure, `impress.LocalStage` for local tasks, `logged_command`, adaptive functions
off the event loop, and the `DragonExecutionBackendV3` import fix.

Tier = (measured impact or failure prevented) × (examples that benefit) ÷ effort; 1 is highest.

F14–F17 come from the 2026-10-15 review of PR 1 against asyncflow 0.5.1's own patterns
(`examples/04-concurrent_backends.py`): where the engine now has an idiom, the escape goes
back. See [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md).

| # | Item | Tier | Status | Doc |
|---|---|---|---|---|
| F1 | PR 1 has not run on Delta. Acceptance: a 1-node, 1-hour run at 8 pipelines/GPU, compared with `22718758` | 1 | **passed** on `22767771` (2026-10-15): labels, local stages, adaptive offload, stderr tails and storage all pass. Full-window rfd3 264.3/node-h (−16 %) is attributed to a 76 s Dragon completion stall beside an smb 16 failure; before the stall the rate was +6 %. F14, F17 and F15 part 2 are now on the branch (`a74b71d`). Next: merge PR 1, then delete this row | [pr1-delta-acceptance](2026-10-08-pr1-delta-acceptance.md#result) |
| F2 | Per-task resources translated per backend: thread caps and GPU pinning (`_tool_task_description` in smb). `gpus_per_rank` is silently ignored by Dragon in discontinuous_scaffolds | 2 | open | [pr2](2026-10-08-framework-pr2.md#f2) |
| F3 | `register_pipeline_tasks()` runs in `__init__` before subclass attributes and `self.logger` exist; crashed `22692267` | 2 (bug) | open | [pr2](2026-10-08-framework-pr2.md#f3) |
| F4 | `start()` returns no per-pipeline results; no test that the manager exits when every pipeline fails (smb 20) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f4) |
| F5 | Telemetry defaults (`checkpoint_interval`, `resource_poll_interval`, absolute path) and a bounded shutdown helper (smb 2) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f5) |
| F6 | Engine `work_dir` should be the job dir, so captured stdio (now on by default) stays with the run (smb 21) | 2 | open; more urgent now that PR 1 captures every task's stdio | [pr2](2026-10-08-framework-pr2.md#f6) |
| F7 | Document and adopt the two-backend engine layout (`compute` + `local` thread pool) in all runners | 2 | adopted everywhere, **awaiting a Delta run**. `protein_binding` and `discontinuous_scaffolds` now build `compute` + a `local` thread pool and declare their adaptive callback on it (F19). smb's `run_nonadaptive.py` is gone (merge `d571de2`): its pass-through policy is now `run_small_molecule_binding.py --nonadaptive`, which declares that body on the runner's own `local` pool, so smb's part waits on the pass-through run in [nonadaptive-under-f19](../examples/small_molecule_binding/plans/2026-10-20-nonadaptive-under-f19.md); `docs/concepts/architecture.md` carries the layout and the declaration. Row stays until a run confirms it | [pr2](2026-10-08-framework-pr2.md#f7) |
| F8 | Task-directory helper: `taskcount` + `{n}_{stage}/in,out` is repeated 7× in smb and 8× in discontinuous | 3 | open | [pr3](2026-10-08-framework-pr3.md#f8) |
| F9 | Adaptive function exceptions are logged and swallowed; the pipeline continues on stale state | 3 | open | [pr3](2026-10-08-framework-pr3.md#f9) |
| F10 | Staggered pipeline start as a manager option (smb `start_delay`; OOM on `22714785` without it) | 3 | open | [pr3](2026-10-08-framework-pr3.md#f10) |
| F11 | Stage-failure policy: `expected_outputs` / retries (smb 15, 16; protein_binding `s5`) | 4 | open, needs design and a reproducer | [deferred](2026-10-08-framework-deferred.md#f11) |
| F12 | Event-driven manager loop instead of 0.5 s polling | 4 | open, not a measured bottleneck | [deferred](2026-10-08-framework-deferred.md#f12) |
| F13 | asyncflow upstream: wrong backend name on lifecycle events, no `node_id`, `fut.cancel()` always uses the default backend, executable tasks labelled `bash`, `LocalExecutionBackend` drops a command's quoting and ignores per-task `env` | — | upstream; no framework code | [deferred](2026-10-08-framework-deferred.md#f13) |
| F14 | Adaptive backend declared (`adaptive_backend=`), not probed out of `flow._backends` (`impress_manager.py:162-164`); today an engine whose pool is not named `local` silently falls back to a thread. A misnamed backend would shut the whole engine down at submit, so `start()` validates the name | 2 | fixed on the PR 1 branch (`a74b71d`), confirmed on Dragon by `22927576` (F18); not yet merged. **Superseded by F19**, which drops the `adaptive_backend=` kwarg this item added and moves the declaration to the function itself; F14's principle (declared, never discovered) is what F19 completes | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f14) |
| F15 | Dev path on asyncflow's own `LocalExecutionBackend`, plus a non-rhapsody variant of the stdio integration test: without rhapsody the suite is 115 passed / 5 skipped, and the skips are PR 1's own defaults | 2 | split. Part 2, the test variant: fixed on the PR 1 branch (`a74b71d`). Part 1, the runner swap: **blocked upstream**, because `LocalExecutionBackend` drops a command's quoting and ignores per-task `env` (F13 asks 4 and 5) | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f15) |
| F16 | Local stages as `function_task`s on a named backend, retiring `wrap_local_task` and the `impress.LocalStage` schema | 3 | open, needs decision (trace-schema break); blocked on F13's cancel bug | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f16) |
| F17 | Drop `pipeline.telemetry`'s `flow._telemetry` fallback (`impress_pipeline.py:101`); the manager already injects the public handle | 3 | fixed on the PR 1 branch (`a74b71d`), confirmed on Dragon by `22927576` (F18: `LocalStage` 1:1); not yet merged | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f17) |
| F18 | Confirm the PR 1 branch head on Delta: F14's `start()` check and declared `local` routing, F17's telemetry injection, and F1's throughput caveat without an injected failure. Same shape as `22767771` | 1 | **passed** on `22927576` (2026-10-15): 0 failures; adaptive 2043/2043 on `local` at 0.31 %; `LocalStage` 1:1; rfd3 337.1/node-h (+6.8 % vs `22718758`), boltz 108.0 (+14.5 %). Next: push and merge PR 1, then delete this row | [pr1-head-confirmation](2026-10-15-pr1-head-confirmation.md) |
| F19 | Adaptive functions are passed to the manager as declared asyncflow tasks. `ImpressManager` chose between three paths (loop / `asyncio.to_thread` / named backend) from two constructor flags; asyncflow's idiom is that the author declares routing at the definition site (`examples/04-concurrent_backends.py`), which F14 adopted for a manager kwarg but not for the function. `_invoke_adaptive_fn` is now one `await`; `_run_to_completion`, `_maybe_await`, `_backend_task`, `_check_adaptive_backend`, `adaptive_offload` and `adaptive_backend` are deleted, and `submit_new_pipelines()` raises `TypeError` for an `adaptive_fn` that is not a task. Also fixes a latent gap: the old pass-through branch never sent `workflow_id`, so a caller-declared task lost its `p<N>:adaptive` label | 2 | **passed** on `23062773` + `23065238` (2026-10-20). `23062773`: 1604/1604 adaptive on `local` at 0.28 %, 3239/3239 labelled, `LocalStage` 1:1, 0 adaptive failures. Throughput unscored: 11 of 32 pipelines killed by backend faults (2 smb 16, one 9-pipeline Dragon `ProcessGroup` burst, smb 26 on `smb-nonadaptive-benchmark`); per live pipeline-h within noise of F18. Rerun `23065238`: rfd3 306.2 / boltz 108.9 per node-h (−9.2 % / +0.8 % vs F18), pass; 1 smb 26 loss. Adaptive share 0.35 % (0.28 % on `23062773`; per-call cost unchanged, p50 0.003 s), accepted against a restated ≤ 0.5 % bar. Next: push and merge PR 1, then delete this row ([f19-delta-acceptance](2026-10-20-f19-delta-acceptance.md#rerun)). Verified offline: 125/125 tests pass, including a real-engine test asserting the callback ran on the declared backend's own thread pool; the smb mock run gives a byte-identical 496-event sequence before and after (124 adaptive calls, 0 failures, every per-stage `next_step` the same). **Deviates from the Conventions rule below:** it removes the opt-out rather than adding one, deliberately — the opt-out *was* the fallback. A caller who needs loop-bound awaits calls their logic from `pipeline.run()` instead of registering an `adaptive_fn`. Acceptance: same shape as F18 (`22927576`) | [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#f19) |

## Order

1. F1 (passed), then F14, F17, F15 part 2 and the `stdio.py` docstring on the PR 1 branch
   (done, `a74b71d`), then F18 on Delta (passed, `22927576`), then F19 (`22a1f82`; passed on `23062773` +
   `23065238`), then push and merge PR 1.
   - F14 changes PR 1's own new API, so it should not reach `main` in its first form.
   - The rest is a one-line deletion, tests or docs. None of it changes the Delta path F1
     measured ([pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md#order-revised-2026-10-15)).
2. PR 2: F2–F7. F3 and F4 first (bug fix, then a test that may move
   smb 20 to teardown).
3. PR 3: F8–F10.
4. F11 and F12 once smb 15/16 have a reproducer; F13 goes to the asyncflow maintainers, and
   F16 and F15 part 1 wait for its answer.

Each PR also migrates the examples off the code it replaces, updates `docs/`, and adds a revision
row to each touched example's CLAUDE.md.

## Conventions

- Cite the job ID behind every claim, as the example backlogs do.
- A framework default changes every example at once. State the behaviour change in the PR body and
  in `docs/concepts/architecture.md`, and give an opt-out.
- Keep PR #60's rule: the caller owns the `WorkflowEngine`; the manager never creates or shuts it down.
