# Tool stages delegated to asyncflow/rhapsody instead of the runner

**Severity:** medium (architecture; one latent GPU defect) · **Status:** implemented on `scaling-wide`, verified offline, not yet run on Delta
**Evidence:** branch history `976c0cf`..`90d6be3`, plus `d8c1b4b` and `8ddeb10` before it

## Why

Two branches added compute management to the example runner, which is the asyncflow/rhapsody stack's job:

| Commit | Runner workaround | What it was compensating for |
|---|---|---|
| `976c0cf` | `OMP_*` caps written into the runner's `os.environ`, sized `sched_getaffinity // (2*n_pipelines)` | 5 `local_task=True` stages spawned their own subprocesses on the Dragon primary and inherited the runner's env |
| `c0698fe` | `_timed_local` + `impress.LocalStage` on all 11 local stages | those stages bypassed asyncflow, so its telemetry could not see them |
| `90d6be3` | `adaptive_decision` → `asyncio.to_thread` | the sync callback ran on the shared event loop |

**Origin of the split.**
- `d8c1b4b` (2026-08-29) moved every task to `local_task=True` with no stated reason. The nearest motive in history is the Dragon 0.14.1 false-FAILED race (`cc365f3`, `dragon_bug_report.txt`, since deleted).
- `8ddeb10` moved only `rfd3` back.
- The "Dragon bottleneck" attribution does not survive the data:
  - `22491438` scaled at 98%.
  - The `22534628` collapse was the blocked event loop, not Dragon.

**Latent defect found while doing this.** `mpnn` was a local task, but LigandMPNN selects CUDA when it is available (`LigandMPNN/run.py:38`). So every pipeline's MPNN ran on the primary node's GPUs, outside any scheduler.

## What changed

- **`mpnn`, `packmin`, `fastrelax`, `filter_shape`, `filter_energy`** are asyncflow executable tasks on the default `compute` backend. They follow the existing `rfd3`/`boltz` pattern: the coroutine does `taskcount`, task dirs and input prep, then returns the command.
- **Per-task thread caps** come from `_tool_task_description()` as a `task_description` default. The env format depends on the backend:
  - Dragon: `process_template.env`, which local services merges into the target node's env (`dragon/localservices/server.py:1539`).
  - Concurrent: `env`, which replaces the environment, so it is merged over `os.environ`.
- **The runner's `os.environ` thread-cap block is gone.**
- **`adaptive_decision`** runs as `flow.function_task(backend="local")` on a `ConcurrentExecutionBackend(ThreadPoolExecutor)`.
- **Per-stage logs** are kept at `{taskdir}/<stage>.log` via `scripts/run_logged.sh`.
- **`mpnn.sh` and `filter_energy.sh`** gain the `VIRTUAL_ENV` guard.
- **Kept:**
  - The `--n-pipelines`/`--work-dir` argv plumbing. It works around a `dragon -w ssh` launcher limit, not compute delegation.
  - The `_read_fasta_seq` memo.

## Validation done (offline, real asyncflow 0.5.1 / rhapsody 0.5.0)

- **Stub-tool harness** on `[compute=Concurrent(ProcessPool), local=Concurrent(ThreadPool)]`:
  - Each stage saw its own caps: `mpnn` `OMP=4`, Rosetta stages `OMP=1`, both with `OMP_WAIT_POLICY=PASSIVE`. The runner's own env has none.
  - Logs were at the old paths.
  - MPNN's empty `fixed_residues` argument survived quoting.
  - `filter_shape` still reuses the `fastrelax` taskcount.
  - A failing tool raised `RuntimeError`, and its stderr carried the wrapper's log tail.
- **Manager end-to-end** (3 mock pipelines, telemetry on):
  - 144/144 adaptive decisions were submitted and completed as asyncflow tasks, with `"backend": "local"`.
  - Zero failures; both backends shut down cleanly.
- **`run_test_small_molecule_binding.py`** passes (exit 0).

## Acceptance test — still required on Delta

1. **2-node smoke** (8 pipelines, small `max_tasks`):
   - `mpnn`/`packmin`/`fastrelax`/`filter_shape` tasks appear on **both** nodes. Check the telemetry `node_id` per `workflow_id`.
   - The primary's CPULoad drops relative to `22491438`.
   - `nvidia-smi` on the primary shows no MPNN processes outside Dragon.
2. **Env check:** temporarily `echo OMP_NUM_THREADS` from `fastrelax.sh`/`mpnn.sh`. Confirm the caps arrive on a remote node after the `dragon -w ssh` hop.
3. **Throughput gate:** rfd3/pipeline/h at or above the 4-node baseline (11.46), with no rise in `TaskFailed`, before the next 8-node campaign.

## Risks

- **False-FAILED race exposure.** More tasks now go through Dragon, so there is more exposure to the 0.14.1 race. It did not manifest in `22534628` (zero task failures in 63,589 log lines).
- **Task rate.** It is low (~32 × 300 tasks over ~7 h ≈ 0.4/s), well within the Dragon monitor thread's capacity.
- **Fallback.** If Dragon placement of the PyRosetta stages misbehaves, add `backend="local"` to just those registrations. They stay asyncflow-managed with per-task env. Keep `mpnn` on `compute`, because it is a GPU tool.
- **Process-mode tasks receive no `gpu_affinity` from Dragon.** So `rfd3`, `boltz` and now `mpnn` each see every GPU on their node. That was already true of `rfd3`/`boltz`, and is unchanged.

## Upstream items (not patched here)

| Repo | Item |
|---|---|
| radical.asyncflow | Cancelling a task routed to a non-default backend calls the *default* backend's `cancel_task` (`workflow_manager.py:870`). The task state map comes only from the default backend (`:116`). This is harmless today because both backends register the default states. |
| rhapsody | The Dragon backend has no `cores_per_rank`/threads key; caps only go through `process_template.env`. `shutdown()` blocks the loop and never cancels in-flight Batch tasks, which is a plausible contributor to the teardown hang (item 2). |
| IMPRESS | `ImpressManager._run_adaptive_fn` could dispatch sync callbacks through a flow backend itself, so other examples get this without wiring it. |
