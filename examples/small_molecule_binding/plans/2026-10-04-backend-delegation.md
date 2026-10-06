# Tool stages delegated to asyncflow/rhapsody instead of the runner

**Severity:** medium (architecture; one latent GPU defect) · **Status:** implemented on `scaling-wide` (`59a9e20`, plus `rfd3`/`boltz` caps 2026-10-05); 2-node smoke (`22670942`), 4-node 1 h (`22675825`) and post-merge gate (`22684833`) all passed on Delta with 0 failures; **throughput gate passed** on `22701168` (8 nodes / 32 pipelines / 4 h, 15.71 rfd3/pipeline/h, 0 failures)
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
- **2026-10-05: `rfd3` and `boltz` capped too** (`GPU_TOOL_THREADS=8`). The first change capped only the five converted stages. On `22670942`, uncapped `boltz` took ~3,030% CPU (~30 cores) and `rfd3` ~680% on the Dragon primary, which sat at 3.8% idle. `rfd3.sh`'s `apptainer exec` has no `--cleanenv`, so the caps reach the container.
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

## Delta results

### `22669434` — 2 nodes (gpub036 + gpub060 primary), 1 h, cancelled at 55:51

- **Effectively 1 pipeline.** `p2_in`–`p8_in` held only `ALR.smiles`; every `p*_in` dir had mtime 2026-09-30 12:56, so the loss predates this change. p2–p8 died on their first `rfd3` with `FileNotFoundError: p{N}_in/ALR_binder_design.json`. The dirs were restored from `p1_in` (identical to `p9_in`) before the next job. See BACKLOG item 9 for the launcher gap that let this through.
- **p1 ran clean.** 31 converted-stage tasks completed on `compute` with no failures.
- **Placement and env, confirmed by sampling `/proc/<pid>/environ` on both nodes during the run:**
  - `mpnn`, `packmin`, `fastrelax` and `filter_shape` all ran on the **non-primary** gpub036, reached over the `dragon -w ssh` hop, as well as on the primary.
  - Rosetta stages had `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_WAIT_POLICY=PASSIVE`; `mpnn` had `OMP_NUM_THREADS=4`. That closes the env check without editing any script.
  - Every tool saw `CUDA_VISIBLE_DEVICES=0,1,2,3`, so there is still no GPU pinning (see Risks).
- **Telemetry could not answer the placement question.** `node_id` is null on every task event; see `upstream/asyncflow-telemetry-backend-and-node-id.md`.

### `22670942` — 2 nodes (gpub045 + gpub060 primary), 8 pipelines, `gpuA40x4-interactive`, 1 h, `TIMEOUT` at 01:00:25 (expected)

| | |
|---|---|
| `TaskFailed` / pipeline failures / tracebacks | **0 / 0 / 0** |
| Completed tasks | `mpnn` 337, `packmin` 108, `fastrelax` 82, `filter_shape` 32, `rfd3` 101, `boltz` 29, `adaptive_decision` 689 (`local`) |
| Tasks per pipeline | 72–102; every pipeline completed full rfd3 → mpnn → packmin → fastrelax → filter_shape → boltz cycles |
| Folds passing | 24 / 29 (83%) |
| rfd3 / pipeline / h | ~13 (106 rfd3 over 8 pipelines in ~1 h) |

**Reading the throughput number.** ~13 is above the 4-node baseline of 11.46, but it is a first-hour figure. The 8-node run `22534628` also did 12.05 in its first two hours before collapsing. So this shows the change does not slow the early phase. It does not replace the throughput gate.

**Primary-node load.** The primary was oversubscribed (3.8% idle, 75–100 runnable on 64 cores). The causes were not the converted stages:
- uncapped `boltz`/`rfd3`, now fixed;
- Dragon's own pool workers, at ~21–25 cores per node of idle spin. See `upstream/dragon-batch-idle-spin.md`.

The "primary's CPULoad drops relative to `22491438`" criterion therefore can't be judged until the Dragon spin is reduced, because it dominates the load figure.

### `22675825` — 4 nodes (gpub039/056/085 + gpub098 primary), 16 pipelines, `gpuA40x4-interactive`, 1 h, `TIMEOUT` at 01:00:09 (expected)

The first Delta run with the `rfd3`/`boltz` caps.

| | |
|---|---|
| `TaskFailed` / pipeline failures / tracebacks / OOM | **0 / 0 / 0 / 0** |
| Completed tasks | `mpnn` 667, `packmin` 212, `fastrelax` 165, `filter_shape` 86, `rfd3` 209, `boltz` 79, `adaptive_decision` 1417 |
| Tasks per pipeline | 73–106 |
| Folds passing | **71 / 79 (90%)** |
| rfd3 / pipeline / h | **13.1** (209 ÷ 16), against ~13 on 2 nodes: first-hour scaling from 2 to 4 nodes is about 100% (2.0× job-wide for 2× pipelines) |
| Mean node CPU% (telemetry) | primary 51.2%; others 45.7–46.2%. On `22670942`, before the `rfd3`/`boltz` caps, it was ~58% on both nodes |
| Mean GPU% | 9.8–14.7% per node, which is GPU 0 only; see [2026-10-05-gpu0-only](2026-10-05-gpu0-only.md) |

