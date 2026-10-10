# PyRosetta

**One-line identity.** The Python-bound (binder/pybind11-generated) interface to the full Rosetta C++ library, packaged with its own `pyrosetta.distributed` layer that includes a Dask-based, SLURM/SGE-aware job distribution system (`pyrosetta.distributed.cluster`).

## Identity
- **Version / release examined:** `pyrosetta.distributed.cluster.__init__.__version__ = "5.0.4"` (`source/src/python/PyRosetta/src/pyrosetta/distributed/cluster/__init__.py:56`). Build driven by `source/src/python/PyRosetta/build.py` and `source/src/python/PyRosetta/src/setup.py`.
- **Provenance:** RosettaCommons; `pyrosetta.distributed.cluster` module authored by Jason C. Klima (module docstring `__author__`). Refcode path: `tools/rosetta/source/src/python/PyRosetta/`.
- **Maturity:** production for the core PyRosetta bindings (used throughout structural biology); the `distributed.cluster` submodule is actively developed (module list of 20+ files, extensive docstrings, security/serialization hardening) but is a narrower, more specialized piece.

## Scientific role
PyRosetta is not a distinct scientific method — it is Rosetta's protocol library (FastRelax, FastDesign, InterfaceAnalyzerMover, scoring, packing, minimization; see `rosetta.md`) exposed as importable Python objects instead of only an XML-driven CLI binary. It serves the same four problem classes as Rosetta, but changes the **invocation surface**: individual movers/filters can be composed, introspected, and chained programmatically inside a single Python process, which matters for an agent that wants fine-grained control (e.g., run FastRelax, inspect per-residue scores, conditionally add a constraint, run again) rather than writing and re-launching a new XML file per decision.

Pipeline stages occupied: same as Rosetta (generate/relax/design/score/analyze), plus **orchestrate** — `pyrosetta.distributed.cluster.PyRosettaCluster` is itself a job-distribution layer, not merely a binding.

## Invocation & I/O contract
- **How a unit of work is invoked:** Python API.
  - Single-process: `import pyrosetta; pyrosetta.init(); pose = pyrosetta.pose_from_pdb("in.pdb"); mover = pyrosetta.rosetta.protocols.relax.FastRelax(scorefxn); mover.apply(pose)`.
  - Scripted-protocol wrapper: `pyrosetta.distributed.tasks.rosetta_scripts.BaseRosettaScriptsTask(protocol_xml)` — parses and validates a RosettaScripts XML string via `rosetta_scripts.RosettaScriptsParser()` and applies it to a pose in-process (`source/src/python/PyRosetta/src/pyrosetta/distributed/tasks/rosetta_scripts.py:24-56`), i.e. the same XML protocols used by the CLI binary can be driven from Python without shelling out.
  - Distributed job system: `pyrosetta.distributed.cluster.PyRosettaCluster(tasks=..., nstruct=..., scheduler=...).distribute(protocols=[my_protocol_fn])`.
