# GROMACS

**One-line identity.** A production-grade, GPU-accelerated molecular dynamics engine with the best
cross-vendor GPU portability of any simulation tool in this toolkit, driven through an mdp/tpr file
contract or a thin Python wrapper (gmxapi) over that same contract.

## Identity
- **Version / release examined:** `project(Gromacs VERSION 2027.0)` —
  `<workspace>/impress-a-refcodes/tools/gromacs/CMakeLists.txt:67`
- **Provenance:** GROMACS development team (KTH Royal Institute of Technology / Uppsala University and
  collaborators). LGPL ≥ 4.6, GPL for earlier history (per upstream project metadata). Refcode:
  `<workspace>/impress-a-refcodes/tools/gromacs/`
- **Maturity:** production. One of the two or three most widely deployed biomolecular MD engines on
  DOE and NSF machines; decades of continuous development, active GitLab CI
  (`.gitlab-ci.yml`), physical-validation test suite (`GMX_PHYSICAL_VALIDATION` option).

## Scientific role
GROMACS runs classical molecular dynamics on solvated biomolecular systems. In this toolkit it serves
**stability/thermostabilization** (RMSD/RMSF drift of a designed fold under explicit-solvent MD) and,
more expensively, **small-molecule binding** (free-energy perturbation / alchemical transformations —
the refcode ships a full `freeenergy/` test-case tree under
`src/testutils/simulationdatabase/freeenergy/`, e.g.
`src/testutils/simulationdatabase/freeenergy/coulandvdwtogether/grompp.mdp`). It occupies the
**simulate** pipeline stage, consuming a prepared, solvated, parameterized structure and producing a
trajectory plus scalar outputs (energies) that downstream tools (MDAnalysis/MDTraj) turn into metrics.

It is not a generative or scoring tool on its own — GROMACS output is a trajectory; turning that
trajectory into a stability or binding *number* is a separate step (see `mdanalysis-mdtraj.md`).

## Invocation & I/O contract
- **How a unit of work is invoked:** two-stage CLI, `gmx grompp` then `gmx mdrun`, or the same two
  stages through the `gmxapi` Python package
  (`python_packaging/gmxapi/src/gmxapi/simulation/{fileio,modify_input,mdrun}.py`).
  - CLI: `gmx grompp -f run.mdp -c conf.gro -p topol.top -o topol.tpr` then
    `gmx mdrun -deffnm topol -nsteps 100 -maxh 2.5` (flags documented in
    `docs/user-guide/mdrun-features.rst:165-166`).
  - Python: `tpr = gmxapi.read_tpr(tpr_filename)`; `md = gmxapi.mdrun(tpr, runtime_args={...})`; and,
    for checkpoint-extended runs, `gmxapi.modify_input(tpr, parameters={"nsteps": N})` before
    `gmxapi.mdrun(...)` — the exact pattern exercised in
    `python_packaging/gmxapi/test/test_mdrun.py:222-248`
    (`test_extend_simulation_via_checkpoint`).
- **Inputs:** `.gro`/`.pdb` (structure), `.top` (topology, referencing force-field files under
  `share/top/`, e.g. `amber99sb.ff`, `amber19sb.ff`, `charmm27.ff`), `.mdp` (run parameters), `.ndx`
  (optional atom-group index).
- **Outputs:** `.tpr` (portable run input, produced by grompp), `.trr`/`.xtc`/`.tng` (trajectory),
  `.edr` (energies), `.log`, `.cpt` (checkpoint). gmxapi's `mdrun` operation additionally exposes typed
  output descriptors `directory`, `checkpoint`, `parameters`, `stderr`, `stdout`, `trajectory`
  (`python_packaging/gmxapi/src/gmxapi/simulation/mdrun.py:70-77`).
- **A concrete example:** `docs/user-guide/getting-started.rst:135-155` walks the exact
  gro+top+mdp → grompp → tpr → mdrun → trr/log/cpt chain described above. gmxapi's own ensemble
  pattern: `simulation_input = gmxapi.read_tpr([tpr_filename] * ensemble_width); md =
  gmxapi.mdrun(simulation_input, runtime_args=mdrun_kwargs)`
  (`python_packaging/gmxapi/test/test_mdrun.py:276-282`) — this is the mechanism for running an
  ensemble of replicas from one Python call.

## Compute pattern
- **Pattern:** P3 (primary) / P4 (when production length exceeds remaining walltime — submit as a
  separate batch job and poll for `.cpt`/`.log` completion)
