# Protein Binding

Location: [`examples/protein_binding/`](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/protein_binding)

An IMPRESS pipeline for iterative computational design of PDZ-domain
protein binders against a target peptide. Starting from a set of input PDZ
PDB structures, the pipeline runs ProteinMPNN sequence design, Boltz-2
complex structure prediction, and pLDDT/PTM/PAE scoring in a loop. An
adaptive decision function compares per-pass scores and spawns child
pipelines for proteins whose predicted quality degrades, trying the
next-ranked MPNN sequence instead.

## Inputs

Input PDB structures are placed in `<input_base_path>/prod_in/<name>_in/`
(e.g. `prod_in/p1_in/`), one file per PDZ scaffold. No ligand or `.params`
files are needed — this is protein-peptide, not small-molecule, binder
design.

### Pipeline parameters

`ProteinBindingPipeline` reads these from its constructor kwargs (i.e.
from `PipelineSetup.config`):

| Parameter | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Directory containing `scripts/` and `mpnn_wrapper.py` |
| `input_base_path` | `base_path` | Parent of `prod_in/` |
| `output_base_path` | `base_path` | Parent of `af_pipeline_outputs_multi/` and the per-pass stats CSVs |
| `mpnn_path` | `$MPNN_PATH` | Path to a ProteinMPNN checkout; raises `ValueError` if neither the kwarg nor the env var is set |
| `peptide_seq` | `"EGYQDYEPEA"` | Target peptide sequence co-folded with each design |
| `max_passes` | `10` | Maximum design/predict iterations per pipeline |
| `num_seqs` | `10` | Number of MPNN sequences generated per job |
| `seq_rank` | `0` | Index into ranked sequences to fold (0 = best score) |

`is_child`, `passes`, `start_pass`, `sub_order`, `iter_seqs`, and
`previous_scores` are set by the adaptive function when it spawns a child
pipeline; they don't normally need to be supplied.

## Pipeline Stages

| Task | Type | Script / Tool | Resource |
|---|---|---|---|
| `s1` | HPC | `scripts/s1_mpnn.sh` → `mpnn_wrapper.py` (ProteinMPNN) | GPU |
| `s2` | local | Parses MPNN FASTA output, ranks by score, populates `iter_seqs` | CPU |
| `s3` | local | Writes a Boltz input FASTA (designed sequence + target peptide) per structure | CPU |
| `s4` | HPC | `scripts/s4_boltz.sh` (`boltz predict`, Boltz-2) | GPU |
| `s4_post_exec` | local | Copies the best-model PDB (renaming Boltz chain IDs `pdz`/`pep` → `A`/`B`) into `best_models/` and `mpnn/job_<N>/`, and the confidence JSON into `best_ptm/` | CPU |
| `s5` | HPC | `scripts/s5_plddt_extract.sh` → `plddt_extract_pipeline.py` (PyRosetta + BioPandas) | CPU |

- `s1`, `s4` and `s5` capture their stdio (the framework default). No GPU
  placement hints are set on the tasks or in the scripts; GPU assignment
  is left to the execution backend.
- `s1` always designs chain `A`. On pass 2+ its input is the previous
  pass's best-model PDB.
- `s3` checks for pre-computed MSAs under `~/boltz/msa_cache/boltz_results_<name>/msa/`.
  If both chain MSAs exist it references them in the FASTA; otherwise it
  writes `empty` and Boltz runs in single-sequence mode. This path is
  hard-coded (`protein_binding.py:152`) and does not follow
  `delta_env_setup.sh`, which writes MSAs to `${WORK_DIR}/boltz/msa_cache`;
  link one to the other until that is fixed (framework backlog F23).
- `s4`/`s4_post_exec` run concurrently across all structures in a pass via
  `asyncio.gather`. If every `s4_post_exec` fails the pass raises
  `RuntimeError` rather than scoring empty output.
- `s1`, `s4`, and `s5` tolerate spurious backend exceptions: if the task's
  expected output exists on disk, the error is logged and treated as
  success.
- `s5` writes `avg_plddt`, `ptm` (max iPTM+PTM), and `avg_pae`
  (cross-interface predicted aligned error) to a per-pass CSV.

