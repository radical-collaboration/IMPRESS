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

| # | Item | Tier | Status | Doc |
|---|---|---|---|---|
| F1 | PR 1 has not run on Delta. Acceptance: a 1-node, 1-hour run at 8 pipelines/GPU, compared with `22718758` | 1 | open; blocks merging PR 1 | [pr1-delta-acceptance](2026-10-08-pr1-delta-acceptance.md) |
| F2 | Per-task resources translated per backend: thread caps and GPU pinning (`_tool_task_description` in smb). `gpus_per_rank` is silently ignored by Dragon in discontinuous_scaffolds | 2 | open | [pr2](2026-10-08-framework-pr2.md#f2) |
| F3 | `register_pipeline_tasks()` runs in `__init__` before subclass attributes and `self.logger` exist; crashed `22692267` | 2 (bug) | open | [pr2](2026-10-08-framework-pr2.md#f3) |
| F4 | `start()` returns no per-pipeline results; no test that the manager exits when every pipeline fails (smb 20) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f4) |
| F5 | Telemetry defaults (`checkpoint_interval`, `resource_poll_interval`, absolute path) and a bounded shutdown helper (smb 2) | 2 | open | [pr2](2026-10-08-framework-pr2.md#f5) |
| F6 | Engine `work_dir` should be the job dir, so captured stdio (now on by default) stays with the run (smb 21) | 2 | open; more urgent now that PR 1 captures every task's stdio | [pr2](2026-10-08-framework-pr2.md#f6) |
| F7 | Document and adopt the two-backend engine layout (`compute` + `local` thread pool) in all runners | 2 | partly done: PR 1 documents the `local` backend in `docs/concepts/architecture.md`; runners other than smb have no `local` backend | [pr2](2026-10-08-framework-pr2.md#f7) |
| F8 | Task-directory helper: `taskcount` + `{n}_{stage}/in,out` is repeated 7× in smb and 8× in discontinuous | 3 | open | [pr3](2026-10-08-framework-pr3.md#f8) |
| F9 | Adaptive function exceptions are logged and swallowed; the pipeline continues on stale state | 3 | open | [pr3](2026-10-08-framework-pr3.md#f9) |
| F10 | Staggered pipeline start as a manager option (smb `start_delay`; OOM on `22714785` without it) | 3 | open | [pr3](2026-10-08-framework-pr3.md#f10) |
| F11 | Stage-failure policy: `expected_outputs` / retries (smb 15, 16; protein_binding `s5`) | 4 | open, needs design and a reproducer | [deferred](2026-10-08-framework-deferred.md#f11) |
| F12 | Event-driven manager loop instead of 0.5 s polling | 4 | open, not a measured bottleneck | [deferred](2026-10-08-framework-deferred.md#f12) |
| F13 | asyncflow upstream: wrong backend name on lifecycle events, no `node_id`, `fut.cancel()` always uses the default backend | — | upstream; no framework code | [deferred](2026-10-08-framework-deferred.md#f13) |

## Order

1. F1, then merge PR 1.
2. PR 2: F2–F7. F3 and F4 first (bug fix, then a test that may move smb 20 to teardown).
3. PR 3: F8–F10.
4. F11 and F12 once smb 15/16 have a reproducer; F13 goes to the asyncflow maintainers.

Each PR also migrates the examples off the code it replaces, updates `docs/`, and adds a revision
row to each touched example's CLAUDE.md.

## Conventions

- Cite the job ID behind every claim, as the example backlogs do.
- A framework default changes every example at once. State the behaviour change in the PR body and
  in `docs/concepts/architecture.md`, and give an opt-out.
- Keep PR #60's rule: the caller owns the `WorkflowEngine`; the manager never creates or shuts it down.
