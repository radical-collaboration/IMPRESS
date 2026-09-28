# Multi-node scale-up: testing tracker

Live tracking doc for taking `small_molecule_binding` from its historical 1-node / 4-hour
allocation to a 4-node / 48-hour run on Delta `gpuA40x4`.

**Status:** Stage 3 complete. Telemetry wired (`2039893`) and Stage 4 (8 nodes / 32 pipelines)
prepared but **not yet submitted**. Earlier status line retained below.

**Stage 3:** (4-node production, job `22491438`) **COMPLETE** — all 16 pipelines hit the
`max_tasks` budget, 98% scaling efficiency, 552 passing folds. One new defect found: the Dragon
teardown hangs (see below).
**Last updated:** 2026-09-27

---

## Why this exists

The three most recent PROD runs (`21933600`, `21945304`, `21960876`) all ended in SLURM
`TIMEOUT` at the 4 h wall limit, so the design campaign never reached `max_tasks`. `seff` on
all three showed **97.7–98.1 % CPU efficiency on 16 cores** while using only ~29 % of memory —
CPU-starved, and under-requesting a node that was already being billed in full.

Scaling up also means using `dragon -m` for the first time. `sacct` shows **every one of the
50 prior allocated jobs ran on exactly 1 node**, so the multi-node launch path — its own
`srun` bring-up plus OFI fabric load — has never executed in this environment. These stages
exist to retire that risk cheaply before committing ~768 GPU-hours.

---

## Stage tracker

| # | Stage | Nodes | Pipelines | Wall | ~GPU-h | Job ID | Status | Result |
|---|---|---|---|---|---|---|---|---|
| 1 | `dragon -m` bring-up (`IMPRESS_TEST_MODE=1`) | 2 | 2 | 0:30 | 4 | `22456499` | **FAILED** | srun `--nodelist` FQDN mismatch → hung to TIMEOUT. Root-caused below; launch method replaced |
| 1b | ssh/TCP bring-up | 2 | 4 (PROD, see below) | 0:30 | 4 | `22466127` | **PASSED** | Ran on **both** nodes; full stack incl. boltz; no srun/ssh errors. Exposed the env-propagation blocker |
| 2 | Remote-execution proof | — | — | — | — | — | **not needed** — 1b proved it via `TASK HOST` | gpub030 + gpub096 |
| 3 | Production | 4 | 16 | 48:00 | ~172 actual | `22491438` | **COMPLETE** | 16/16 budgets hit at 6h41m; 552 folds; 98% efficiency. **Teardown hung 60 min**, manual cancel |
| 4 | Expanded campaign | 8 | 32 | **12:00** | ~198 projected | — | **prepared, not submitted** | telemetry wired; trajectories off; walltime right-sized |

Cost context: `bdyk-delta-gpu` balance is 19,164 GPU-hours, so Stage 3 is ~4 %.
Billing accrues on **elapsed**, not requested, time.

### Commands

```bash
export SCRATCH=/scratch/bdyk/hooten1
cd /scratch/bdyk/hooten1/IMPRESS/examples/small_molecule_binding

# Stage 1b — submitted as 22466127 (same command; the launcher now picks the
# ssh/TCP path internally whenever SLURM_NNODES > 1)
IMPRESS_TEST_MODE=1 sbatch --nodes=2 --time=00:30:00 delta_gpu_run.sh

# Stage 2 — optional, only if Stage 1 leaves remote execution unproven
sbatch --nodes=2 --time=00:45:00 delta_gpu_run.sh    # will TIMEOUT; that is expected

# Stage 3 — full production run
sbatch --nodes=4 delta_gpu_run.sh
```

---

## Stage 1b result — PASSED (multi-node works)

| Criterion | Result |
|---|---|
| `Unable to create step` / `node configuration is not available` | **0** — regression fixed |
| Launcher | `dragon -w ssh --network-config .../netconf_22466127/slurm.yaml -t tcp` `(nodes=2)` |
| Dragon saw both nodes | `32 workers, **3 managers**` (= `num_nodes + 1`) |
| Work ran off the primary node | `TASK HOST: gpub030...` **and** `gpub096...` |
| ssh host-based auth | no permission/connection errors |
| Full stack | 23 `rfd3`, 84 `mpnn`, 25 `packmin`, 17 `fastrelax`, 5 `filter_shape`, 4 `boltz` |
| Real outputs | 92 rfd3 JSON, 4 boltz `confidence_*.json` |
| Crashes | none (the 12 "failed" lines are the normal adaptive sequence gate) |