The `rfd3`/`boltz` caps were **not** live-verified here: the job started unattended, and telemetry carries no env. They are verified offline only.

### `22684833` — post-merge gate: 2 nodes (gpub082 primary + gpub084), 8 pipelines, run entirely from `/work/nvme`, `TIMEOUT` at 01:00:02 (expected)

This run gated the merge of `origin/main` (`ebfc0cb`) and the move to a `WORK_DIR` on `/work/nvme`: checkout, data, and the new venv `ve/small_mol`.

| | |
|---|---|
| `TaskFailed` / pipeline failures / tracebacks | **0 / 0 / 0** |
| Completed tasks | `mpnn` 357, `packmin` 105, `fastrelax` 82, `filter_shape` 32, `rfd3` 99, `boltz` 29, `adaptive_decision` 703 |
| Folds passing | 27 / 29 |
| rfd3 / pipeline / h | 13.1 (105 ÷ 8) |
| Paths | `MPNN_DIR`, `BOLTZ_CACHE`, `FOUNDRY_SIF_PATH`, task outputs and telemetry all under `$WORK_DIR` |

Remote placement of `rfd3`/`boltz` was **inferred, not sampled**:
- GPU 0 on the non-primary gpub084 averaged 45% busy;
- 0 of 99 `rfd3` and 0 of 29 `boltz` tasks failed.

A remote `rfd3` without the `WORK_DIR` bind would be expected to fail, but nobody took a `/proc` sample to confirm `WORK_DIR` in the remote env. That indirect evidence was accepted.

## Acceptance test — status

1. **2-node smoke:** **passed** (`22670942`). Placement on both nodes was confirmed via `/proc`, since telemetry has no `node_id`.
2. **Env check:** **passed** (`22669434`). Caps arrived on the non-primary node.
3. **4-node, 1 h:** **passed** (`22675825`, 0 failures, ~100% first-hour scaling from 2 to 4 nodes).
4. **Post-merge gate:** **passed** (`22684833`); remote placement was inferred, see above.
5. **Throughput gate:** **passed** (`22701168`, 2026-10-06). It required ≥ 11.46 rfd3/pipeline/h past hour 2 with no rise in `TaskFailed`. Measured: 15.16 / 16.22 / 16.28 / 15.19 by hour (15.71 overall), 0 failures over 4 h at 32 pipelines. Primary-node CPU averaged 62.7 % (others ~47 %). See [scale-gate](2026-10-06-scale-gate.md).

## Risks

- **False-FAILED race exposure.** More tasks now go through Dragon, so there is more exposure to the 0.14.1 race. It did not manifest in `22534628` (zero task failures in 63,589 log lines).
- **Task rate.** It is low (~32 × 300 tasks over ~7 h ≈ 0.4/s), well within the Dragon monitor thread's capacity.
- **Fallback.** If Dragon placement of the PyRosetta stages misbehaves, add `backend="local"` to just those registrations. They stay asyncflow-managed with per-task env. Keep `mpnn` on `compute`, because it is a GPU tool.
- **Process-mode tasks receive no `gpu_affinity` from Dragon, so every GPU tool runs on GPU 0.**
  - Every tool sees `CUDA_VISIBLE_DEVICES=0,1,2,3` (confirmed on `22669434`) and defaults to `cuda:0`.
  - Measured on `22684833`: GPU 0 averaged 52% / 45%, GPUs 1–3 exactly 0% on both nodes.
  - This predates this change; `mpnn` merely joined `rfd3`/`boltz` on GPU 0. See [2026-10-05-gpu0-only](2026-10-05-gpu0-only.md) and BACKLOG item 10.

## Upstream items (not patched here)

| Repo | Item |
|---|---|
| radical.asyncflow | Cancelling a task routed to a non-default backend calls the *default* backend's `cancel_task` (`workflow_manager.py:870`). The task state map comes only from the default backend (`:116`). This is harmless today because both backends register the default states. |
| rhapsody | The Dragon backend has no `cores_per_rank`/threads key; caps only go through `process_template.env`. `shutdown()` blocks the loop and never cancels in-flight Batch tasks, which is a plausible contributor to the teardown hang (item 2). |
| IMPRESS | `ImpressManager._run_adaptive_fn` could dispatch sync callbacks through a flow backend itself, so other examples get this without wiring it. |
| dragonhpc | Batch pool workers and managers busy-spin when idle; the pool size is hardcoded `num_cpus // 2`. See [upstream/dragon-batch-idle-spin.md](upstream/dragon-batch-idle-spin.md). |
| radical.asyncflow | Lifecycle events after submit carry the default backend's name, and `node_id` is never set on task events. See [upstream/asyncflow-telemetry-backend-and-node-id.md](upstream/asyncflow-telemetry-backend-and-node-id.md). |