`s4_boltz.sh` reads these environment variables:

| Variable | Default | Effect |
|---|---|---|
| `BOLTZ_VENV` | `$VIRTUAL_ENV` | Environment whose `bin/` provides the `boltz` CLI |
| `BOLTZ_CACHE_DIR` | `$HOME/.boltz` | Boltz weights/CCD cache (`--cache`) |
| `BOLTZ_USE_MSA_SERVER` | unset | Set to `1` to add `--use_msa_server` (off by default) |

## Adaptive Flow

```
s1 (mpnn) --> s2 (rank seqs) --> s3 (write FASTA) --> s4 (Boltz-2 x N, parallel)
                                                                  |
                                                      s4_post_exec (stage files x N, parallel)
                                                                  |
                                                           s5 (pLDDT extract)
                                                                  |
                                                       adaptive_decision()
                                            +--------------------+--------------------+
                                     score improved                              score degraded
                                  (keep in pipeline)                (spawn child pipeline, seq_rank+1)
                                                                  |
                                                        passes += 1 (up to max_passes)
```

`adaptive_decision()` (defined inside `impress_protein_bind()` in
`run_protein_binding.py`, and declared on the `local` backend with
`@flow.function_task(backend="local")`) runs after each pass and reads `<output_base_path>/af_stats_<name>_pass_<N>.csv`:

| Pass | Condition | Action |
|---|---|---|
| Pass 1 | No prior scores | Save current scores as baseline; continue |
| Pass 2+ | `current_score <= previous_score` (improved or held) | Keep the protein in the current pipeline |
| Pass 2+ | `current_score > previous_score` (degraded) | Move the protein to a new child pipeline at `seq_rank + 1` |

When one or more proteins degrade, a child pipeline named
`<parent>_sub<N>` is created: its input directory
(`prod_in/<parent>_sub<N>_in/`) is populated with the degraded proteins'
best-model PDBs, and it inherits `iter_seqs` (skipping `s1`/`s2` on its
first pass, since sequences already exist) but uses the next-best MPNN
candidate (`seq_rank + 1`). Children inherit the parent's
`input_base_path`/`output_base_path`. Nesting is capped at
`MAX_SUB_PIPELINES = 3`. If the parent's tracked protein list is emptied
after spawning, it sets `kill_parent = True` and terminates.

`run_protein_binding.py` enables `ImpressManager` telemetry
(`checkpoint_path="./telemetry/"`) and emits three custom events from the
adaptive function: `impress.ProteinScore`, `impress.ChildPipelineSpawned`,
and `impress.PassSummary`. A telemetry summary is printed when the run
finishes.

## Output Structure

```
<input_base_path>/
  prod_in/<name>_in/                          # input PDB files
<output_base_path>/
  af_pipeline_outputs_multi/<name>/
    mpnn/job_<N>/seqs/                         # MPNN FASTA files for pass N
    mpnn/job_<N>/<protein>.pdb                 # copy of the pass-N best model
    af/fasta/                                  # Boltz input FASTAs (designed + peptide)
    af/prediction/best_models/                 # best-model PDB per structure
    af/prediction/best_ptm/                    # confidence JSON per structure
    af/prediction/dimer_models/<protein>/      # full Boltz outputs
      boltz_results_<protein>/predictions/<protein>/
    af/prediction/logs/
  af_stats_<name>_pass_<N>.csv                 # per-pass scores: ID, avg_plddt, ptm, avg_pae
```

## Running It

`run_protein_binding.py` is configured entirely through environment
variables:

| Variable | Default | Description |
|---|---|---|
| `IMPRESS_BACKEND` | `dragon` | The `compute` backend: `dragon` → `DragonExecutionBackend`; anything else → `ConcurrentExecutionBackend(ProcessPoolExecutor())` (both from `rhapsody.backends`). A second, `local` thread-pool backend always runs the adaptive callback |
| `IMPRESS_N_PIPELINES` | `16` | Number of root pipelines (`p1` … `pN`) |
| `IMPRESS_MAX_PASSES` | `10` | `max_passes` for each pipeline |
| `IMPRESS_SCRIPTS_DIR` | the example directory | Passed as `base_path` |
| `IMPRESS_BASE_DIR` | `IMPRESS_SCRIPTS_DIR` | Passed as `input_base_path` |
| `IMPRESS_OUTPUT_DIR` | `IMPRESS_SCRIPTS_DIR` | Passed as `output_base_path` |
| `MPNN_PATH` | — | ProteinMPNN checkout (required) |