The `TASK HOST` values are FQDNs, independently confirming the Stage 1 root cause:
`gethostname()` returns FQDNs on compute nodes too, so `srun --nodelist` could never match
Slurm's short `NodeName=gpub030`.

TIMEOUT at 30 min was expected, not a failure — PROD's `max_tasks=300` was in effect.

### Blocker this exposed: env config is dropped under `-w ssh`

`dragon -w ssh` forwards only an allowlist to the backends
(`dragon/launcher/wlm/ssh.py:29-41`): `PATH`, `PYTHONPATH`, `LD_LIBRARY_PATH`,
`PYTHONSTARTUP`, `VIRTUAL_ENV`, `DRAGON_*`. So `IMPRESS_TEST_MODE`, `IMPRESS_N_PIPELINES` and
`OMP_NUM_THREADS` were **silently dropped** and the runner used PROD defaults.

`MPNN_DIR` / `BOLTZ_CACHE` / `FOUNDRY_SIF_PATH` / `SCRATCH` survived **only** because
`~/.bashrc` exports them and the ssh login shell sources it. Do not rely on that for new
settings.

Evidence it ran PROD despite `IMPRESS_TEST_MODE=1`: 4 pipeline dirs `p1`-`p4` (TEST is 2);
92 rfd3 JSON / 23 rfd3 tasks = 4 models each = PROD `diffusion_batch_size=4` (TEST is 1);
ensemble hit 32 with no "Task budget exhausted" (PROD `max_tasks=300`, TEST 10).

**Fix applied:** run config now travels as **argv**, which Dragon forwards verbatim —
`delta_gpu_run.sh` passes `--n-pipelines N [--test-mode]`, and the runner sets thread caps in
`os.environ` itself (sized from `sched_getaffinity`, which respects the cgroup). Verified
locally across six precedence cases under a 64-core mask.

---

## Stage 1 result — FAILED, root-caused, launch method replaced

```
Running: dragon -m run_small_molecule_binding.py  (nodes=2)
srun: error: Unable to create step for job 22456499: Requested node configuration is not available
*** JOB 22456499 ON gpub039 CANCELLED AT 2026-09-26T23:26:58 DUE TO TIME LIMIT ***
```

The failure is a genuine Dragon-on-Delta incompatibility, not a misconfiguration.

`sacct` showed step `22456499.0` — Dragon's **network-config** srun — ran on *both* nodes and
`COMPLETED` in 2 s. Only the **backend-launch** srun failed, and no `.1` step was ever created.
The two differ in exactly one meaningful way (`dragon/launcher/wlm/slurm.py`):

| | command |
|---|---|
| worked (`.0`) | `srun --nodes=2 --ntasks=2 --cpu_bind=none -u -l -W 0` |
| failed | `srun --nodes=2 --ntasks=2 --cpu_bind=none `**`--nodelist=<hosts>`** |

That `--nodelist` is built from `node.host_name` (`frontend.py:966` → `base.py:355`), and
`host_name` defaults to `gethostname()` (`node_desc.py:150-151`). On Delta `gethostname()`
returns the **FQDN** (`dt-login03.delta.ncsa.illinois.edu`), while Slurm's naming is short —
`scontrol show node gpub039` gives `NodeName=gpub039`, `NodeAddr=gpub039`,
`NodeHostName=gpub039`. An FQDN nodelist matches no node in the allocation, which is exactly
Slurm's "Requested node configuration is not available".

`--hostlist` is **not** a workaround: `SlurmWLM.__init__(self, network_prefix, port, _hostlist)`
accepts the argument and never references it again. There is no env knob either.

### The fix, from `ARCHIVE-run_impress.slurm`

`delta_gpu_run.sh` now takes a different multi-node path, sidestepping both known hazards:

```bash
dragon-network-config --output-to-yaml                       # writes <wlm>.yaml into cwd
dragon -w ssh --network-config <that yaml> -t tcp <runner>
```

- **`-w ssh`** starts backends over ssh (`wlm/ssh.py:337` iterates
  `zip(nodelist, node_ip_addrs)`), so no `srun --nodelist` is ever built and FQDNs are fine.
  Delta sets `HostbasedAuthentication yes` and `EnableSSHKeysign yes` cluster-wide, so this
  needs no user ssh keys — there is no private key in `~/.ssh`, only an inbound
  `authorized_keys`.
