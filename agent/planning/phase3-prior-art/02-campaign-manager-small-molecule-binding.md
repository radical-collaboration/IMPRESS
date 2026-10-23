# Phase 3 prior art — `campaign_manager` / `small_molecule_binding` (Delta + foundry containers)

Repo: `impress-a-refcodes/middleware/campaign_manager`. HEAD stayed on `devel` throughout; everything
below was read read-only via `git show origin/new_cm:<path>` / `git ls-tree -r --name-only origin/new_cm`.
Branch never checked out.

## 1. What `campaign_manager` is

`campaign_manager` (package name `campaign-manager`, internal module name in `new_cm` is
`src.campaign`, `AsyncCampaignManager`) is **not** a scientific-DAG composer. It is a **multi-replica
pool orchestrator**: it runs many concurrent instances ("replicas") of one or more user-supplied
`BaseWorkflow` subclasses inside a single asyncio event loop, wires them into named "groups" with
dependency edges, and schedules them under CPU/GPU resource limits. Per its own README
(`origin/new_cm:README.md`):

> "A **campaign** is a set of **workflow groups** wired by dependencies and runtime triggers. Each
> group is a pool of instances that all run the same workflow class. When an instance finishes it can
> signal the next group, triggering more work downstream."

The `devel` branch had a completely different architecture (`src/radical/cm/{bookkeeper,enactor,planner}`
— a HEFT/GA/L2FF static-planner + bookkeeper + enactor stack, ~4200 lines). `new_cm` deletes all of it
and replaces it with a fresh `src/campaign/` package. The commit that introduces it says explicitly
(`e26b087`):

> "Extracted from the SPHERICAL repo (branch: adr) ... Orphan branch — no history from campaign_manager
> master/devel."

This explains a real gap: `origin/new_cm:CLAUDE.md` still describes the *SPHERICAL* repo layout
(`workflows/run_campaign/esm2_ddsim_campaign/...`, an `src/inference/` ESM2 service, `sgdes` workflow)
that does not match the actual tree in `campaigns/` and has no `src/inference/`. **`CLAUDE.md` is stale
documentation carried over from the donor repo** — treat its file-path claims with suspicion; its
architecture description of `AsyncCampaignManager` itself is accurate and was cross-checked against
`campaign_manager.py`/`executor.py`/`scheduler.py`.

**Dependencies** (`origin/new_cm:pyproject.toml`):
```toml
dependencies = [
    "pyyaml>=6.0",
    "radical.asyncflow>=0.3.0",
    "rhapsody-py>=0.2.0",
    "nvidia-ml-py"
]
[project.optional-dependencies]
dragon = ["dragonhpc>=0.13.2", "rhapsody-py>=0.2.0", "nvidia-ml-py"]
adr    = ["radical.adr", "pydantic>=2"]   # not yet on PyPI, installed editable
llm    = ["openai>=1.0.0", "instructor>=1.0.0"]
```
This confirms Phase 2's picture exactly: `radical.asyncflow` is the workflow engine dependency,
`rhapsody-py` provides real backends (`DragonExecutionBackend`, `ConcurrentExecutionBackend`), and
`radical.adr` is an **optional** bridge, not a foundation — the CM works with zero ADR code installed.

## 2. Loop ownership — the key finding

`AsyncCampaignManager` owns a **reactive, event-driven scheduler loop**, not a fixed-phase cycle:
`_schedule()` re-runs on every state change (a replica finishing, or a `trigger_dependent`/`signal_done`
call), using a two-pass greedy algorithm (guarantee `concurrency_floor`, then fill to
`concurrency_cap`, both priority-ordered). This loop is described in `campaign_manager.py`'s docstring:

> "Two-pass greedy scheduler on every state change... Pass 1 — guarantee `concurrency_floor` for all
> eligible groups (highest priority). Pass 2 — fill remaining capacity up to `concurrency_cap`."

Separately, when ADR supervision is used, `src/campaign/adr/operator.py`'s `CampaignOperator` (a
subclass of `radical.adr.Operator`) runs the ADR `Run→Observe→Decide→Act` loop via `Operator.run()`
(an async generator). **This is exactly the `Operator.run()` that Phase 2 flagged as owning a complete
outer loop that conflicts with ours.** `campaign_manager` resolved that conflict — and this is the most
transferable finding in this review — by **never letting `Operator.run()` be the program's main loop**.
Instead, `src/campaign/adr/supervisor.py::run_supervised(cm, operator, tick_s)` wraps it:

```python
async def run_supervised(cm, operator, tick_s=1.0, max_failed_ticks=None):
    async def _drive():
        async for _snapshot in operator.run():
            await asyncio.sleep(tick_s)
            # ... failure-streak bookkeeping ...
        if hasattr(cm, "stop"):
            await cm.stop()   # ADR goal fired -> tell the CM to stop accepting new work

    drive_task = asyncio.ensure_future(_drive())
    try:
        await cm.wait()        # <-- the CM's OWN loop is what the caller actually awaits
    finally:
        await operator.shutdown()
        if not drive_task.done():
            drive_task.cancel()
            ...
```

`operator.run()` is driven as a **background task racing against `cm.wait()`**, not as the top-level
await. The CM's own scheduler/executor loop stays authoritative over launching, resource allocation,
and completion; the ADR operator is deliberately restricted to a small set of `@act` **levers**
(`set_priority`, `set_batch_size`, `set_score_cutoff`, `trigger`) that only *nudge* the CM — it cannot
directly start/stop tasks or touch resources. The `CampaignOperator` docstring calls this the
"ADR sacred boundary":

> "The CM keeps owning scheduling, execution lifecycle, and resources; a `CampaignOperator` runs the
> ADR Run→Observe→Decide→Act loop *alongside* a live CM and only nudges its levers (priority, batch
> size, dependent triggers) — the ADR 'sacred boundary'."

This is real, in-production evidence that **"mine the pattern, keep our loop"** (Phase 2's
recommendation) is not just viable but is exactly what a comparable system did, using the identical
`radical.adr` version.

## 3. The operator — `sm_binding_operator.py` (decision layer), quoted in full

This is **not campaign_manager's own abstraction** — it directly subclasses `radical.adr.policy.base.Policy`
(imports: `from radical.adr import goals, observe, Decision`, `from radical.adr.goals import Goal`,
`from radical.adr.policy.base import Policy, decide`) and campaign_manager's `CampaignOperator` (itself a
`radical.adr.Operator` subclass). So the ADR abstractions are used verbatim; `campaign_manager` only adds
the `CampaignOperator` base class (goal-validation helper, checkpoint sidecar helper, inherited `@act`
levers) and `CampaignView` (the CM-state → observation adapter).

Full operator (`campaigns/small_molecule_binding/sm_binding_operator.py`):

```python
class SmMolBindingPolicy(Policy):
    """Dummy cycle-based policy... Each ADR tick it either:
      - Triggers n explore + m exploit pipelines (cycle start), or
      - Waits for the current cycle's pipelines to finish.
    """
    def __init__(self, op):
        super().__init__()
        self._act          = op.get_actions()
        self._explore_n    = op.explore_n
        self._exploit_m    = op.exploit_m
        self._max_cycles   = op.max_cycles
        self._per_cycle    = op.explore_n + op.exploit_m
        self._campaign_cycle   = 0
        self._cycle_launched   = False
        self._cumulative_total = 0

    @decide
    async def run(self, obs: dict) -> Decision:
        n_hits = int(obs.get("n_hits", 0))
        if self._cycle_launched and n_hits >= self._cumulative_total:
            self._campaign_cycle += 1
            self._cycle_launched = False
        if not self._cycle_launched and self._campaign_cycle < self._max_cycles:
            self._cycle_launched = True
            self._cumulative_total += self._per_cycle
            actions = []
            if self._explore_n > 0:
                actions.append(self._act.trigger("explore", self._explore_n))
            if self._exploit_m > 0:
                actions.append(self._act.trigger("exploit", self._exploit_m))
            return Decision(actions=actions)
        return Decision()   # nothing to do this tick

class SmMolBindingOperator(CampaignOperator):
    def __init__(self, view, engine=None, *, max_cycles=1, explore_n=2, exploit_m=1, **kwargs):
        super().__init__(view, engine=engine, **kwargs)
        self.max_cycles, self.explore_n, self.exploit_m = int(max_cycles), int(explore_n), int(exploit_m)
        self._validate_stopping_condition()

    def rule_policy(self):    return SmMolBindingPolicy(self)
    def default_policy(self): return SmMolBindingPolicy(self)

    @goals
    def criteria(self):
        total = self.max_cycles * (self.explore_n + self.exploit_m)
        if total <= 0: return []
        return Goal(name="all_cycles_done", metric="n_hits",
                    threshold=total - 0.5, direction="maximize")

    @observe
    def extract(self, snapshot):
        obs = _BaseCampaignOperator.extract(self, snapshot)
        stages = obs.get("stages", {})
        obs["explore_finished"] = stages.get("explore", {}).get("finished", 0)
        obs["exploit_finished"] = stages.get("exploit", {}).get("finished", 0)
        return obs
```

