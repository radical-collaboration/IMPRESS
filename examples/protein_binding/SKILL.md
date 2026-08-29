# Protein Binding Use Case — SKILL.md

## What it does

5-step adaptive protein design pipeline running on Delta HPC (gpuA40x4):

| Step | Task | Type | Notes |
|------|------|------|-------|
| s1 | ProteinMPNN — generate sequences | local (subprocess) | GPU via `CUDA_VISIBLE_DEVICES` |
| s2 | Sequence ranking | local (pure Python) | sorts by MPNN score |
| s3 | FASTA generation | local (pure Python) | writes `.fa` for each target |
| s4 | AlphaFold multimer prediction | local (subprocess) | GPU, runs via Apptainer |
| s4_post | Copy best models | local (pure Python) | glob → shutil.copy |
| s5 | pLDDT extraction | local (subprocess) | writes `af_stats_<name>_pass_<n>.csv` |

Passes repeat up to `max_passes` times. The adaptive function reads pLDDT CSVs and can spawn child pipelines for proteins that degrade.

---

## Key files

```
protien_binding_usecase/
├── run_protein_binding.py      # entry point — backend, GPU policy, ImpressManager
├── delta_gpu_run.sh            # SLURM script — Dragon launcher
├── delta_env_setup.sh          # one-time venv setup (~/ve/impress/)
├── af2_multimer_reduced.sh     # Apptainer wrapper for AlphaFold multimer
├── mpnn_wrapper.py             # ProteinMPNN CLI wrapper
└── plddt_extract_pipeline.py   # reads AF JSON → writes CSV
```

Pipeline implementation: `/scratch/bblj/mgoliyad1/IMPRESS/src/impress/pipelines/protein_binding.py`

---

## Environment variables

| Variable | Set in | Purpose |
|----------|--------|---------|
| `SCRATCH` | user env | base scratch path (`/scratch/bblj`) |
| `MPNN_PATH` | `delta_gpu_run.sh` | path to ProteinMPNN repo |
| `AF2_DATABASE` | `delta_gpu_run.sh` | AlphaFold database dir |
| `AF2_SIF` | `delta_gpu_run.sh` | AlphaFold Apptainer image |
| `IMPRESS_INPUT_DIR` | `delta_gpu_run.sh` | dir containing `{name}_in/` folders |
| `IMPRESS_OUTPUT_DIR` | `delta_gpu_run.sh` | output root (af_pipeline_outputs_multi/) |
| `IMPRESS_SCRIPTS_DIR` | `delta_gpu_run.sh` | dir with mpnn_wrapper.py, af2_multimer_reduced.sh |
| `SBATCH_ACCOUNT` | user env | SLURM account (e.g. `bblj-delta-gpu`) |

`IMPRESS_PRE_EXEC` was removed — the venv is activated in the SLURM script before `dragon -s`, so all subprocesses inherit the environment.

---

## Dragon integration

**Backend**: `DragonExecutionBackendV2` (flow engine only — no tasks dispatched to Dragon workers).

**Why not V3**: Dragon worker subprocesses silently hang when a subprocess uses GPU ops (`cupy`, `torch`, Apptainer). Same failure mode documented in `DeepDriveSim/workflows/miniapps_workflow/miniapps_workflow.py`.

**Fix**: All pipeline steps are `local_task=True`. GPU steps (s1, s4) run as `asyncio.create_subprocess_shell()` on the Dragon head process, which has direct GPU access from SLURM allocation. Dragon manages the `ImpressManager`/`WorkflowEngine` loop; it never dispatches tasks to workers.

**GPU affinity**: `_find_gpus()` + `_make_policy()` in `run_protein_binding.py` use `dragon.native.machine.System()` to discover GPUs and build a `dragon.infrastructure.policy.Policy` with `gpu_affinity`. The policy's GPU list is passed as `CUDA_VISIBLE_DEVICES` to each subprocess via `_gpu_env()` in the pipeline.

```python
# To change GPU count per pipeline (default n_gpus=1 for MPNN):
policy = _make_policy(all_gpus, idx=0, n_gpus=1)
```

**Launcher** (`delta_gpu_run.sh`):
```bash
source ~/ve/impress/bin/activate
dragon-config add --ofi-runtime-lib="${FAB_LIB}"
rm -rf asyncflow.session.*
dragon -s run_protein_binding.py     # -s = single-node
```

**SLURM resource request**: `--tasks-per-node=4`, `--gpus=4`, `--exclusive` (matches Dragon's single-node layout).

---

## Key design decisions

### Three separate path env vars
`base_path` was split into `IMPRESS_INPUT_DIR` / `IMPRESS_OUTPUT_DIR` / `IMPRESS_SCRIPTS_DIR` so input data, outputs, and scripts can live in different locations independently.

### Output dirs auto-created in `__init__`
`os.makedirs(..., exist_ok=True)` is called in `ProteinBindingPipeline.__init__` for all required subdirs. No manual `mkdir` needed in the SLURM script.

### `s4_post` replaces `post_exec`
`post_exec` in task descriptions is a RADICAL-Pilot artifact — `ConcurrentExecutionBackend` and Dragon never execute it. Replaced with a `local_task=True` coroutine using `glob` + `shutil.copy` to move `ranked_0.pdb` and `ranking_debug.json` to `best_models/` and `best_ptm/`.

### AlphaFold container flags
- `--no-home`: prevents host's newer Biopython from shadowing the container's version (`SCOPData` import error)
- `--run_relax` removed: not supported by this container version
- Database bind: `/scratch/rhaas/SUP-5301/database:/database`
- Container: `/scratch/rhaas/SUP-5301/alphafold.sif`

---

## One-time setup

```bash
export SCRATCH=/scratch/bblj
cd /scratch/bblj/mgoliyad1/IMPRESS/examples/protien_binding_usecase
bash delta_env_setup.sh          # creates ~/ve/impress/

# Unzip inputs (GNU tar, not zip):
cd /scratch/bblj/mgoliyad1/IMPRESS_inputs
tar -xf prod_in.tar              # or whatever archive name
```

## Submitting a job

```bash
export SCRATCH=/scratch/bblj
export SBATCH_ACCOUNT=bblj-delta-gpu
cd /scratch/bblj/mgoliyad1/IMPRESS/examples/protien_binding_usecase
sbatch delta_gpu_run.sh
```

## Checking results

```bash
# pLDDT scores per pass:
cat af_stats_p1_pass_1.csv

# AlphaFold best models:
ls IMPRESS_outputs/af_pipeline_outputs_multi/p1/af/prediction/best_models/

# Full logs:
tail -f logs/impress_<jobid>.out
```
