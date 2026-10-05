# asyncflow telemetry: wrong `backend` on lifecycle events; `node_id` never set on task events

**Component:** radical.asyncflow 0.5.1 (`workflow_manager.py`) with rhapsody 0.5.0 telemetry
**Severity:** medium. Routing is correct, but the trace misattributes multi-backend tasks and cannot map a task to a node.
**Status:** diagnosed, not reported upstream, not patched locally
**Evidence:** telemetry from smoke job `22669434`, at `logs/22669434/telemetry/asyncflow.session.6e362266.1791173482.telemetry.jsonl`. The engine was `backend=[DragonExecutionBackend(name="compute"), ConcurrentExecutionBackend(ThreadPoolExecutor, name="local")]`, with `adaptive_decision` registered as `flow.function_task(backend="local")`.

Paths: `AF = radical.asyncflow/src/radical/asyncflow`, `RH = rhapsody/src/rhapsody`. The installed copies match these checkouts.

## Issue 1 — Started/Completed/Failed/Canceled report the default backend

**What we saw.** A task routed to `local` reports `"backend": "local"` on TaskQueued and TaskSubmitted, but `"compute"` on TaskStarted and TaskCompleted.

| Event | Count | `backend` |
|---|---|---|
| TaskCreated | 162 | all `compute` |
| asyncflow.TaskResolved | 162 | all `compute` |
| TaskQueued | 162 | 85 `compute` / 77 `local` |
| TaskSubmitted | 162 | 85 `compute` / 77 `local` |
| TaskStarted | 162 | all `compute` |
| TaskCompleted | 154 | all `compute` |
| TaskFailed | 7 | all `compute` |

**Cause.**
- Every task event goes through `_emit()` (`AF/workflow_manager.py:244–280`), which sets `backend=backend or self._default_backend_name` (`:276`). The default is `backend[0].name`, set at `:94`.
- Only the TaskQueued (`:1248–1257`) and TaskSubmitted (`:1357–1367`) calls pass the task's `target_backend`.
- These calls omit it and fall back to `"compute"`:
  - In `task_callbacks`: TaskCompleted (`:1672–1679`), TaskStarted (`:1689–1695`), TaskCanceled (`:1704–1711`), TaskFailed (`:1720–1728`).
  - TaskCreated (`:812–821`) and TaskResolved (`:825+`).
- The routing itself is correct: `:1369–1384` submits to `self._backends["local"]`.

**Intent.** This is a bug, not a design choice:
- `RH/telemetry/events.py:43` defines `backend` as "Name of the execution backend that produced the event".
- rhapsody's own Session bridge stamps every event with the task's routed backend (`RH/telemetry/manager.py:709–870`).
- `docs/telemetry/reference.md:65` says TaskCreated should carry `backend=""` before routing.

**Fix.**
- Pass `backend=comp_desc.get("target_backend")` in the four `task_callbacks` emits (`:1673`, `:1690`, `:1705`, `:1721`). `comp_desc = comp["description"]` is already in scope there.
- Do the same in TaskCreated and TaskResolved, or pass `""` per the reference doc.

**Impact on us.**
- Per-backend breakdowns of task duration or failures are wrong.
- Every `local` adaptive decision is counted as a `compute` task.
- Our `_on_task_event` subscriber in `run_small_molecule_binding.py` labels by `workflow_id`, not by backend, so it is unaffected.

## Issue 2 — `node_id` is null on every task lifecycle event

**What we saw.**
- `node_id` is null on all TaskSubmitted/Started/Completed/Failed events, including Dragon tasks that ran on two different nodes.
- We confirmed those tasks were on both nodes by sampling `/proc` on each node during the run.

**Schema and intent.**
- `RH/telemetry/events.py:58` defines `node_id: str | None = None` on `BaseEvent`. The docstring (`:45`) says "Node/worker identifier, None when not applicable", and `docs/telemetry/reference.md:29` says "Hostname or worker address".
- All doc usage concerns ResourceUpdate, which joins per-GPU to per-node on `(session_id, node_id, event_time)`: `events.py:168–200`, `faq.md:78,95`, `quickstart.md:71,117`, `integrations.md:188,277,298,336–338`.
- Nothing documents `node_id` on task events.

**Who sets it today: only the resource adapters.**
- Dragon adapter: `RH/telemetry/adapters/dragon.py:274`, `374`, `408`, `425`. It takes the host from a per-node worker placed with `hostname_policies()`.
- Concurrent adapter: `adapters/concurrent.py:62` (`socket.gethostname()`).
- Dask adapter: `adapters/dask.py:88,106`.
- In our file, only ResourceUpdate has `node_id`:
  - `compute` on `gpub060` (220 per-node samples plus 220 for each of GPUs 0–3).
  - `compute` on `gpub036` (150 plus 150 for each GPU).
  - `local` on `gpub060` (220 plus 220 for each GPU). The concurrent adapter re-measures the head node that Dragon also measures, so gpub060 is reported twice under two backend names.

**Why task events can't carry it.**
- asyncflow's `_emit()` has no `node_id` parameter.
- The rhapsody Dragon backend never records where a task ran:
  - It reads only the return value (`RH/backends/execution/dragon.py:236`) and stdout/stderr (`:265–271`).
  - `_deliver_batch` (`:285–309`) adds only `return_value`, `stdout`, `stderr` and `exception`.
  - RUNNING is reported at dispatch time inside `submit_tasks` (`:344`), before Dragon has placed the process. So TaskStarted is neither placed nor a true start time.
- The concurrent backend adds no host either (`concurrent.py:247,250`).

**What filling it requires.**
1. The backend records the execution host in the task dict, e.g. `task["node_id"]`:
   - Concurrent: `socket.gethostname()`.
   - Dragon: wrap the target so it reports its hostname, or look up the node from the process puid. Which Dragon API offers the latter is not yet checked.
   - Either way it lands in `_deliver_batch`, so it is available for Completed/Failed. TaskStarted needs a true started callback.
2. asyncflow passes `node_id=task_dct.get("node_id")` in the `task_callbacks` emits.
3. Optionally, rhapsody's Session bridge (`_on_task_state_change`) does the same.

**Impact on us.**
- We cannot attribute tasks to nodes from telemetry, so per-node load and placement analyses need `/proc` sampling.
- The BACKLOG item 6 acceptance check "tasks on both nodes" had to be done that way.

## Workaround until fixed

- **Placement:** sample `/proc/<pid>/environ` and `cmdline` on each node during the run.
- **Per-backend counts:** take them from TaskSubmitted only.