- **`-t tcp`** skips the HSTA/OFI path that dlopens `libdfabric_ofi.so` out of `FAB_LIB` —
  the other ranked multi-node hazard. Slower than HSTA, but this workload sends only two
  Dragon tasks per pipeline cycle, so transport throughput is not the bottleneck.
- **`--network-config`** satisfies the "SSH workload manager requires a valid hostlist or
  hostfile" check, which `frontend.py:165` gates on `self._config_from_file is None`.
- Generation itself is already proven here — `dragon-network-config` uses the same `SRUN_ARGS`
  as step `.0`, which succeeded.

The yaml is generated inside a per-job `netconf_<jobid>/` dir because the tool writes
`<wlm>.yaml` into its cwd, and a bare `slurm.yaml` in the shared WORKDIR would collide between
concurrent jobs. The `FAB_LIB` autodetect and `dragon-config` handling are retained: unused by
`-t tcp`, but still correct and needed if anyone reverts to `-m`.

---

## Stage 1b pass criteria

**0. The specific regression is gone.** This is the whole point of the re-test:

```bash
grep -iE "Unable to create step|node configuration is not available" impress_22466127.out
```

Empty passes. Also confirm the launcher line reads
`dragon -w ssh --network-config .../slurm.yaml -t tcp` with `(nodes=2)`, and that the
generated yaml is non-empty.

**1. Dragon actually saw both nodes.** This is the decisive check.

```bash
grep -E "Running: dragon|DragonExecutionBackend:" impress_22456499.out
```

Expect `dragon -m ... (nodes=2)` and **`3 managers`**. Dragon sets
`num_managers = num_nodes + 1`, and the archived single-node run (`arch/impress_21913252.out`)
reads `32 workers, 2 managers`. Still seeing `2 managers` means Dragon silently clamped to one
node and the test proved nothing — do not advance.

**2. Fabric came up.** A bad `FAB_LIB` fails as a near-silent hang, not an error, so look for
the absence of dlopen failures *plus* real task progress.

```bash
grep -iE "libfabric|ofi|dlopen|fabric" impress_22456499.out
grep -E "rfd3|boltz|adaptive/" impress_22456499.out | tail -20
```

**3. Environment survived the hop.** Remote tasks resolve `boltz`/`python` purely through
inherited `PATH`, and `rfd3.sh` needs `$SCRATCH` for its apptainer `--bind`. Empty output
passes:

```bash
grep -rl "command not found\|No such file or directory" ./*session*/*.stderr 2>/dev/null
```

**4. Real outputs landed** (catches the silent `--writable-tmpfs` failure mode, where `rfd3`
exits 0 but writes into a vanishing overlay):

```bash
ls logs/p1/*_rfd3/out/*.json
ls logs/p1/*_boltz/out/boltz_results_boltz_input/predictions/boltz_input/confidence_*.json
```

A `adaptive/backbone] passed=False` alongside an **empty** `out/` is that failure, not a
genuine QC rejection.

**5. Where the work actually ran.** `scripts/rfd3.sh` and `scripts/boltz.sh` now carry a
temporary `echo "TASK HOST: $(hostname)"`:

```bash
grep -rh "TASK HOST" ./*session*/*.stdout 2>/dev/null | sort -u
sacct -j 22466127 -o JobID%18,JobName%18,AllocNodes,NodeList%22,State%16
```

Two distinct hostnames proves distribution; one means Dragon ran everything on the primary.

### Results — Stage 1b

> Fill in after the job runs.

- [ ] No `Unable to create step` / `node configuration is not available`
- [ ] Launcher line shows `-w ssh --network-config ... -t tcp` with `nodes=2`
- [ ] `3 managers`
- [ ] No ssh permission/connection errors
- [ ] No `command not found` in task stderr
- [ ] `TASK HOST` shows two distinct hostnames
- [ ] Non-empty `*_rfd3/out/` and `*_boltz/.../confidence_*.json`
- [ ] Exit 0 / reached `=== Small Molecule Binding pipeline done`

Notes:

---

## Caveat: only 2 pipelines in TEST mode