For a local (non-Dragon) run:

```bash
cd examples/protein_binding
export MPNN_PATH=/path/to/ProteinMPNN
export IMPRESS_BACKEND=local IMPRESS_N_PIPELINES=2 IMPRESS_MAX_PASSES=2
python run_protein_binding.py
```

The runner follows the standard IMPRESS pattern: it creates the engine over
two named backends, passes the engine to the manager, declares the adaptive
callback on the `local` thread pool, and shuts the engine down itself:

```python
compute = await DragonExecutionBackend(name="compute")
local = await ConcurrentExecutionBackend(
    ThreadPoolExecutor(max_workers=N_PIPELINES), name="local")
flow = await WorkflowEngine.create(backend=[compute, local])
manager = ImpressManager(
    flow,
    telemetry_config={"checkpoint_path": "./telemetry/", "resource_poll_interval": 5.0},
    telemetry_subscribers=[_on_task_event],
)

@flow.function_task(backend="local")
async def adaptive_decision(pipeline): ...

try:
    await manager.start(pipeline_setups=pipeline_setups)
finally:
    await flow.shutdown()
```

The callback must run on a thread pool, because it mutates the live
pipeline object. The decorator rebinds `adaptive_decision` to the task, so
child configs that pass `'adaptive_fn': adaptive_decision` carry the task,
not the bare function.

### On NCSA Delta

Two helper scripts target Delta's `gpuA40x4` partition:

- **`delta_env_setup.sh`** — run once on a login node (requires
  `WORK_DIR`, e.g. `/work/nvme/<project>/$USER`; options `--env-dir`,
  `--impress-dir`, `--python`). Creates a Python ≥ 3.11 venv in
  `${WORK_DIR}/ve/impress` with `radical-asyncflow`,
  `rhapsody-py[dragon,telemetry]`, IMPRESS (editable), PyTorch, and
  PyRosetta; builds a separate Boltz conda env in `${WORK_DIR}/ve/boltz`;
  warms the Boltz cache in `${WORK_DIR}/boltz`; and pre-computes MSAs into
  `${WORK_DIR}/boltz/msa_cache` for every `prod_in/p*_in/*.pdb` under
  `$IMPRESS_BASE_DIR` (default `${WORK_DIR}/IMPRESS_inputs`).
- **`delta_gpu_run.sh`** — the batch job (`sbatch delta_gpu_run.sh`; create
  `logs/` in the example directory first, since Slurm writes the job logs
  there; requires `WORK_DIR`). Sets up Delta's CUDA/MPI/libfabric paths,
  activates `${IMPRESS_VENV:-${WORK_DIR}/ve/impress}`, configures Dragon,
  exports `MPNN_PATH`, `BOLTZ_VENV`, `BOLTZ_CACHE_DIR`, and the `IMPRESS_*`
  path variables (`IMPRESS_BASE_DIR=${WORK_DIR}/IMPRESS_inputs`,
  `IMPRESS_OUTPUT_DIR=${WORK_DIR}/IMPRESS_outputs`), and launches
  `dragon -s run_protein_binding.py` (`-m` for multi-node jobs), or plain
  `python3` when `IMPRESS_BACKEND=local`.

!!! note

    `delta_gpu_run.sh` defaults `BOLTZ_VENV` to `${HOME}/ve/boltz`, while
    `delta_env_setup.sh` builds the Boltz env in `${WORK_DIR}/ve/boltz`.
    Export `BOLTZ_VENV=${WORK_DIR}/ve/boltz` before `sbatch` until the
    default is aligned (framework backlog F23).

### Alternate entry point

- **`run_nonadaptive.py`** — 16 pipelines with no `adaptive_fn` on
  `DragonExecutionBackend`, used as a baseline to measure the benefit of
  the adaptive strategy. It passes no path config, so it relies on
  `MPNN_PATH` and the current working directory.
