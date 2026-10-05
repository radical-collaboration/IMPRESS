# Dragon Batch: idle pool workers and managers busy-spin (~21–25 cores per node)

**Component:** dragonhpc 0.14.1, `dragon.workflows.batch` (reached through rhapsody 0.5.0 `DragonExecutionBackend`)
**Severity:** high on the Dragon primary node (oversubscribes it); wasted cores elsewhere
**Status:** diagnosed, not reported upstream, no local workaround applied
**Evidence:** smoke jobs `22669434` (gpub036 + gpub060) and `22670942` (gpub045 + gpub060), 2 × A40x4 nodes, 64 cores each, launched with `dragon -w ssh -t tcp`

## Symptom

Every node of a Dragon run carries about 30 `python -c "from dragon.native.process import _dragon_native_python_process_main; ..."` processes. Each sits at 70–80% CPU for the whole run, whether or not any task is running. On `22669434`, where effectively one pipeline was running one tool at a time, both nodes showed about 2,900% CPU in these processes.

Live 5-second `top` on `22670942`, 8 pipelines:

| Node | Dragon native procs | Tools | Idle |
|---|---|---|---|
| gpub060 (primary) | 2,060% | 3,845% | **3.8%** |
| gpub045 | 2,486% (42 procs) | 504% | 47% |

On the primary, `procs_running` was 75–100 on 64 cores. A single-threaded PyRosetta `fastrelax` got only 62% of a core in that window, against 100% a few seconds later. It had about 28k nonvoluntary context switches.

This also reinterprets earlier campaign figures. The "per-node CPULoad 26–40 of 64 with GPUs mostly idle" from `22491438` and `22534628` (see the CLAUDE.md 2026-09-27 and 2026-09-30 rows) is largely this spin, not tool work.

## What the processes are

Batch starts one subnode manager per node, plus a scheduler manager on the first node. Each manager builds a `dragon.native.Pool`.

- **Pool size is hardcoded at `node.num_cpus // 2` per node** (`batch.py:5167`, `5180`, `5209`). The code assumes hyperthreading, so Delta's 64 non-HT cores give **32 workers per node**.
- **Process-mode tasks run on these workers.**
  - `Manager._launch_tasks` calls `pool.map_async(_do_task)` (`batch.py:3502`). The worker then calls `JobCore.run` (`batch.py:1799`), which creates a `ProcessGroup` and polls `grp.join(timeout=0.1)` (`batch.py:1447–1517`).
  - So each task holds one worker for its whole lifetime, and pool size = the maximum number of concurrent tasks per node.
  - The core budget is `_subnode_available_cores = physical_cores_per_node` (`batch.py:2007`, `2803–2821`).
- **The other processes:**
  - One manager process per node at about 110%.
  - One ProcessGroup manager per running task at about 22%.
  - A few processes at about 9%, probably the results-DDict managers (not conclusively identified).

## Root cause: two spins

1. **Idle workers spin for their entire wait timeout.**
   - The worker loop is `inqueue.get(timeout=WORKER_POLL_FREQUENCY)` with `WORKER_POLL_FREQUENCY = 0.2` (`dragon/native/pool.py:32`, `555`).
   - `native.Queue` reads through the FLI with the compiled-in `DRAGON_DEFAULT_WAIT_MODE = DRAGON_ADAPTIVE_WAIT` (`include/dragon/global_types.h:53`).
   - In `libdragon.so`, `dragon_bcast_wait` is a loop of `sched_yield`, then `clock_gettime`, then a deadline check. It never falls back to a futex or sleep.
   - Live `strace` of an idle worker: 105,332 `sched_yield` calls in 3 s. With yields filtered out, the only other syscall is `getpid()` exactly every 0.200 s.
   - So the spin covers the whole timeout, and a longer timeout would not help.
2. **Managers busy-loop with no sleep.**
   - `Manager._run` (`batch.py:3701–3790`) loops `work_q.get_nowait()` and `_async_queue.get_nowait()` with no sleep or blocking get.
   - `strace`: about 68k `sched_yield` per 2 s.

32 × ~70% plus the managers comes to about 2,500–2,900% per node, which matches what was observed.

## Knobs available today (none sufficient)

- **`Batch(...)` kwargs**, passed through by `DragonExecutionBackend(batch_kwargs=...)` (rhapsody `dragon.py:114`, `123`): `num_nodes`, `pool_nodes` (forced to 1, `batch.py:5175–5177`), `disable_telem`, `scheduler_workers`, `results_ddict_*`, `managed_lifecycle`, `stdout`/`stderr`, `task_logs`.
  - **None of them sets the per-node worker count.**
  - `scheduler_workers` only sizes the scheduler's small pool.
- **`DRAGON_USER_WAIT_MODE=IDLE_WAIT`** feeds `Policy` and `Connection` (`parameters.py:326`, `573`; `connection.py:282–519`), but not native `Queue`/FLI channels. Probably ineffective here; untested.
- **The manager busy-loop has no knob.**

## Candidate local workaround (not applied)

Shrink the pool before the managers are built, for example from the runner before the backend is created:

```python
import os
from dragon.workflows.batch import batch as _b
_orig = _b.Batch._setup_managers
def _setup_managers(self):
    n = int(os.environ.get("IMPRESS_DRAGON_WORKERS_PER_NODE", "0"))
    if n > 0:
        self._workers_per_node_in_pool = n   # pool size + core budget + ClientCompiler
        self.num_workers = n
    _orig(self)
_b.Batch._setup_managers = _setup_managers
```

**What it touches:**
- `_setup_managers` is called at `batch.py:5272`. It reads `_workers_per_node_in_pool` for the pool size and core budget (`5484`, `5493`, `5525`), and the compiler reads it again later (`5928`).
- At n = 8–12, idle spin should drop from about 21 cores to about 5–8 cores per node. The manager spin remains.

**Risks:**
- A cap below peak concurrent tasks per node makes ready tasks queue. `22670942` showed 4–5 tools per node at peak, so keep n at least that peak plus about 2.
- Keep n ≥ `results_ddict_managers_per_pool` (default 4).
- Any `job()` with `num_procs > n` would be treated as multi-node (`batch.py:1728–1730`). This workflow only submits single-process tasks.
- It monkeypatches a private method, so it must be re-checked on every Dragon upgrade.

## Asks for upstream (Dragon)

1. **Make the per-node pool size a `Batch` parameter.** It is hardcoded `num_cpus // 2` today, which is wrong on non-HT nodes and oversized for workflows whose tasks are external processes.
2. **Stop the ADAPTIVE wait spinning until its deadline.** For example, back off to a futex/idle wait after a bounded spin, or let `native.Queue`/`Pool` take a wait mode.
3. **Make `Manager._run` sleep or block when a pass made no progress.**
4. **Expose these through rhapsody's `DragonExecutionBackend`** once they exist.

## How to re-check

On any running job, run these on each node:
- `ps -u $USER -o pid,pcpu,args --sort=-pcpu | grep _dragon_native`
- `top -b -n1 | head`

Compare tool CPU% against idle. Short `strace -c -p <worker pid>` runs (a few seconds, then detach) show the `sched_yield` rate. py-spy is not installed on Delta.
