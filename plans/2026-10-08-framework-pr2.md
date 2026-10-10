# Framework PR 2 (Tier 2): resources, init order, results, lifecycle, run dir

**Status:** open, design only · **Items:** F2–F7 · **Depends on:** PR 1 merged (F1)

Each section gives the evidence, the change, and the test. File references are to `main` plus PR 1.

<a id="f2"></a>
## F2 — Per-task resources, translated per backend

**Evidence.** smb's `_tool_task_description(threads, gpu)` (`small_molecule_binding.py`, "Per-task environment" section) encodes behaviour that took several jobs to find:
- Concurrent `env` *replaces* the environment, so the caps must be merged over `os.environ`.
- Dragon's `process_template.env` is *merged* on the target node, so only the delta is sent.
- `OMP_WAIT_POLICY=PASSIVE` stops idle OpenMP spin.
- On Dragon, GPU pinning needs `Policy(gpu_affinity=[g])`, because a template `CUDA_VISIBLE_DEVICES` is overwritten (`22692293`).
- On Concurrent, `CUDA_VISIBLE_DEVICES` works.
- Uncapped `boltz` took ~30 cores of the primary (`22670942`).
- `discontinuous_scaffolds` passes `{"gpus_per_rank": 1}`, an RP key that Dragon ignores, so its GPU tasks get no placement at all.

**Change.**
- Add `impress.utils.resources.task_description(flow, threads=None, gpu=None, env=None) -> dict`. It returns the dict for the engine's default backend (or a named one): Concurrent, Dragon, or RP (`cores_per_rank`/`gpus_per_rank`). For an unknown backend it passes `env` through unchanged and logs a warning.
- Expose it as `ImpressBasePipeline.task_resources(...)`.
- Migrate the three smb call sites and discontinuous's `gpus_per_rank`.

**Test.**
- Unit: one case per backend type, using backend stubs selected by class name, so Dragon need not be importable.
- smb mock run unchanged.

<a id="f3"></a>
## F3 — Registration order in `__init__`

**Evidence.**
- `ImpressBasePipeline.__init__` calls `register_pipeline_tasks()` before subclasses have set their attributes, and before `self.logger` is assigned.
- Job `22692267` crashed 26 s in, because `gpu_index` was set after `super().__init__()`.
- smb now has to set attributes *before* calling `super()`, which is a trap for every new pipeline.

**Change.**
- Assign `self.logger` first in `__init__`.
- Move `register_pipeline_tasks()` into `_ensure_registered()`. The manager calls it just before `run()`, and it is idempotent, so calling it directly still works.
- Keep a deprecation-free path: if a subclass already calls `auto_register_task` itself, nothing changes.

**Test.**
- Update `tests/unit/test_pipeline_base.py`.
- Add a test pipeline that sets an attribute *after* `super().__init__()` and uses it in a task's `task_description`.

<a id="f4"></a>
## F4 — Per-pipeline results, and exit when all fail

**Evidence.**
- smb 20: `22726386` held 8 nodes for ~27 node-hours after its last pipeline failed, and never wrote `runner_status`.
- Reading `ImpressManager.start()`, the loop should exit once `pipeline_tasks` is empty. So the hang may be in teardown (F5 / smb 2), not in the manager. That has not been confirmed.

**Change.**
- First write the test: a mock in which every pipeline raises must make `start()` return within 5 s.
- Then make `start()` return `{name: None | exception}` and log a final `N ok / M failed` line.
- Runners derive `runner_status` from the result rather than relying on reaching the last line.

**Test.**
- The test above, plus one with mixed outcomes.
- If the test already passes on `main`, record in smb 20 that the 27 node-hours were teardown.

<a id="f5"></a>
## F5 — Telemetry defaults and a bounded shutdown

**Evidence.**
- smb's runner settings beat both the asyncflow defaults and `protein_binding`'s:
  - `checkpoint_interval=300`: without it, a wall-clock kill loses the 128 KB-buffered file.
  - `resource_poll_interval=15`: at 5 s, ResourceUpdate was 69 % of the file.
  - An absolute `checkpoint_path`.
- `telemetry.stop()` must run before `flow.shutdown()` and in a `finally`.
- smb 2: `flow.shutdown()` hung for 60 min on `22491438`, ~64 GPU-h for nothing.

**Change.**
- `ImpressManager` applies those telemetry defaults under any user-supplied `telemetry_config` keys. PR 1 already gives pipelines `pipeline.telemetry`.
- Add `impress.utils.lifecycle.shutdown(flow, telemetry=None, timeout=300)`:
  - stops telemetry in its own `try`;
  - then runs `asyncio.wait_for(flow.shutdown(), timeout)`;
  - logs `teardown started` / `complete` / `timed out`;
  - raises `TeardownTimeout` on expiry.
- The caller still owns the engine.
- All runners call it from `finally`.

**Test.**
- Unit: a fake `flow.shutdown` that never returns makes the helper raise within the timeout, and `stop()` was still called first.
- Delta: confirm with the next run that reaches completion.

<a id="f6"></a>
## F6 — Engine `work_dir` in the job dir

**Evidence.**
- asyncflow puts captured stdio in `{work_dir}/{engine uid}/`, and `work_dir` defaults to the cwd.
- On `22726386` that was the submit dir: 16k files and 427 MB in `asyncflow.session.*`, split away from `IMPRESS_WORK_DIR` (smb 21).
- PR 1 turned capture on for every executable task, so this now applies to every example.

**Change.**
- Runners pass `WorkflowEngine.create(..., work_dir=<run dir>)`.
- Document it next to the capture default in `docs/concepts/architecture.md`.
- Consider a manager warning when capture is on and `flow.work_dir` is the process cwd.

**Test.** The integration test from PR 1 already asserts that files land under `work_dir`. Add a check in each runner.

<a id="f7"></a>
## F7 — Two-backend engine layout everywhere

**Evidence.**
- PR 1 runs adaptive functions on a backend named `local` when there is one, and otherwise in `asyncio.to_thread`.
- Only smb's runner builds that backend. protein_binding and discontinuous fall back to `to_thread`, so their adaptive calls are unbounded and invisible in telemetry.
- `docs/concepts/architecture.md` now describes the `local` backend.

**Change.**
- Add a short "Recommended engine" section to the architecture doc: `compute` default plus a `local` thread pool sized to the pipeline count.
- Switch protein_binding and discontinuous runners to it.
- discontinuous's adaptive function runs `subprocess.run` (blocking), so it benefits directly.

**Test.** Each runner's telemetry shows `p<N>:adaptive` with `target_backend=local`.
