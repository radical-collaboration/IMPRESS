# Small Molecule Binding

Location: [`examples/small_molecule_binding/`](https://github.com/radical-collaboration/IMPRESS/tree/main/examples/small_molecule_binding)

An IMPRESS pipeline for iterative computational design of protein binders
against a small-molecule ligand. Starting from a ligand-containing target
structure, the pipeline runs backbone diffusion, sequence design, energy
minimization, structural validation, and fold prediction in a loop, using
an ensemble-history-based adaptive router to direct the search toward
productive regions of structure-sequence space rather than fixed pass/fail
gating alone.

## Inputs

Each pipeline reads its inputs from `input_dir` when given (absolute, or
relative to `base_path`), else from `<base_path>/<pipeline_name>_in/`. The
runner passes the absolute `examples/small_molecule_binding/p{i}_in/`, one
directory per pipeline.

| File | Required | Description |
|---|---|---|
| `ALR_binder_design.json` | Yes | RFDiffusion3 design config (target structure, hotspot residues, diffusion settings) |
| `fixed_residues.txt` | Yes | Space-separated residue indices held fixed during MPNN sequence design |
| `<ligand>.params` | Yes | Rosetta ligand parameter file (e.g. `ALR.params`); filename must match `ligand_params` |
| `<ligand>.smiles` | Yes (`boltz`) | Ligand SMILES for Boltz-2 co-folding (e.g. `ALR.smiles`); stem must match `ligand_params` |
| `common_filenames.txt` | Yes (`filter_energy`) | Accepted filenames for ligand energy filtering |
| `input_pdbs/` | Optional | Target PDB files referenced by the diffusion config |

### Configurable parameters

| Parameter | Default | Description |
|---|---|---|
| `base_path` | `os.getcwd()` | Root directory for all task subdirectories and inputs |
| `input_dir` | `<name>_in` | Input directory (absolute, or relative to `base_path`) |
| `scripts_path` | `<base_path>/scripts` | Directory holding the tool wrapper scripts |
| `mpnn_dir` | env `MPNN_DIR` | Path to a LigandMPNN checkout (required; `ValueError` if unset) |
| `foundry_sif_path` | env `FOUNDRY_SIF_PATH` | Apptainer image containing RFDiffusion3 (required) |
| `boltz_cache_path` | env `BOLTZ_CACHE` | Boltz-2 model cache (required) |
| `ligand_params` | `ALR.params` | Ligand parameter filename (relative to the input directory) |
| `mock` | `False` | Run with lightweight mock tasks — no HPC tools required |
| `num_refine_cycles` | `3` | MPNN → PackMin cycles per backbone attempt |
| `mpnn_ensemble_size` | `1` | Independent sequence batches generated on cycle 0 |
| `diffusion_batch_size` | `2` | Backbone models generated per RFDiffusion3 call |
| `rfd3_partial_t` | `10.0` | RFD3 partial-diffusion noise (Å) for guided backbone feedback |
| `max_tasks` | `300` | Total ensemble entries before the pipeline stops |
| `start_delay` | `0` | Seconds `run()` waits before its first stage (set by the runner to stagger pipelines sharing a GPU) |

These are the class defaults. The runner's `PROD` config
(`run_small_molecule_binding.py`) overrides several of them and the
thresholds below, e.g. `diffusion_batch_size=4`, `num_refine_cycles=2`,
`mpnn_ensemble_size=10`, `backbone_max_ca_deviation=1.0`,
`fold_min_plddt=75.0`.

### Quality thresholds

| Parameter | Default | Metric |
|---|---|---|
| `backbone_max_ca_deviation` | `2.0 Å` | Max CA deviation from the diffusion target |
| `backbone_min_ss_fraction` | `0.2` | Minimum helix + sheet fraction |
| `fastrelax_max_interact` | `0.0 REU` | Protein-ligand interaction energy |
| `fastrelax_max_total_score` | `0.0 REU` | Total Rosetta score |
| `fastrelax_max_fa_rep` | `150.0 REU` | Steric clash energy |
| `interface_min_sc` | `0.5` | Minimum shape complementarity |
| `fold_min_plddt` | `70.0` | Minimum mean pLDDT from Boltz-2 |
| `fold_min_ligand_iptm` | `None` (off) | Minimum Boltz-2 protein-ligand interface confidence |

## Pipeline Stages

| Task | Type | Script / Tool | Resource |
|---|---|---|---|
| `rfd3` | HPC | `scripts/rfd3.sh` (RFDiffusion3 via Apptainer) | GPU |
| `analysis_backbone` | local | Reads JSON metrics from the `rfd3` output directory | CPU |
| `mpnn` | HPC | `scripts/mpnn.sh` → `scripts/mpnn_run.py` (LigandMPNN) | CPU |
| `analysis_sequence` | local | Reads `.fa` headers from MPNN `seqs/` output | CPU |
| `packmin` | HPC | `scripts/packmin.sh` → `scripts/packmin.py` (PyRosetta pack + minimize) | CPU |
| `analysis_packmin` | local | Reads `_packmin_score.json` | CPU |
| `fastrelax` | HPC | `scripts/fastrelax.sh` → `scripts/fastrelax.py` (Rosetta FastRelax) | CPU |
| `analysis_fastrelax` | local | Reads the `.fasc` score file | CPU |
| `filter_shape` | HPC | `scripts/filter_shape.sh` → `scripts/filter_shape.py` (PyRosetta shape complementarity) | CPU |
| `analysis_interface` | local | Reads `shape_complementarity_values.txt` | CPU |
| `boltz` | HPC | `scripts/boltz.sh` (Boltz-2 protein-ligand co-folding) | GPU |
| `analysis_fold` | local | Reads Boltz-2 `confidence_*.json` files | CPU |

The fold step is still called `STEP_AF2` in the state machine; the name
predates the switch from ColabFold to Boltz-2.

The pipeline runs as a `while self.next_step != STEP_DONE` state machine,
calling `adaptive_decision()` after every analysis step:

```
STEP_RFD3  --> analysis_backbone --> adaptive_decision()
STEP_MPNN  --> refine cycle:
                   for each cycle:
                       mpnn --> analysis_sequence --> adaptive_decision()
                       packmin --> analysis_packmin --> adaptive_decision()
STEP_FASTRELAX --> analysis_fastrelax --> adaptive_decision()
STEP_INTERFACE --> analysis_interface --> adaptive_decision()
STEP_AF2       --> analysis_fold       --> adaptive_decision() --> STEP_RFD3 (loop)
```

The MPNN + PackMin inner refinement cycle runs `num_refine_cycles` (default
3) iterations: cycle 0 generates `mpnn_ensemble_size` independent sequence
candidates from the best backbone; later cycles generate one candidate from
the current best packed structure. PackMin is skipped on the final cycle.

## Adaptive Flow

Unlike the other two examples, this pipeline never spawns child pipelines
— all adaptivity happens via `next_step`/state transitions inside a single
pipeline instance, and termination is budget-bounded (`max_tasks`), not
convergence-bounded.

Every analysis task appends `(type, score, input_path, output_path)` to
`pipeline.state['ensemble']`. For a given stage, `adaptive_decision()`
computes:

- **`overall_avg`** — mean score across all prior entries of that type.
- **`selective_avg`** — mean score of prior entries whose structural or
  sequence similarity to the current result (Kabsch CA-RMSD for
  structures, per-position identity for sequences) is on the "similar"
  side of the mean pairwise similarity.

A result is in a **productive neighbourhood** when
`selective_avg > overall_avg`.

| After step | Condition | Next step |
|---|---|---|
| `backbone` | Fails hard thresholds | `STEP_RFD3` — retry |
| `backbone` | No prior data, or `selective_avg > overall_avg` | `STEP_MPNN` — proceed |
| `backbone` | `selective_avg <= overall_avg` | `STEP_RFD3` — unproductive region, retry |
| `sequence` | No prior data, or `selective_avg >= overall_avg` | `STEP_MPNN` (reset retry count) |
| `sequence` | `selective_avg < overall_avg`, retries `< 3` | `STEP_RETRY_SEQ` — rerun MPNN, same cycle |
| `sequence` | Retries exhausted (`>= 3`) | `STEP_RFD3` — abandon this backbone |
| `packmin` | Always | `STEP_MPNN` — continue refinement cycle |
| `fastrelax` | Pass / fail | `STEP_INTERFACE` / `STEP_MPNN` retry; `STEP_RFD3` once retry metrics stop improving, or after 5 attempts |
| `interface` | Pass / fail | `STEP_AF2` / `STEP_MPNN` retry; `STEP_RFD3` once retry metrics stop improving, or after 5 attempts |
| `fold` | `selective_avg > overall_avg` | `STEP_RFD3`, with the current fold decoy fed back as `rfd3_input_pdb` (guided diffusion) |
| `fold` | Otherwise | `STEP_RFD3`, with `rfd3_input_pdb` cleared (start from scratch) |

Fold analysis never sets `STEP_DONE` — the loop is intentionally
open-ended, and the pipeline only terminates when `max_tasks` ensemble
entries have accumulated.

## Output Structure

```
<base_path>/                     # the runner's work dir
  <pipeline_name>/
    <N>_rfd3/out/                # backbone diffusion outputs
    <N>_mpnn/out/seqs/           # FASTA files with confidence scores
    <N>_mpnn/out/packed/         # packed PDB structures
    <N>_packmin/out/             # minimized PDB + score JSON
    ...
    <N>_boltz/out/               # Boltz-2 predictions + confidence JSONs
```

`<N>` is the pipeline's running task count, so the numbers depend on the
route taken, not on the stage.

## Running It

On NCSA Delta, `delta_env_setup.sh` builds the environment and
`sbatch delta_gpu_run.sh` launches the runner under Dragon. To run it
directly:

```bash
cd examples/small_molecule_binding
export MPNN_DIR=... FOUNDRY_SIF_PATH=... BOLTZ_CACHE=...
IMPRESS_BACKEND=local python run_small_molecule_binding.py --n-pipelines 1
```

| Setting | Default | Description |
|---|---|---|
| `IMPRESS_BACKEND` | `dragon` | The `compute` backend: `dragon` → `DragonExecutionBackend`; anything else → `ConcurrentExecutionBackend(ProcessPoolExecutor())`. A second, `local` thread pool runs the declared adaptive callback |
| `--n-pipelines` / `IMPRESS_N_PIPELINES` | `PROD.n_pipelines` (4) | Number of pipelines; each needs its own `p{i}_in/` |
| `--work-dir` / `IMPRESS_WORK_DIR` | `examples/small_molecule_binding/logs` | Run directory, passed as `base_path` |
| `MPNN_DIR`, `FOUNDRY_SIF_PATH`, `BOLTZ_CACHE` | — | Tool paths (required) |

Prefer the command-line flags under Dragon: on a multi-node run,
environment variables set by the launcher do not reach the runner. Pipeline
thresholds live in the `PROD` `RunConfig` at the top of
`run_small_molecule_binding.py`.

Two alternate entry points are also provided:

- **`run_nonadaptive.py`** — a fixed routing table (every stage always
  "passes" and proceeds linearly, with no ensemble comparison or guided
  backbone feedback), used as a baseline comparison.
- **`run_test_small_molecule_binding.py`** — a mock dry run (`mock=True`,
  routing to `mock.py`'s placeholder tasks) that exercises the full state
  machine and adaptive routing logic with no external HPC tools required;
  terminates after 100 ensemble entries.

The mock run still constructs the real pipeline class and imports the
runner, so set placeholder tool paths and a non-Dragon backend:
`MPNN_DIR=x FOUNDRY_SIF_PATH=x BOLTZ_CACHE=x IMPRESS_BACKEND=local python run_test_small_molecule_binding.py`.
It writes `p1/` into the current directory, so run it from a scratch copy.