`IMPRESS_TEST_MODE=1` pins `n_pipelines=2`, and the `cfg is PROD` guard in
`run_small_molecule_binding.py` deliberately blocks `IMPRESS_N_PIPELINES` from overriding TEST.
With only 2 concurrent Dragon tasks, both *could* legitimately land on one node even when
multi-node is working correctly.

The `TASK HOST` logging above is what makes this interpretable either way. If it shows a single
hostname, that is not necessarily a failure — rerun as Stage 2 (PROD config, 8 pipelines, short
wall, will TIMEOUT harmlessly) for a stronger signal.

**Remove both `TASK HOST` lines once multi-node is proven.**

## If Stage 1b fails

The next suspect is ssh host-based auth not working between compute nodes — the config says
enabled, but that is site config, not a live test. The signature would be ssh
permission/connection errors rather than an srun error.

Fallback: a one-line patch to `SlurmWLM._get_wlm_launch_be_args` shortening `--nodelist`
entries to `h.split(".")[0]`, then revert to `dragon -m`. Safe because Dragon connects over
`ip_addrs`, not hostnames — the hostnames are only used for srun placement.

---

## Stage 3: expect sublinear scaling, and measure it

Only **2 of 13** tasks reach the Dragon backend — `rfd3` (`small_molecule_binding.py:656`) and
`boltz` (`:1055`), both `capture_stdio=True`. The other **11** are `local_task=True` and run
in the driver's event loop on the head node, including the heavyweight `mpnn`, `packmin`,
`fastrelax` and `filter_shape` subprocesses. At 16 pipelines that is 16 concurrent
subprocesses on a single 64-core node at `OMP_NUM_THREADS=2`.

**Extra nodes accelerate only the two GPU stages.** Compare throughput per wall-hour against
Stage 2 before going beyond 4 nodes:

```bash
ls -d logs/p*/[0-9]*_boltz | wc -l     # completed cycles; divide by elapsed hours
```

If 4 nodes is not meaningfully better than 2, the head node is the ceiling and the fix is
architectural — converting `fastrelax`/`packmin`/`filter_shape` to Dragon tasks — not more
nodes. They already build clean command strings and write only to Lustre, so the conversion is
largely mechanical.

### GPU-spread evidence to collect during Stage 3

Explicit GPU pinning was deliberately **removed** from this example (main's CLAUDE.md assigns
placement to the backend). But nothing currently specifies affinity: `DragonExecutionBackend()`
takes no arguments, and there is no `gpus` / `Policy` / `task_backend_specific_kwargs` anywhere
in the example or `src/impress/`. So `rfd3` and `boltz` (`--devices 1`) may both default to
`cuda:0`.

```bash
grep -ci "out of memory" impress_<id>.out                    # must be 0
srun --overlap --jobid=<id> -w <node> -N1 -n1 \
  nvidia-smi --query-compute-apps=gpu_uuid,used_memory --format=csv
```

Several processes on one GPU UUID while others idle confirms the pile-up is real and currently
unowned — worth raising upstream rather than re-patching here.

---

## Already done (no action needed)

**Config** — `delta_gpu_run.sh`: `--cpus-per-task` 16→64, `--mem` 220G→240G, `--time` 4h→48h,
explicit `--account`. The CPU increase is free: billing is
`max(cpu*31.25, mem/8, gpu*500)` under `MAX_TRES`, and the GPU term already pins it at 2000.

**Two blockers fixed** — (a) `CUDA_HOME`/`MPI_LIB`/`FAB_LIB` were hardcoded to CUDA 25.3,
mpich 8.1.32 and libfabric 1.22.0, all removed by Delta's Cray PE upgrade; harmless under
`dragon -s` but fatal (as a silent hang) under `dragon -m`. Now autodetected with an existence
check. (b) `--mail-user=<your e-mail>` made `sbatch` parse `e-mail>` as a directive, so the
script **could not be submitted at all**.

**Also** — `dragon-config -c` before `add` (it appends), `SLURM_OVERLAP=1`, a guard refusing
the node-local `/tmp` foundry extraction when `--nodes>1`, three corrected `${SCRATCH}/${USER}`
path defaults, `OMP_NUM_THREADS`/`OMP_WAIT_POLICY` (nothing capped threads anywhere), and the
`VIRTUAL_ENV` guard in `scripts/boltz.sh`.