- **GPU vendor portability:** **portable** — `GMX_GPU` is a CMake multichoice option with values
  `OFF CUDA OpenCL SYCL HIP` (`CMakeLists.txt:242-247`). The SYCL path further selects a backend via
  `GMX_SYCL` = `AUTO | ACPP | DPCPP`, where `DPCPP` is Intel oneAPI DPC++ (Aurora) and `ACPP` is
  AdaptiveCpp (`CMakeLists.txt:248-271`). This is the strongest, most direct evidence of cross-vendor
  GPU support in the entire toolkit: GROMACS builds natively for Polaris/ACCESS (CUDA), Frontier (HIP),
  and Aurora (SYCL/DPC++) from the same source tree with no vendor fork required.
- **State model:** checkpointable. `.cpt` files are written periodically and on clean signal-driven
  shutdown (`docs/user-guide/mdrun-features.rst:49-60`: on TERM/INT, mdrun finishes the current step and
  writes a checkpoint; a third signal or ABRT aborts without one). `mdrun -maxh 2.5` self-terminates
  cleanly before a walltime limit, which is the mechanism an agent should use to guarantee a
  checkpoint is written before SLURM/PBS kills the job.
- **Data locality:** shared-FS required (tpr/cpt/trajectory files read and written by rank 0 and
  polled by the agent).
- **Staging burden:** none beyond the container/build itself — force fields (`share/top/*.ff`) ship in
  the source tree; no large weight downloads.
- **Container availability:** community/build-required for the specific GPU backend needed. Official
  Docker build tooling exists in-tree (`python_packaging/docker/`), but a leadership-class deployment
  (HIP for Frontier, SYCL/DPCPP for Aurora) will generally require a site-specific Apptainer build
  against the vendor toolchain rather than a portable pre-built image.

## Deployment on DOE & ACCESS
- **Frontier (AMD MI250X/HIP):** build with `-DGMX_GPU=HIP`. GROMACS has invested specifically in HIP
  and SYCL-on-AMD performance (see Sources); this is one of the few tools in the whole toolkit that
  runs natively and well on Frontier without a compatibility shim.
- **Aurora (Intel PVC/SYCL-XPU):** build with `-DGMX_GPU=SYCL -DGMX_SYCL=DPCPP` against Intel oneAPI.
  Real, first-class support — not a community patch.
- **Polaris / ACCESS (NVIDIA CUDA):** build with `-DGMX_GPU=CUDA`; this is GROMACS's original and most
  mature backend, with `GMX_GPU_FFT_LIBRARY` defaulting to cuFFT (`CMakeLists.txt:325`).
- Multi-node runs need `-DGMX_MPI=ON` against the site MPI (thread-MPI, the default, is single-node
  only — `GMX_THREAD_MPI` option, `CMakeLists.txt:221`, is explicitly "not compatible with MPI").
  Module vs. Apptainer: leadership sites generally expect a module-based or site-built GROMACS tuned to
  the local network fabric and GPU-aware MPI (`cmake/gmxManageGpuAwareMpi.cmake`); a generic container
  loses some of that tuning. No license gate — LGPL/GPL, freely redistributable.

## Agentic surface
- **Native MCP:** no. No MCP server ships in or is referenced by the refcode or upstream GROMACS docs.
  (Community MCP wrappers around arbitrary CLI tools are possible but unverified — not claimed here.)
- **Parameters worth exposing for autonomous variation:**

  | parameter | type | sane range | default | trade-off |
  |---|---|---|---|---|
  | `nsteps` / simulation length | int (via `.mdp` or gmxapi `modify_input`) | 10³–10⁷ | mdp-defined | wall-clock cost vs. sampling/drift signal |
  | `dt` (mdp) | float, ps | 0.001–0.004 | 0.002 | larger step is cheaper but needs H-bond constraints (`constraints = h-bonds`) to stay stable |
  | `-maxh` (mdrun CLI) | float, hours | ≤ remaining walltime | none | guarantees a clean checkpoint before preemption |
  | `nstxout`/`nstenergy` (mdp) | int, steps | 500–5000 | mdp-defined | trajectory/energy output density vs. disk I/O and file size |
  | ensemble width (`read_tpr([tpr]*N)`) | int | 1–~50 | 1 | more independent replicas per candidate vs. proportional GPU-time cost |

- **Parameters that must NOT be agent-varied:** force-field choice and `.top` topology once grompp has
  bound them to a `.tpr` (changing physics mid-ensemble silently invalidates comparisons across
  replicas); `constraints`/`coulombtype`/PME grid settings (correctness — wrong settings can converge
  to a stable-looking but unphysical trajectory with no loud error); `GMX_GPU` build-time backend
  (a runtime concern, not a per-job one, but never something the agent should try to toggle per run).

## Failure modes & what the agent must check
- **Loud failure:** `grompp` exits non-zero on missing/inconsistent topology-structure atom counts,
  bad `.mdp` keys, or unstable-by-construction settings (e.g., a timestep grompp flags as violating the
  LINCS warning threshold). `mdrun` exits non-zero on a genuine numerical blow-up it detects internally
  (LINCS/SETTLE constraint failure, domain-decomposition failure).
