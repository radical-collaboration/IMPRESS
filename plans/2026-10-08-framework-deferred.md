# Framework, deferred (Tier 4) and upstream items

**Status:** open · **Items:** F11–F13

<a id="f11"></a>
## F11 — Stage-failure policy

**Evidence.**
- smb 15: after a `TaskFailed`, the pipeline dies with `'NoneType' object is not subscriptable` (`22714866` p7/p15) instead of retrying or escalating.
- smb 16: rfd3 was reported failed after writing all its outputs.
- protein_binding's `run()` already hand-codes the same workaround for `s5`: on failure it checks for the CSV and treats its presence as success.

**Proposed.** `auto_register_task(..., expected_outputs=callable, retries=0)`:
- If a task fails but `expected_outputs()` returns true, log a warning and resolve as success.
- Otherwise retry up to `retries` times, then raise.

**Why deferred.** smb 16 has not recurred in staggered runs, and smb 15 is a pipeline-logic bug as much as a framework gap. Design this against a reproducer, not a guess.

<a id="f12"></a>
## F12 — Event-driven manager loop

**Evidence.** `ImpressManager.start()` polls every 0.5 s. Adaptive latency was p99 0.071 s at 32 pipelines (`22701168`), so polling is not a measured bottleneck.

**Proposed.** Replace the polling with `asyncio.wait` on the pipeline tasks, plus an `asyncio.Event` that `run_adaptive_step()` and `submit_child_pipeline_request()` set.

**Why deferred.** It rewrites the loop that F4 and F9 also touch. Do it with them or after them, never before.

<a id="f13"></a>
## F13 — asyncflow upstream issues (no framework code)

These are written up in `examples/small_molecule_binding/plans/upstream/asyncflow-telemetry-backend-and-node-id.md` and `.../2026-10-04-backend-delegation.md` ("Upstream items"). radical.asyncflow 0.5.1:
- Started/Completed/Failed/Canceled events carry the default backend's name, not the task's.
- `node_id` is never set on task events, so placement cannot be read from a trace.
- `fut.cancel()` calls the *default* backend's `cancel_task`, even for tasks routed elsewhere.
- Since PR 1, adaptive tasks run on `local`. A `kill_parent` cancel of a pipeline mid-adaptive would hit this bug.

PR 1 also relies on private engine attributes (`_backends`, `_default_backend_name`, `_telemetry`, `backend._work_dir`, `fut.task`). Ask upstream for public accessors: the backend table, the telemetry manager, and a task's stdio paths. The guarded lookups in `impress.utils.stdio` and `ImpressManager._local_backend_task` can then be replaced.