**Inputs** — `p1_in` … `p16_in` now exist, all byte-identical (`f60dbed8d00a`). They are
independent stochastic restarts of one design problem, not distinct targets. Covered by
`examples/.gitignore` (`*/p*/`), so untracked. Pipeline count derives from the allocation and
caps at however many exist:

| nodes | GPUs | pipelines | idle | `OMP_NUM_THREADS` |
|---|---|---|---|---|
| 1 | 4 | 4 | 0 | 8 |
| 2 | 8 | 8 | 0 | 4 |
| 4 | 16 | 16 | 0 | 2 |

**Verified environment** — `sbatch --test-only --nodes=4` accepted (256 processors); all three
fabric paths resolve; `foundry.sif` present on Lustre (8.85 GB), satisfying the `nodes>1`
guard; `MPNN_DIR` and `BOLTZ_CACHE` resolve; Boltz cache warm (`.mols_complete` present) so 16
concurrent pipelines skip the extraction-repair branch; 3.5 PB free.

---

## Reference

- **No checkpoint/resume exists.** On `TIMEOUT` all in-memory state (ensemble history, retry
  counters, guided-backbone seeds) is lost; on-disk task outputs survive but the campaign
  restarts from zero. The whole campaign must fit in one job.
- **`max_tasks` is per pipeline**, not global (`small_molecule_binding.py:1189` tests
  `len(self.state['ensemble'])`). 300 × 16 pipelines = 4,800 ensemble entries.
- **Artifact locations:** `IMPRESS_SESSION_DIR` no longer exists — asyncflow writes its session
  dir under the process cwd (`WORKDIR`). Task dirs go to `IMPRESS_WORK_DIR` (`WORKDIR/logs`).
- **Queue:** `gpuA40x4` is heavily backlogged (~2,300 pending vs ~256 running). Short jobs
  backfill well — Stage 1 estimated ~4 h out — while 48 h requests estimate ~2 days. Walltime
  length did **not** measurably change the estimate for a given node count.


---

## Stage 3 interim evaluation (job `22491438`, at t+25 min)

### Startup — all criteria met

| Check | Result |
|---|---|
| Config reached the runner | `N_PIPELINES: 16` **and** `--n-pipelines 16` in the launcher line |
| Pipelines started | `Starting with 16 initial pipelines` (was 4 before the argv fix) |
| Dragon saw all nodes | `32 workers, **5 managers**` (= `num_nodes + 1`) |
| Input dirs | `p1` … `p16` all created |

The argv fix is confirmed working: the identical launcher previously produced 4 pipelines
because `IMPRESS_N_PIPELINES` was dropped over ssh.

### Health — clean

0 OOM, 0 tracebacks, 0 exceptions, 0 srun/ssh errors. All 16 pipelines active within ~2 min of
the log tail; none stalled. Per-node `CPULoad` out of 64:

| gpub015 (primary) | gpub026 | gpub066 | gpub068 |
|---|---|---|---|
| 28.8 | 15.6 | 33.8 | 38.4 |

Work is genuinely distributed — the remote nodes are busier than the primary, and the primary
still has headroom despite carrying all 11 `local_task` stages.

### Throughput — 83% scaling efficiency

Counts are mtime-filtered to this job; see the caveat below.

| | rfd3/h | boltz/h | rfd3/pipeline/h |
|---|---|---|---|
| 2-node, 4 pipelines (`22466127`) | 46.8 | 8.1 | 11.69 |
| 4-node, 16 pipelines (`22491438`) | 154.8 | 47.6 | 9.67 |

**3.3x job-wide for 4x the pipelines — 83% per-pipeline efficiency, i.e. 17% degradation at
4x scale.** Mildly sublinear, consistent with 11 of 13 tasks being pinned to the primary node,
but far better than a hard head-node ceiling. Going beyond 4 nodes is defensible on this
evidence, though the degradation will compound. (The boltz figure shows 5.9x but the baseline
is only 4 events — noise, not superlinearity.)

Ensemble is growing ~52 entries/h on the fastest pipeline, so `max_tasks=300` lands in
**~5.7 h**, costing roughly **92 GPU-hours** of the 768 h ceiling. The 48 h request is purely a
safety margin.

### Issue found: the output tree is reused across runs

`logs/p1` and `logs/p2` alone still held **73 task dirs from job `22466127`**. Task paths are
`{base_path}/{name}/{taskcount}_{taskname}` with `taskcount` restarting at 1 each run, so a new
run **overwrites** the previous run's dirs in place. Two consequences:

1. Any analysis over `logs/p*/` mixes runs unless filtered by mtime — my first throughput pass
   was inflated by exactly this (87 rfd3 vs the true 65).
2. Prior-run artifacts are silently destroyed as paths are reused.

Fix: set a per-job `IMPRESS_WORK_DIR` (e.g. `${WORKDIR}/logs/${SLURM_JOB_ID}`) so each run gets
its own tree, or clean `logs/p*` between runs. Not urgent for the running job, but it should
land before the next one.


---

## Stage 3 final result (job `22491438`)

### Outcome: the campaign succeeded

| | |
|---|---|
| Pipelines | **16/16 hit the 300-entry `max_tasks` budget** |
| Compute finished | **6h41m** (`22:23:11` — "All pipelines finished. Exiting.") |
| Scaling | 3.9x job-wide for 4x pipelines = **98% per-pipeline efficiency** |
| Folds | **552 passed / 25 failed** (95.7%) |
| Tasks | 1109 rfd3, 3045 mpnn, 958 packmin, 841 fastrelax, 622 filter_shape, 575 boltz |
| Health | 0 OOM, 0 tracebacks, 0 exceptions, 0 srun/ssh errors |

It stopped on the task budget rather than the wall clock — the original goal, after three
predecessor runs died at `TIMEOUT`.

Throughput vs the 2-node baseline (`22466127`), mtime-filtered to each job:

| | rfd3/h | boltz/h | rfd3/pipeline/h |
|---|---|---|---|
| 2-node, 4 pipelines | 46.8 | 8.1 | 11.69 |
| 4-node, 16 pipelines | 183.4 | 91.9 | **11.46** |

Per-node `CPULoad` stayed balanced at 26-40 of 64 with the primary no busier than the rest, so
the "11 of 13 tasks pinned to the primary node" ceiling is real in principle but **not binding at
16 pipelines**.

### New defect: Dragon teardown hangs after a clean finish

The job did **not** exit cleanly. Timeline:

```
22:23:11.462  [MANAGER] All pipelines finished. Exiting.
22:23:11      ==================== IMPRESS MANAGER FINISHED ====================
22:23:11.467  [rhapsody...dragon] Shutting down Dragon backend
              ... 60 minutes of nothing ...
23:23:02      CANCELLED by 68562 (manual scancel)
```

`sacct` records `State=CANCELLED`, `Elapsed=07:41:11`. All science was complete at 6h41m; the
remaining **60 minutes were spent hung inside `flow.shutdown()`** and never resolved on their
own. `=== Small Molecule Binding pipeline done ===` never printed.

**Cost: ~64 GPU-hours burned on the hang** (60 min x 4 nodes x 4 GPU) — about 37% of the job's
total billed 172 GPU-h, for zero output.

Implications:
- This is the **first** multi-node production teardown, and it hung on the first attempt. Treat
  it as reproducible until shown otherwise.
- At 8 nodes the burn rate doubles to 32 GPU-h per hung hour.
- The SLURM wall limit is currently the **only** backstop — there is no watchdog and no resume.
  A 48 h request means an unattended hang could bill the full remainder.
- Mitigation is therefore two-part: **right-size `--time`** (12 h for the 8-node campaign), and
  **bound the shutdown in code** so the job self-terminates once the work is provably done.


---

## Telemetry wiring (commit `2039893`, branch `telemetry-scaleup`)

Enabling telemetry is three lines on `ImpressManager`, but the `protein_binding` reference
wiring copied verbatim would produce a trace that cannot answer Stage 4's question. Two defects,
both verified against that example's real 7.0 MB output:

1. **Only 2 of 13 tasks would appear.** `auto_register_task(local_task=True)` returns the raw
   coroutine and never reaches asyncflow, so only `rfd3` and `boltz` emit lifecycle events. The
   other 11 — `mpnn`, `packmin`, `fastrelax`, `filter_shape`, `filter_energy` and the six
   analysis stages — are exactly the ones that run on the primary node whose saturation Stage 4
   is meant to measure.
2. **Even those 2 are indistinguishable.** The label is `shlex.split(cmd)[0]`, i.e. always
   `bash` — **3486 of 3486** `executable` attributes in the reference file.