- **Silent bad output:** a system that integrates without crashing but has (a) an unequilibrated hot
  spot from a bad energy minimization, (b) box/PBC artifacts if the box is too small relative to the
  cutoff, or (c) a "flatlined" trajectory (frozen atoms) from an over-constrained or mis-set
  temperature-coupling group. **Check:** re-derive temperature and pressure time series from the
  `.edr` file (`gmx energy`) and confirm they equilibrate to the target ensemble values within
  expected fluctuation bounds before trusting any RMSD/RMSF computed downstream; check that the
  potential energy is not still trending monotonically at the end of the run (unconverged/unequilibrated
  system, not blown up, just not representative).
- **Preemption/kill without checkpoint:** if the scheduler kills the job before mdrun's own `-maxh`
  self-termination fires, no final checkpoint is guaranteed — the agent must set `-maxh` strictly below
  the SLURM/PBS walltime, not equal to it.

## Cost per unit of work
Concrete data point: an ~80,000-atom protein-in-membrane-in-explicit-water benchmark system achieves
**241 ns/day on a single NVIDIA A100** (NHR@FAU GPU benchmark, GROMACS ~2022-era; see Sources). A
comparably sized ~50,000-atom soluble-protein-in-water system (smaller, no membrane) would be expected
to run somewhat faster than that on the same GPU, so 241 ns/day is a conservative floor for the "typical
design candidate in a water box" case this toolkit cares about.

- **Unit of work:** one candidate's stability trajectory, ~10–50 ns.
- **Wall-clock:** at ~200–300 ns/day on one GPU, a 20 ns trajectory costs roughly **1.5–2.5 hours**
  on a single A100/MI250X-class GPU (P3, single node, 1 GPU minimum — GROMACS scales to multi-GPU/multi-node
  but a single design-candidate trajectory does not need it).
- **Resource shape:** 1 node, 1 GPU is the realistic per-candidate unit; multi-node MPI is reserved for
  either much larger systems or much longer aggregate campaigns, which pushes into P4 territory.
- **Checkpointable:** yes (`.cpt`), see State model above.
- **Implication for the agent's budget:** running even a short 10–20 ns equilibration/stability check
  on *every* design candidate is expensive relative to the P1 generate/inverse-fold/predict stages
  (seconds to low minutes each). GROMACS-class MD is realistically a **final-stage triage** step run on
  a short list (tens, not hundreds, of survivors) rather than a per-candidate filter applied to every
  sequence a generative model proposes.

## Verdict
**Recommended.** GROMACS is the highest-performance, best-GPU-portability MD engine available to this
project and is the correct choice whenever a design candidate needs a real, physically rigorous
explicit-solvent trajectory — especially on Frontier and Aurora, where its native HIP and SYCL/DPCPP
support (verified directly in `CMakeLists.txt`) is unmatched by the more CUDA-centric alternatives in
this toolkit. It is not classified **Core** because its two-stage, file-mediated grompp/mdrun contract
is a poorer fit for tight agent-driven parameter sweeps than OpenMM's native Python API, and because
its cost profile (hours per GPU per candidate) means it cannot run in the agent's per-candidate inner
loop — it belongs at the final-triage stage of a campaign, invoked on a short list, not on every
candidate.

## Sources
- `<workspace>/impress-a-refcodes/tools/gromacs/CMakeLists.txt` (version, GMX_GPU/GMX_MPI/GMX_SYCL options)
- `<workspace>/impress-a-refcodes/tools/gromacs/docs/user-guide/getting-started.rst`
- `<workspace>/impress-a-refcodes/tools/gromacs/docs/user-guide/mdrun-features.rst`
- `<workspace>/impress-a-refcodes/tools/gromacs/docs/user-guide/system-preparation.rst`
- `<workspace>/impress-a-refcodes/tools/gromacs/python_packaging/gmxapi/src/gmxapi/simulation/{mdrun,fileio,modify_input}.py`
- `<workspace>/impress-a-refcodes/tools/gromacs/python_packaging/gmxapi/test/test_mdrun.py`
- `<workspace>/impress-a-refcodes/tools/gromacs/src/testutils/simulationdatabase/freeenergy/`
- `<workspace>/impress-a-refcodes/tools/gromacs/share/top/` (bundled force fields)
- GROMACS performance on different GPU types — NHR@FAU: https://hpc.fau.de/2022/02/10/gromacs-performance-on-different-gpu-types/ (241.2 ns/day, 80,289-atom system, A100) — external, not verified against this refcode's exact version but representative of modern GROMACS GPU throughput.
- "GROMACS on AMD GPU-Based HPC Platforms: Using SYCL for Performance and Portability" (arXiv:2405.01420) — external, cited for AMD/SYCL performance context, inferred relevance not independently re-verified line-by-line.