**What it observes:** a flat dict from `CampaignView.observe()` — per-stage `finished`/`running`/
`pending`/`priority`/`cap`/`bp_state`/`stalls`/`avg_duration_s`/`score_p50`/`score_p90`/`n_failed`, plus
`n_hits` (sum of finished replicas across terminal stages) and `cycle`. **What it decides:** whether to
launch the next cycle's batch of `explore`/`exploit` replicas — count-based, no content of any candidate
result is inspected. **How the decision is expressed:** `Decision(actions=[...])` where each action is a
call to a pre-registered `@act` lever (`trigger(stage, replicas)`); an empty `Decision()` is the no-op.

**Mapping to our `ControlPolicy`/`Decision` union:** this is architecturally the closest real-world
analogue to our **model D (user-supplied explicit policy)** — a hand-written, fully deterministic
`decide` function with internal counters, no LLM, no learning. It has no `interpret` and no
`on_rejected` equivalent (there is no rejection path at all: `trigger()` either succeeds or is a no-op).
Its returned `Decision` only ever expresses **"launch N more of stage X"** — there is no `Backtrack`,
no `RequestHuman`, and it cannot express `ComposeAndRun` because it never composes a graph; the only
thing it can vary between cycles is **how many replicas of two fixed stages to launch**. The
`CampaignOperator._validate_stopping_condition()` pattern (raise `ValueError` at construction if there
is no `@goals` and no `max_cycles`) is a nice small guardrail worth adopting verbatim — it prevents a
whole class of "campaign that silently runs forever" bugs.

## 4. The workflow — `sm_binding_workflow.py`, and the DAG question

**This is the single most important finding for Phase 4's runtime-composition question.**
`sm_binding_workflow.py`'s own docstring:

> "SmMolBindingWorkflow — Campaign Manager workflow that wraps one complete
> SmallMoleculeBindingPipeline run (**black-box A1 integration**)."

`campaign_manager` does **not** build the RFD3 → MPNN+PackMin → FastRelax → FilterShape → AlphaFold2
DAG at all. Each CM "replica" is **one entire opaque call into IMPRESS's own pipeline object**:

```python
from impress import ImpressManager, PipelineSetup
from small_molecule_binding import SmallMoleculeBindingPipeline
from run_small_molecule_binding import adaptive_decision
...
manager = ImpressManager(execution_backend=backend)
setup = PipelineSetup(name=replica_id, type=SmallMoleculeBindingPipeline,
                       adaptive_fn=adaptive_decision, kwargs=pipeline_kwargs)
await manager.start(pipeline_setups=[setup])
await manager.flow.shutdown()
```