- **Inputs:** `Pose`/`PackedPose` objects (in-memory), PDB files, or task dictionaries (JSON-serializable kwargs) for `PyRosettaCluster`.
- **Outputs:** `Pose`/`PackedPose` objects; `PyRosettaCluster` additionally writes pickled decoy files plus a `scores.json`/logging tree to `output_path` (per constructor docstring in `core.py`).
- **A concrete example** (from the module's own docstring conventions, `core.py`):
  ```python
  from pyrosetta.distributed.cluster import PyRosettaCluster

  def my_protocol(packed_pose, **kwargs):
      import pyrosetta
      pose = packed_pose.pose
      # ... apply movers ...
      return pose

  PyRosettaCluster(
      tasks=[{}],
      nstruct=100,
      scheduler="slurm",
      cores=1,
      processes=1,
      memory="4g",
      min_workers=1,
  ).distribute(protocols=[my_protocol])
  ```

## Compute pattern
- **Pattern:** **P2** (CPU-parallel fan-out, in-job) for direct API use inside an agent's own allocation — identical cost profile to the Rosetta CLI, since it's the same underlying C++ engine. **P4** (external HPC job) when `PyRosettaCluster(scheduler="slurm")` is used, because it submits *separate* `SLURMCluster` (via `dask-jobqueue`) worker jobs outside whatever allocation launched the Python process — confirmed by `core.py` docstring: `"scheduler": "sge"|"slurm"|None → SGECluster|SLURMCluster (dask_jobqueue) | distributed.LocalCluster"` (`core.py:78-83`).
- **GPU vendor portability:** **CPU-only** by default. Optional `--torch`/`--tensorflow` build flags exist (`source/src/python/PyRosetta/src/setup.py:910-911`) but even those compile with `USE_TENSORFLOW_CPU` (`setup.py:92`) — there is no CUDA/HIP/SYCL code path in the PyRosetta build regardless of flags.
- **State model:** stateless per protocol call at the Pose level (a `Pose` is just an in-memory object); `PyRosettaCluster` is checkpointable at the task/decoy level by design — it persists a state file and its own docs describe `"reproduce"`/`"iterate"` toolkit functions (`toolkit.py`, exported names `produce`, `reproduce`, `iterate` in `__init__.py:26-27`) intended for resuming/replaying campaigns.
- **Data locality:** shared-FS required for the SLURM/SGE `scheduler` modes (workers write to `scratch_dir`, default `/temp` or cwd, per `core.py` docstring); self-contained for `LocalCluster`/direct API use.
- **Staging burden:** none beyond the same Rosetta `database/` directory Rosetta itself needs (`pyrosetta.init()` locates it via the installed package or `PYROSETTA_DATABASE`/`ROSETTA3_DB`).
- **Container availability:** official — same `rosettacommons/rosetta` Docker Hub images bundle PyRosetta (per `tools/rosetta/README.md`); PyRosetta is also distributed as a **conda package** (`pyrosetta` channel, documented upstream, not independently verified in this refcode) which is generally the lower-friction install path vs. building Rosetta itself from source.

## Deployment on DOE & ACCESS
Same CPU-only reasoning as `rosetta.md` applies — no platform blocks Rosetta on GPU-vendor grounds because none of the hot paths use a GPU. The practical difference from bare Rosetta is packaging: PyRosetta ships prebuilt wheels/conda packages for common glibc/Python-version combinations, which may be usable directly on ACCESS (Delta/Bridges-2/Expanse, standard x86_64 Linux) without a from-source build, whereas Frontier (non-standard CPU/interconnect stack) and Aurora likely still require a from-source PyRosetta build (`build.py -j<N>`) to match the compute-node environment and avoid glibc/AVX mismatches. The `pyrosetta.distributed.cluster` SLURM/SGE integration is directly usable on ACCESS/Frontier (SLURM) without modification; Polaris and Aurora use PBS Pro, which `dask_jobqueue` also supports (`PBSCluster`) but which `PyRosettaCluster`'s `scheduler` argument does **not** currently expose (only `"sge"`/`"slurm"`/`None` per the docstring) — this is a real gap for PBS Pro machines that would need a workaround (e.g., pass a pre-built `dask_jobqueue.PBSCluster` client explicitly via the `clients` argument instead of the `scheduler=` convenience path).

## Agentic surface
- **Native MCP:** no (see `rosetta.md` for the same community-only MCP caveat, which covers PyRosetta interactively too).
- **Parameters worth exposing for autonomous variation:** same protocol-level parameters as `rosetta.md` (nstruct, scorefxn, relaxscript, cartesian/dualspace), plus cluster-layer knobs:

| parameter | type | sane range | default | trade-off |
|---|---|---|---|---|
| `nstruct` (`PyRosettaCluster`) | int | 1–1000s | 1 | ensemble size vs. linear compute cost, same as CLI `-nstruct` |
| `scheduler` | enum | `None`(local), `"slurm"`, `"sge"` | `None` | `None` keeps work inside the agent's own allocation (P2); `"slurm"`/`"sge"` spawns external jobs (P4) with queue-wait risk |
| `cores` / `processes` / `memory` (dask-jobqueue) | int/int/str | 1–N per node shape | `1`/`1`/`"4g"` | must match the target queue's per-job resource limits or `sbatch` submission fails |
| `min_workers` | int | 1–N | 1 | how many Dask workers to hold as a floor while adaptively scaling; too low starves the pipeline, too high wastes allocation |
| `decoy_ids` | list[int] | — | `None` | selects a specific decoy from a multi-decoy upstream protocol for reproducibility — never randomize this if the goal is deterministic replay |

- **Parameters that must NOT be agent-varied:** `seeds` should be treated as fixed/logged, not agent-chosen per run, when reproducibility of a specific accepted design is required (the class explicitly supports `seeds` for this reason); the pickle-based deserialization path (`client`/`clients`/task inputs) must never be pointed at untrusted input — the class's own docstring warns "this class uses the `pickle` module to deserialize pickled `Pose` objects ... please only run with input files you trust," which is a correctness/security constraint the agent must not relax by accepting arbitrary external pickles into a campaign.

## Failure modes & what the agent must check
Identical structural-quality checks to `rosetta.md` apply to every Pose produced through PyRosetta (total-score outliers, `cart_bonded`, `rama_prepro`, buried unsatisfied polars, residual clash) — PyRosetta does not change what silent failure looks like, only how the agent observes it (it can inspect `pose.energies()` and per-residue score tables directly in-process, which is strictly more visibility than parsing a CLI scorefile). Additional PyRosetta/cluster-specific hazards:
- **Silent partial-ensemble completion** — if a `PyRosettaCluster(scheduler="slurm")` run loses workers to preemption or walltime, the `min_workers`/adaptive-scaling model can quietly deliver fewer decoys than `nstruct` requested without raising; the agent must count actual output decoys against the requested `nstruct`, not assume completion from a non-error return.
- **Dask scheduler/worker mismatch errors** are loud (`distributed.scheduler.KilledWorker`, imported explicitly in `core.py:506`) but the class's own docstring notes worker output can race the scheduler ("If a Dask worker returns the result(s) ... too quickly, the Dask scheduler needs to..."), a known source of nondeterministic task loss that the class tries to mitigate but does not eliminate — the agent should treat missing decoys as expected-rare rather than alarming, and retry rather than fail the campaign.

## Cost per unit of work
Per-decoy compute cost is identical to the equivalent Rosetta CLI protocol (see `rosetta.md`'s Cost section) — PyRosetta adds no meaningful per-call overhead over the C++ engine itself; the Python/pybind11 boundary cost is negligible relative to FastRelax/FastDesign runtimes measured in CPU-minutes. The added cost specific to PyRosetta is **cluster orchestration overhead**: `PyRosettaCluster` job submission via `dask_jobqueue.SLURMCluster` introduces per-job `sbatch` queue wait (P4 cost, highly variable by queue) on top of the same per-decoy compute; for local (`scheduler=None`) use this overhead is a few seconds of Dask scheduler/worker startup, effectively free relative to decoy cost.

## Verdict
**Core.** PyRosetta is not optional if the agent needs to compose or inspect Rosetta protocols programmatically rather than only launching pre-written XML files — and Phase 1's autonomy requirement (adaptive parameter choice, mid-protocol inspection) makes that composability load-bearing, not a nice-to-have. The `pyrosetta.distributed.cluster` Dask/SLURM system should be treated as **complementary but not adopted as our execution layer**: it competes directly with rhapsody/asyncflow for the P4 external-job-submission role, duplicates functionality (its own retry/checkpoint/reproduce semantics, its own state files), and only speaks SLURM/SGE natively (a real gap for Polaris/Aurora PBS Pro). The right integration is to use PyRosetta as a **P2 in-process library** driven directly by our own execution layer for the common case, and treat `PyRosettaCluster`'s SLURM path as a fallback/reference implementation rather than a dependency — building our own P4 submission around `PyRosettaCluster`'s scheduler abstraction would mean inheriting a second, Dask-native job-tracking model alongside our own.

## Sources
- `tools/rosetta/source/src/python/PyRosetta/src/pyrosetta/distributed/cluster/__init__.py` (version, exported API)
- `tools/rosetta/source/src/python/PyRosetta/src/pyrosetta/distributed/cluster/core.py` (constructor docstring: `tasks`, `nstruct`, `scheduler`, `cores`, `processes`, `memory`, `scratch_dir`, `min_workers`, lines ~1-350; `class PyRosettaCluster` at line 605; `KilledWorker` import at line 506; `distribute` method at line 1523)
- `tools/rosetta/source/src/python/PyRosetta/src/pyrosetta/distributed/tasks/rosetta_scripts.py` (`BaseRosettaScriptsTask`, lines 1-56)
- `tools/rosetta/source/src/python/PyRosetta/src/setup.py` (`--torch`/`--tensorflow` build flags and `USE_TENSORFLOW_CPU`, lines 91-92, 910-911)
- `tools/rosetta/README.md` (Docker/conda distribution)
- Upstream PyRosetta/dask-jobqueue scheduler support (`SGECluster`, `SLURMCluster`, `PBSCluster`) is general `dask_jobqueue` knowledge, inferred from the `core.py` docstring's explicit `"sge"`/`"slurm"` enumeration — not independently verified against a PBS code path in this refcode.
