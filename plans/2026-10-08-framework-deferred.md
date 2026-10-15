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

PR 1 also relies on private engine attributes (`_backends`, `_default_backend_name`, `_telemetry`, `backend._work_dir`). Ask upstream for public accessors: the backend table (or a `has_backend(name)`), the telemetry manager, and a task's stdio paths. The guarded lookups in `impress.utils.stdio` and `ImpressManager._local_backend_task` can then be replaced.

**Third ask, added 2026-10-15: label an executable task after its decorated function.** `comp_desc["executable"]` is `shlex.split(cmd)[0]` (`workflow_manager.py:654-660`), and `_tel_executable` prefers it over `comp_desc["name"]`, which already holds the function name (`:739-741`). Every IMPRESS tool stage therefore appears as `bash` — `logged_command()` guarantees it — which is why each call has to carry `workflow_id="{pipeline}:{stage}"` purely as a label. Until this is fixed, `flow.workflow_scope()` cannot be adopted for trace hierarchy: a scope assigns one id to every task inside it, and a call-time `workflow_id` overrides the ContextVar (`:716-718`), so the two cannot both be used. See [pattern-rollback](2026-10-15-asyncflow-pattern-rollback.md) ("Keep").

**Fourth ask, added 2026-10-15: keep a command's quoting on `LocalExecutionBackend`.** The engine splits the command an executable task returns into `executable` + `arguments` (`workflow_manager.py:654-661`). The backend's default shell mode re-joins them with `" ".join([executable] + arguments)` (`backends.py:318`), so `bash -c 'echo a; echo b'` runs as `bash -c echo a; echo b`. Every `logged_command()` stage returns that shape, so asyncflow's own backend cannot run IMPRESS's tool stages. The fix is `shlex.join`. This blocks [F15 part 1](2026-10-15-asyncflow-pattern-rollback.md#f15); reproduced by `tests/integration/test_task_defaults_local.py` with a `bash -c` command (stdout `'\n'` instead of `'out-line\n'`).

**Correction, 2026-10-15:** `fut.task` was listed above as a private attribute. It is not — asyncflow sets it on every component future (`setattr(comp_fut, comp_type, comp_desc)`, `workflow_manager.py:756`) and consumes it in its own public dependency resolution (`:915`). It is undocumented, not private, and `impress.utils.stdio` can keep using it. The telemetry-manager accessor also stops being needed if F17 removes the fallback that wants it.