So the actual stage sequence (RFD3, ProteinMPNN+PackMin cycles, FastRelax, FilterShape, AlphaFold2 —
per `config.yaml`'s header comment) lives entirely inside **IMPRESS's original `small_molecule_binding`
example** (already reviewed in Part A of this prior-art series) — it is **not** re-implemented or
re-composed by `campaign_manager`. `campaign_manager`'s own graph, visible from `config.yaml`, is trivial:
two independent, non-communicating groups (`explore`, `exploit`), each with `dependencies: []`, both
declared `terminal` — there is no `_signal_done`/`_trigger_dependent` chain between them at all. Every
"IMPRESS pipeline run" is, from campaign_manager's point of view, a single black-box task.

Whether the *inner* IMPRESS DAG is static or runtime-composed could not be determined from this repo
(that's the domain of Part A's IMPRESS review, not `campaign_manager`). What **is** established here:
**a real deployed system chose to keep the scientific DAG entirely inside one library (IMPRESS) and
used the "campaign manager" layer only for outer-loop replica fan-out** — i.e., they did not attempt to
express the scientific pipeline in the orchestrator's own composition primitives at all. This is
evidence *for* our free-runtime-composition decision being non-redundant work (nobody else in this
codebase attempted it at the campaign-manager layer), and also a caution: bolting "campaign management"
on top of an already-fixed pipeline is a much smaller integration surface than what IMPRESS-A is
attempting — this system never had to solve dependency-graph validation, parameter typing across stages,
or budget-aware dry-run, because IMPRESS's pipeline already decided all of that internally.

Two more workflow-level details worth carrying forward:
- **GPU pinning is per-replica, not per-task.** `self.policies[0]` (a Dragon `Policy` built by
  `gpu.make_policies()`, see §7) is passed as a single `"policy"` kwarg into
  `SmallMoleculeBindingPipeline(...)` — the CM assigns one GPU-affinity policy per *pipeline replica*
  and IMPRESS is trusted to honor it for every task inside that replica. There is no per-task resource
  negotiation between the two systems.
- **Shared execution backend.** One `DragonExecutionBackend` is started once in `run_campaign.py` and
  handed to every replica via `self.engine_dragon`; the code comment explains why this is safe: "All
  shell tasks use `local_task=True` + `asyncio.create_subprocess_shell()`, so there is no Dragon channel
  routing. We can safely share the CM's Dragon backend across replicas without task-result
  cross-contamination." I.e. the actual GPU tool invocations (RFD3, MPNN, ColabFold, PyRosetta) run as
  literal local subprocesses on the allocated node — Dragon is only used for the multi-node
  process/channel plumbing, not for routing each shell command.

## 5. `config.yaml`, quoted substantially

```yaml
engine: dragon    # dragon = multi-node GPU runs; concurrent = local mock/testing

resources:
  total_cpus: 0   # 0 = unlimited
  total_gpus: 0   # managed per-replica via required_gpus

workflows:
  explore:
    replicas:          0       # triggered by ADR operator each cycle
    concurrency_cap:   2
    concurrency_floor: 1
    priority:          10
    required_gpus:     1
    input_dir: p1_in
    work_dir: runs
    mock: false
    diffusion_batch_size: 1    # backbones per rfd3 call  (prod: 2)
    num_refine_cycles:    1    # mpnn+packmin cycles       (prod: 3)
    num_seqs:             1    # sequences per mpnn call   (prod: 4)
    mpnn_ensemble_size:   1    # mpnn batches on cycle 0   (prod: 1)
    max_tasks:            5    # ensemble budget            (prod: 300)
    backbone_max_ca_deviation: 10.0   # prod: 1.0
    backbone_min_ss_fraction:  0.0    # prod: 0.5
    fastrelax_max_fa_rep:      1e6    # prod: 100.0
    fastrelax_max_total_score: 1e6    # prod: 0.0 (Rosetta scores negative; 1e6 always passes)
    fastrelax_max_interact:    1e6    # prod: 0.0
    interface_min_sc:          0.0    # prod: 0.35
    fold_min_plddt:            0.0    # prod: 70.0
  exploit:
    replicas: 0
    concurrency_cap: 1
    concurrency_floor: 1
    priority: 9
    required_gpus: 1
    # (same pipeline-parameter keys, integration-test values)

cm:
  features:
    backpressure: false
    sharder:      false
    monitor:      false
  adr:
    policy:  rule
    tick_s:  1.0
    terminal: [explore, exploit]
    goals:
      max_cycles: 1
      explore_n:  2
      exploit_m:  1

workflow_registry:
  explore: sm_binding_workflow.SmMolBindingWorkflow
  exploit: sm_binding_workflow.SmMolBindingWorkflow
```

Every "always-pass" quality-gate value has a commented-out production value alongside it — this is a
strong, directly transferable idiom: **ship the file with production thresholds documented in-line as
comments next to the disabled/integration-test value**, so nobody has to hunt a separate prod config to
know what "real" looks like. This maps closely onto our `ToolSpec` parameters / `sites/*.yaml` — note
that here, *all* of the scientific-pipeline parameters (batch sizes, cycle counts, QC thresholds) are
forwarded opaquely as `config` dict keys straight into `SmallMoleculeBindingPipeline(**pipeline_kwargs)`;
`campaign_manager` does not know or validate any of their types or ranges — only its own scheduling keys
(`replicas`, `priority`, `concurrency_cap`, etc., listed in `_cm_keys` in `campaign_manager.py`) are
interpreted. There is **no typed parameter schema at the campaign-manager layer** for tool-specific
knobs — everything scientific is untyped YAML passed through, contrasting with our `ToolSpec` design
which does type/validate stage parameters centrally.

## 6. Adaptivity

Adaptivity here is minimal and coarse: the trigger is purely **counting `n_hits` (finished-replica
count) against a cycle target** — no candidate score, pLDDT, or Rosetta metric ever reaches the
decision layer for `small_molecule_binding` specifically (the docstring says as much: "All replicas use
the same input JSON for now (dummy policy); future versions will generate varied inputs for the exploit
group based on completed pipeline scores" — **explicitly an unfinished placeholder**, not a working
adaptive loop). What varies between cycles: **nothing about structure or parameters** — only *how many*
replicas of the two pre-existing groups get triggered, on a fixed schedule (`max_cycles=1,
explore_n=2, exploit_m=1` in the integration config). The richer adaptivity machinery that
`campaign_manager` *does* have — `Triage`/`Surrogate`/`BudgetController`/`ReplanningController`,
score-based cutoff nudging, drift-triggered replanning, a Thompson-sampling bandit wrapped as an ADR
policy (`BanditSchedulingPolicy`), and even an `LLMSchedulingPolicy` (OpenAI + `instructor`, "compose
`Policy(primary=LLM, fallback=rule)`") — is all present in `src/campaign/adr/policies/` and exercised by
the `ddsim_campaign` example, but **is not used at all** by `small_molecule_binding`. This campaign is
the simplest possible instance of the framework: one dummy rule policy, no triage, no surrogate, no
backpressure, no sharder, no monitor. That is itself informative — the *real, GPU-cost, actually-run*
campaign in this repo is the plainest one, while the sophisticated adaptive machinery lives only in
cheaper/synthetic benchmark campaigns (`ddsim_campaign`, `dreamer_campaign`). Read as evidence: building
rich adaptive-decision machinery is cheap to *write*; wiring it into a real, expensive GPU pipeline where
mistakes cost wall-clock and allocation-hours is where projects stall out — a caution IMPRESS-A should
take seriously given our control models B (LLM oracle) and A (agentic loop) are exactly this kind of
higher-risk wiring.

## 7. State, provenance, restart

- **No mid-campaign checkpoint/restart for this campaign.** `CampaignOperator` inherits generic
  `save_checkpoint_full()`/`load_checkpoint_full()` helpers (wrapping `radical.adr.Operator`'s own
  `save_checkpoint`/`load_checkpoint`, plus an optional `.extra.json` sidecar for campaign-specific state,
  with a version tag checked on load) — but `sm_binding_operator.py` and `run_campaign.py` **never call
  either**. If the SLURM job dies mid-run, the ADR cycle counter, `SmMolBindingPolicy`'s internal state,
  and the CM's in-memory replica bookkeeping are all lost; the run must restart from cycle 0.
- **Per-replica result provenance is durable, but coarse.** `on_replica_done()` writes
  `{work_dir}/{replica_id}_result.json` (`{replica_id, group, status, best_plddt}`) and appends to a
  class-level `_results` list (in-process only, not persisted itself). The pLDDT is scraped by globbing
  `{work_dir}/{replica_id}/*_alphafold/out/binder_scores_*.json` — i.e. provenance recovery after a crash
  would mean re-globbing IMPRESS's own output tree, not reading any campaign_manager ledger.
- **`run_supervised(..., max_failed_ticks=...)`** exists specifically to detect "SLURM preemption"-style
  infrastructure failure (consecutive ticks where everything that finished, failed) and raise
  `CampaignAbortedError` — but `small_molecule_binding`'s `run_campaign.py` does not pass
  `max_failed_ticks`, so this safety net is unused here even though the framework has it.
- **Net read:** this confirms Phase 2's conclusion that nothing in the asyncflow/rhapsody/adr stack gives
  you durability for free — and shows that even a purpose-built "campaign manager" layer built *on top*
  of that stack, when actually pointed at a real GPU campaign, still shipped without exercising its own
  restart path. Durability remains squarely "ours to build," and even a plausible checkpoint API is not
  a substitute for testing it against the real, expensive campaign.

## 8. Deployment on Delta — quoted generously

### `delta_sbatch.sh` (SLURM, GPU partition)

```sh
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=00:30:00
#SBATCH --job-name=sm_binding_campaign
#SBATCH --output=runs/slurm-%j.out
#SBATCH --error=runs/slurm-%j.err
# NOTE: runs/ must exist before sbatch is called.
```

Environment setup inside the job script — note the **Dragon-specific system library wiring**, which is
Delta-specific hard-won knowledge (fabric libs must be found for multi-node Dragon to work at all):

```sh
export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}
dragon-config add --ofi-runtime-lib="${FAB_LIB}"
```

Single-node vs. multi-node Dragon launch mode is chosen from `$SLURM_NNODES`:

```sh
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then DRAGON_MODE="-m"; else DRAGON_MODE="-s"; fi
dragon ${DRAGON_MODE} run_campaign.py --config "${CONFIG}"
```
(`-s` = single-node Dragon runtime, `-m` = multi-node via MPI/OFI fabric — the script picks this
automatically rather than requiring the operator to know it.)

Tool paths default to specific, hard-coded absolute paths on Delta's `/work/hdd` filesystem, overridable
by env var:
```sh
export MPNN_PATH="${MPNN_PATH:-/work/hdd/<project>/$USER/LigandMPNN}"
export COLABFOLD_PATH="${COLABFOLD_PATH:-/work/hdd/<project>/$USER/localcolabfold}"
export FOUNDRY_SIF_PATH="${FOUNDRY_SIF_PATH:-/work/hdd/<project>/$USER/foundry.sif}"
export COLABFOLD_CACHE_DIR="${COLABFOLD_CACHE_DIR:-${SCRATCH}/${USER}/.cache/colabfold}"
```
and the script ends with `rm -rf asyncflow.session*` — cleanup of asyncflow's own session directories,
implying they otherwise accumulate in the working directory across runs (a small but concrete
operational gotcha worth carrying forward).

### `delta_env_setup.sh` (one-time environment build) — the real install order matters

This script encodes an 11-step install order for a Rosetta/AlphaFold2/RFDiffusion3/LigandMPNN stack on
Delta, including several non-obvious fixes:

```sh
"${PIP}" install -q --force-reinstall "setuptools<71"      # step 2 — pinned down for a reason
"${PIP}" install -q radical-asyncflow                       # step 3
"${PIP}" install -q "rhapsody-py[dragon,telemetry]"          # step 4
"${PIP}" install -q -e "${IMPRESS_DIR}"                      # step 5
"${PIP}" install -q -e "${CM_DIR}"                           # step 6
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121   # step 7
"${PIP}" install -q pandas biopandas                         # step 8
"${PIP}" install -q gemmi prody ml-collections dm-tree       # step 9
"${PIP}" install -q "colabfold[alphafold]"
"${PIP}" install -q "jax[cuda12]"                            # step 10
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"   # step 11
```
with the rationale documented in comments — this is exactly the kind of hard-won HPC-deployment
knowledge the review should surface:

> "gemmi: RFDiffusion3 outputs .cif.gz; LigandMPNN's ProDy `parsePDB()` only reads PDB format, so the
> mpnn task converts CIF.GZ → PDB via gemmi. prody, ml-collections, dm-tree: LigandMPNN run.py imports
> these directly; they are not in the LigandMPNN .venv on Delta (**permissions issue**), so they are
> installed here in the shared IMPRESS venv."

AlphaFold2 weights are pre-downloaded once, with a completion marker file to make the step idempotent
across repeated env-setup runs, and are deliberately kept off `/u` (home) to avoid quota exhaustion:
```sh
_cf_marker="${_cf_params}/download_finished.txt"
if [ -f "${_cf_marker}" ]; then echo "AF2 weights already present ... skipping download."
else ... wget ... alphafold_params_2021-07-14.tar ... touch "${_cf_marker}"; fi
```
The script ends with a `_check()` helper that import-tests every dependency (`radical.asyncflow`,
`rhapsody`, `impress`, `campaign-manager`, `torch`, `gemmi`, `prody`, `colabfold`, `jax`, `pyrosetta`)
and reports OK/WARNING per package rather than failing hard on the first broken import — useful for
diagnosing a partially-broken HPC environment without re-running the whole script.

### `pull_foundry.sh` — a discrepancy worth flagging

This script builds the "foundry" container (`docker://rosettacommons/foundry`) via
`apptainer build --sandbox`, then **tars the sandbox directory** to scratch:
```sh
apptainer build --sandbox "$SANDBOX" docker://rosettacommons/foundry
tar -czf "$DEST_TAR" -C /tmp "foundry_sandbox_$$"
```
producing `foundry_sandbox.tar.gz` — but every other reference to this container in this campaign
(`SETUP.txt`, `delta_sbatch.sh`) expects a single-file `.sif` at `FOUNDRY_SIF_PATH`
(`/work/hdd/<project>/$USER/foundry.sif`). **`pull_foundry.sh` does not produce a `.sif`** — either a
separate, undocumented `apptainer build foundry.sif <sandbox-or-tar>` step happens outside this repo, or
this script is a stale/earlier approach that was superseded once someone built the `.sif` by hand.
Either way, **the container-pull path as checked into this repo is not self-consistent** — flag this as
a real gap, not an oversight in this review.

### `SETUP.txt` — required vs. optional env vars (transferable checklist)

```
SCRATCH               [required]  allocation scratch root
SBATCH_ACCOUNT        [required]  SLURM account, e.g. <project>-delta-gpu
FOUNDRY_SIF_PATH       [required]  RFDiffusion3/Foundry Apptainer image (.sif)
MPNN_PATH              [required]  LigandMPNN repo root
COLABFOLD_PATH         [required]  localcolabfold install
COLABFOLD_CACHE_DIR    [optional]  AF2 weights cache (default under $SCRATCH)
IMPRESS_SRC            [optional]  IMPRESS repo root
SM_BINDING_EXAMPLES_DIR [optional] IMPRESS/examples/small_molecule_binding
ENV_DIR                [optional]  venv path (default /u/$USER/ve/impress)
CM_DIR                 [optional]  campaign_manager repo root
```
Every pipeline-quality knob (thresholds, batch sizes, cycle counts) is explicitly said to live in
`config.yaml` only — "No Python files need editing for routine configuration" — a clean separation of
deployment concerns (env vars = filesystem paths/credentials) from science concerns (YAML = pipeline
parameters) worth adopting directly.

## 9. What the `new_cm` rework changed vs. `devel`

`git diff --stat devel origin/new_cm` (212 files, +35804/-4232) shows this is not an incremental patch
but a wholesale replacement of the orchestration core:

- **Removed entirely:** `src/radical/cm/{bookkeeper,enactor,planner}` — a static-planning stack
  (`ga_planner.py`, `heft_planner.py`, `l2ff_planner.py`, `random_planner.py`, a `bookkeeper.py` for
  state tracking, an `enactor` abstraction with a `simulated_enactor.py`). This was a classic
  plan-then-execute HPC scheduler (HEFT/GA are offline task-to-resource mapping heuristics) — i.e. the
  *previous* design in this same repo was static, ahead-of-time scheduling, not adaptive/runtime
  composition at all.
- **Added:** the entire `src/campaign/` package (`AsyncCampaignManager`, scheduler/executor/monitor
  mixins, backpressure, sharder, triage, surrogate, budget controller, replanning, the `adr/` bridge) —
  imported wholesale from a different, apparently more mature sibling project ("SPHERICAL"), per the
  `e26b087` commit message, as an **orphan branch with no shared history**. There is no `CHANGES.md` in
  this repo; the only rationale trail is commit messages (`git log --oneline devel..origin/new_cm`,
  22 commits) — mostly mechanical ("Reorganize workflows...", "Fix paths in dreamer_campaign sbatch
  scripts", "Redact allocation name from batch scripts") plus the two substantive ones: `e26b087`
  (import from SPHERICAL) and `c32f63f` ("small mol campaign instructions" — the commit that added the
  `small_molecule_binding` campaign itself, our primary target).
- Net effect for this review: **the `devel`→`new_cm` transition itself is not a rework of the
  small-molecule-binding campaign** — that campaign is new in `new_cm` and has no `devel`-branch
  ancestor to diff against. The relevant "what changed and why" is one level up: this repo replaced a
  static HEFT/GA planner architecture with an async replica-pool orchestrator plus an optional ADR
  observe/decide/act supervision bridge, and the small-molecule-binding campaign is the first (and only)
  real-GPU-cost consumer of that new architecture.

## 10. Gaps and dead ends

- **`CLAUDE.md` is stale** — describes the donor "SPHERICAL" repo's file layout (`workflows/run_campaign/
  esm2_ddsim_campaign/run_campaing.py`, `src/inference/`) which does not exist in this tree's actual
  `campaigns/` layout. Its architectural description of `AsyncCampaignManager` is accurate; its paths and
  the referenced `docs/adr_adaptive_decisions.md` are not (that file does not exist on `origin/new_cm`).
- **The adaptive policy for `small_molecule_binding` is an explicit placeholder.** Per the workflow
  docstring: "All replicas use the same input JSON for now (dummy policy); future versions will generate
  varied inputs for the exploit group based on completed pipeline scores." The "explore vs. exploit"
  framing in the config/operator names is aspirational — as shipped, both groups run identical inputs;
  only the replica *count* differs by cycle.
  - The `run_campaign.py` cycle-0 kickstart is a manual workaround, not a clean API: both groups are
  declared `replicas: 0` (ADR-triggered) so the CM has zero pending work at start-of-day; if
  `run_supervised()` were entered immediately, the ADR loop's first tick would trigger cycle 0 anyway —
  but the code instead calls `cm.trigger_dependent()` directly for cycle 0 *and* manually pokes the
  policy's private state (`operator.policy._cycle_launched = True; operator.policy._cumulative_total =
  n_explore + n_exploit`) so the policy's own first tick doesn't double-trigger. This is fragile
  (reaches into a policy's private attributes from the runner) and is explicitly commented as a
  workaround in the code.
- **`pull_foundry.sh` produces a `.tar.gz` of a sandbox, not the `.sif` every other script expects** —
  see §8. Either an undocumented conversion step exists outside the repo, or this is dead/superseded code.
- **Checkpoint/restart machinery exists but is unexercised** for the one real campaign in this repo — see
  §6/§7.
- **No typed parameter schema at the campaign-manager layer** for scientific/tool parameters — everything
  is untyped YAML forwarded straight into `SmallMoleculeBindingPipeline(**kwargs)`; validation, if any,
  happens inside IMPRESS, invisible to this layer.
- **Provenance for pLDDT-scraping is filesystem-glob-based** (`glob.glob(".../binder_scores_*.json")`),
  fragile to any change in IMPRESS's own output directory naming.

## Patterns for Phase 4 — adopt / adapt / avoid

1. **Adopt — supervise, don't surrender the loop.** `run_supervised(cm, operator, tick_s)`'s pattern of
   running `Operator.run()` as a background task raced against your own `await cm.wait()`, with the
   operator restricted to a small `@act` lever surface, is a working, load-bearing resolution to exactly
   the Phase 2 conflict (`Operator.run()` owning a full loop). If IMPRESS-A ever wants to let a
   `radical.adr`-style policy object drive `decide`, wrap it this way rather than calling `.run()` as the
   top-level await.
2. **Adopt — validate the stopping condition at construction, not at runtime.**
   `CampaignOperator._validate_stopping_condition()` (raise `ValueError` if there's no `@goals` and no
   `max_cycles`) is a one-line guardrail against campaigns that silently run forever. Cheap to copy into
   our `ControlPolicy` construction path.
3. **Adopt — deployment idiom of "prod value in a comment next to the disabled value."** Every quality
   gate in `config.yaml` documents its production number as an inline comment beside the
   integration-test value. Directly reusable for our `sites/*.yaml` and `ToolSpec` defaults.
4. **Adopt — the Delta operational knowledge wholesale.** The Dragon fabric-library `LD_LIBRARY_PATH`
   wiring, the `-s`/`-m` single/multi-node dispatch based on `$SLURM_NNODES`, the `setuptools<71` pin,
   the gemmi/prody/ml-collections/dm-tree install-order fixes for LigandMPNN, the AF2-weights idempotent
   download-with-marker pattern, and keeping model-weight caches off `/u` — all directly reusable for any
   IMPRESS-A deployment on Delta.
5. **Adapt — CampaignView as an anti-corruption layer.** `CampaignView`/`CampaignViewProtocol` cleanly
   isolates all CM-state coupling behind one small `observe()`/lever-methods interface so policies can be
   unit-tested with a fake view. Worth adapting the *shape* of this (a narrow protocol between "decision
   layer" and "execution state") even though our `ControlPolicy` will need a richer surface (arbitrary
   graph composition, not just pre-registered levers).
6. **Avoid — treating "campaign manager" as a DAG composer.** This system's actual scientific DAG lives
   entirely inside IMPRESS and is invisible to `campaign_manager`; the orchestrator here only fans out
   *replicas of an already-fixed pipeline*. That's a materially smaller problem than IMPRESS-A's
   runtime-composed-arbitrary-DAG target — don't mistake this codebase's simplicity for evidence that the
   simpler design suffices; it suffices here only because IMPRESS already solved composition internally.
7. **Avoid — reaching into a policy's private attributes from the runner** (the cycle-0 kickstart
   workaround in `run_campaign.py`). If an outer loop needs to seed initial state, that should be a
   documented policy constructor argument or an explicit `seed()`/`prime()` method, not
   `operator.policy._cycle_launched = True` from outside.
8. **Avoid — shipping a container-pull script whose output format doesn't match what the rest of the
   deployment expects** (the `pull_foundry.sh` sandbox-tar vs. `.sif` mismatch). A footgun for the next
   person deploying from this repo; make sure our own container-pull scripts produce exactly the artifact
   our sbatch scripts reference, and test the two together.

## What could not be determined

- Whether IMPRESS's own inner `SmallMoleculeBindingPipeline` DAG (RFD3→MPNN→PackMin→FastRelax→
  FilterShape→AlphaFold2) is statically fixed or composed at runtime — out of scope for this repo; that
  is Part A's territory.
- How (or whether) `foundry_sandbox.tar.gz` actually becomes `foundry.sif` in practice — no conversion
  step is present in this repo.
- Whether `small_molecule_binding` has ever actually completed a full production run on Delta (the
  config in the repo is an "integration-test" sizing; no run logs, benchmark JSON, or results are checked
  in for this campaign, unlike `ddsim_campaign`/`esm2_ddsim_campaign` which do have benchmark scripts and
  plotting tooling).
- The rationale for choosing `radical.adr`'s `Policy`/`Decision`/`Operator` over rolling
  `campaign_manager`'s own decision abstraction — no design doc exists in this repo (the `CLAUDE.md`
  pointer to `docs/adr_adaptive_decisions.md` is dead).

## Top 5 concretely reusable things (ranked)

1. **The `run_supervised()` "operator-as-background-task-alongside-your-own-wait()" pattern** — the
   cleanest available real-world resolution to the ADR-`Operator.run()`-owns-the-loop conflict Phase 2
   identified. Highest value because it directly unblocks a design question we already flagged as open.
2. **The Delta deployment scripts' hard-won operational fixes** (Dragon fabric library paths, `-s`/`-m`
   node-count dispatch, `setuptools<71`, LigandMPNN's missing-deps-in-its-own-venv workaround, AF2
   weights idempotent download) — concrete, immediately copyable knowledge for our own Delta deployment,
   saving real debugging time.
3. **`CampaignOperator._validate_stopping_condition()`** — a one-line, cheap-to-adopt guardrail against
   runaway campaigns.
4. **The `config.yaml` "prod value as inline comment" documentation idiom** — costs nothing, directly
   improves our own `sites/*.yaml`/`ToolSpec` defaults' usability.
5. **The `CampaignView`/`CampaignViewProtocol` narrow-adapter pattern** for decoupling a decision layer
   from live orchestrator state for unit-testability — adapt the shape, not the specific interface, into
   our `ControlPolicy` testing story.