What landed, beyond enabling it:
- `impress.LocalStage` custom event + a `_timed_local` decorator on all 11 local stages.
  Additive instrumentation, not an execution change: converting them to `flow.function_task` is
  not drop-in, since they mutate `self.state`/`self.taskcount` in-process and the
  `OMP_NUM_THREADS` cap depends on them being subprocesses of the runner.
- `workflow_id=f"{name}:rfd3"` / `:boltz` at the two Dragon call sites.
- `checkpoint_path` derived from the resolved `work_dir` (a relative path resolves against
  `$SCRATCH`, not the source tree, and this inherits per-job scoping);
  `resource_poll_interval=15.0` (the reference's 5.0 made ResourceUpdate 69% of its file);
  `checkpoint_interval=300.0` (the reference omits it, so a wall-clock kill loses the
  128 KB-buffered file); `stop()` in `finally` before `flow.shutdown()` (the reference has it in
  `try` and loses the file on any error).

Verified off-HPC against the real stack: a live `WorkflowEngine.start_telemetry` session wrote
the JSONL containing `fastrelax completed 0.020s` and `packmin failed`; the decorator preserves
`__name__` (required by `auto_register_task`'s `setattr`), returns values and propagates
exceptions.

## Correction: the Dragon primary is not the batch node

Stage 3's interim note said the primary node was at 29.5/64 and "no busier than the rest". That
was wrong — it assumed the primary was the batch node `gpub015`. The `dragon-network-config`
JSON in `impress_22491438.out` shows index `0`, `is_primary: true`, is **`gpub068`**, which was
the busiest node in both readings:

| node | early | steady | role |
|---|---|---|---|
| gpub015 | 28.8 | 29.5 | batch node (frontend only) |
| gpub026 | 15.6 | 31.3 | |
| gpub066 | 33.8 | 29.5 | |
| **gpub068** | **38.4** | **39.7** | **Dragon primary — runs all 11 local stages** |

So the primary sat at **62%** of 64 cores at 16 pipelines, ~10 cores above the others — the
`local_task` load, exactly as the architecture predicts. A naive doubling to 32 pipelines
projects to **~124%, i.e. oversubscribed**, and `OMP_NUM_THREADS` is already at its floor of 1
so no headroom can be reclaimed by trimming threads.

This does not invalidate the 98% efficiency figure, which is measured throughput. It does mean
Stage 4 is likelier to land in the degraded regime than first stated. **Always check which node
is `is_primary` before reading a load figure — it is not the batch node.**

## Stage 4 preparation (not submitted)

- `scripts/rfd3.sh`: `dump_trajectories=False`. The `*_noisy_*`/`*_denoised_*` files are
  11.85 MB of each 11.92 MB rfd3 dir (99.4%). Safe: nothing reads them, and `analysis_backbone`
  selects from `.json` files containing `_model_` then derives `.cif.gz` by extension swap —
  trajectory files ship no `.json`, so they are unreachable by that selection. Campaign
  footprint ~30 GB → ~3.8 GB.
- `delta_gpu_run.sh`: `--time` 48:00:00 → **12:00:00**. The wall limit is the only backstop
  against the teardown hang. 12 h = ~6.8 h expected compute + ~1 h teardown + slack to ~62%
  throughput. Exposure if it hangs: 384 GPU-h vs 1536 at 48 h. Queue start estimate is identical
  for 8/12/16/24/48 h, so shortening costs nothing.
- `p17_in` … `p32_in` created (all 32 checksum-identical, gitignored). 8 nodes now yields 32
  pipelines with **zero idle GPUs**; `OMP_NUM_THREADS` = 1.

### Evidence to collect from the Stage 4 run

`impress_<jobid>.out` **cannot** answer the `node_id` question — `impress_22491438.out` has 0
occurrences of `node_id` and 0 of `telemetry`, since it predates the wiring. It carries only the
`dragon-network-config` JSON (nodes discovered, and which is primary) and the `N managers` line.

The file to keep is `logs/<SLURM_JOB_ID>/telemetry/<session>.<ts>.telemetry.jsonl` (~40-60 MB
for a 7 h 8-node run). Pass conditions: **8 distinct `node_id`s** (fewer means
`DragonTelemetryAdapter` silently no-opped — it is fail-soft at three points and only logs a
warning), task labels reading `p*:rfd3`/`p*:boltz` rather than `bash`, and all 11 local stages
present with durations.
