# LAMMPS

**One-line identity.** A general-purpose classical MD engine built around pluggable "styles" for
materials, soft matter, and coarse-grained physics, with genuinely broad multi-vendor GPU support but
no biomolecular-force-field center of gravity.

## Identity
- **Version / release examined:** `#define LAMMPS_VERSION "2 Sep 2026"` —
  `<workspace>/impress-a-refcodes/tools/lammps/src/version.h:1`
- **Provenance:** Sandia National Laboratories (originally), now a broad multi-institution open-source
  project. Refcode: `<workspace>/impress-a-refcodes/tools/lammps/`
- **Maturity:** production. Very actively developed (packages tree alone spans dozens of physics
  domains — `src/*` package directories), strong DOE-lab pedigree, first-class GPU/Kokkos investment.

## Scientific role
LAMMPS is a materials-science and soft-matter MD engine first, a biomolecular MD engine a distant
second. Its bundled biomolecular example — `examples/peptide/in.peptide`
(`<workspace>/impress-a-refcodes/tools/lammps/examples/peptide/in.peptide`), a "solvated
5-mer peptide" using `pair_style lj/charmm/coul/long`, `bond_style harmonic`, `angle_style charmm`,
`dihedral_style charmm` — is a 30-year-old canonical CHARMM benchmark, not an actively maintained
biomolecular-design workflow. LAMMPS *can* run a CHARMM- or AMBER-style protein force field, but the
project's own packaging, defaults, and documentation center on metals, polymers, granular and
colloidal systems, and machine-learned interatomic potentials for materials — not protein
stability/binding assessment.

**Honest read for this toolkit:** LAMMPS does not earn a place in the core protein-design toolkit.
GROMACS and OpenMM already cover everything this project's four in-scope problem classes
(stability, de novo binder design, enzyme/catalytic design, small-molecule binding) need from
biomolecular MD, with mature CHARMM/AMBER force-field support, native PME electrostatics tuned for
proteins in water, and much larger biomolecular-simulation communities validating their defaults.
Adding LAMMPS alongside them would mean maintaining a third MD input format and a third set of
force-field conventions for no scientific capability GROMACS/OpenMM lack.

**What would change this verdict:**
- **Coarse-grained protein/peptide models** (Martini-style CG force fields, structure-based/Go models)
  for cheap large-conformational-sampling screens before committing to atomistic GROMACS/OpenMM runs —
  LAMMPS has strong native CG support that neither GROMACS nor OpenMM prioritizes as heavily.
- **Polymer or peptide-materials work** outside pure biomolecular MD (e.g., designed peptide
  self-assembly into fibrils/hydrogels, protein-polymer conjugates) — genuinely LAMMPS's home turf.
- **ML interatomic potentials via the `ML-IAP` package**
  (`<workspace>/impress-a-refcodes/tools/lammps/src/ML-IAP/`, e.g. `pair_mliap.cpp`,
  `mliap_model_python.cpp` for coupling a Python-defined NN/ACE/SNAP potential) — if this project ever
  needs to run MD with a learned potential rather than a classical force field, `ML-IAP`'s
  `mliap_model_python_couple.pyx` Python-coupling path is a real, non-trivial capability GROMACS does
  not offer.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, `lmp -in in.peptide -log log.peptide` (binary name `lmp`,
  built via CMake — `cmake/CMakeLists.txt`); or the `lammps` Python module
  (`<workspace>/impress-a-refcodes/tools/lammps/python/lammps/`) which wraps the C library
  interface for in-process control of an already-open LAMMPS instance.
- **Inputs:** an input script (`in.*`, LAMMPS's own command language) plus a data file (`data.*`,
  LAMMPS's own atom/bond/angle/topology format) — e.g. `examples/peptide/data.peptide`. Neither format
  is `.gro`/`.top`/`.mdp`-compatible; a protein system prepared for GROMACS/OpenMM (PDB + force-field
  XML/top) cannot be fed to LAMMPS without a separate conversion step (e.g. via a `moltemplate`/CHARMM
  psf-to-LAMMPS-data toolchain not present in this refcode).
- **Outputs:** `log.*` (thermodynamic time series), `dump.*` (trajectory, LAMMPS-native `atom`/`custom`
  dump styles), binary restart files.
- **A concrete example:** `examples/peptide/in.peptide` (see Scientific role above) — `run 300` for a
  short demonstration; `bench/in.rhodo` / `bench/data.rhodo` is LAMMPS's other bundled biomolecular
  case (rhodopsin in a lipid bilayer), also decades-old and used purely as a scaling benchmark, not a
  design workflow.

## Compute pattern
- **Pattern:** P3 (primary) / P4 (when production length exceeds remaining walltime)
- **GPU vendor portability:** **CUDA+HIP+SYCL, portable** — with evidence, but split across two
  packages with different reach:
  - `GPU` package: `set(GPU_API "opencl" CACHE STRING ...)` with
    `GPU_API_VALUES opencl cuda hip` (`cmake/Modules/Packages/GPU.cmake:22-24`) — single-GPU-per-rank
    acceleration of a limited set of pair styles.
  - `KOKKOS` package: backend selected via `Kokkos_ENABLE_CUDA` / `Kokkos_ENABLE_HIP` /
    `Kokkos_ENABLE_SYCL` (`cmake/Modules/Packages/KOKKOS.cmake:80-260`) — the broader-coverage,
    better-maintained GPU path, and the one that would actually run on Aurora.
  Net: LAMMPS can in principle be built for Frontier (HIP), Aurora (SYCL via Kokkos), and
  Polaris/ACCESS (CUDA) from the same source tree — comparable portability ambition to GROMACS, though
  with more style-by-style variability in what is actually GPU-accelerated.
- **State model:** checkpointable via LAMMPS `restart` command/binary restart files
  (`doc/src/restart.rst:1-60`: `restart N root keyword value ...` writes a binary restart on a
  configurable cadence; supports toggling between two rolling filenames to survive a crash between
  writes).
- **Data locality:** shared-FS required.
- **Staging burden:** none for classical force fields; `ML-IAP` adds a Python-model-weights staging
  burden if used.
- **Container availability:** community/build-required — no official biomolecular-tuned container is
  implied by this refcode; a leadership deployment would be a from-source Kokkos/GPU build.

## Deployment on DOE & ACCESS
- **Frontier (HIP):** `GPU` package via `GPU_API=hip`, or `KOKKOS` with `Kokkos_ENABLE_HIP=ON` (plus
  `Kokkos_ENABLE_HIP_MULTIPLE_KERNEL_INSTANTIATIONS`/`Kokkos_ENABLE_ROCTHRUST` tuning,
  `cmake/Modules/Packages/KOKKOS.cmake:80-83`).
- **Aurora (SYCL/XPU):** `KOKKOS` with `Kokkos_ENABLE_SYCL=ON`. This is the only realistic GPU path to
  Aurora for LAMMPS in this refcode; the `GPU` package's `GPU_API` list does not include SYCL/OpenCL
  for Intel specifically beyond generic OpenCL.
- **Polaris / ACCESS (CUDA):** `GPU_API=cuda` or `Kokkos_ENABLE_CUDA=ON` — LAMMPS's most mature,
  best-tested GPU path.
- Module vs. conda vs. Apptainer: a from-source CMake build against site Kokkos/MPI is the realistic
  path on any of these machines; no license gate (GPL-2.0, per `LICENSE`).

## Agentic surface
- **Native MCP:** community / unverified. A third-party "MCP LAMMPS Server" exists publicly (glama.ai
  listing, "Chenghao-Wu/MCP_LAMMPS") but is an independent community project, not upstream LAMMPS, and
  was not verified against this refcode or for production readiness. Treat as **no** for planning
  purposes.
- **Parameters worth exposing for autonomous variation:** n/a for this toolkit's in-scope problem
  classes — see Verdict. If the CG/polymer/MLIAP use case above is ever activated, the relevant knobs
  would be `run` step count, `timestep`, and (for `ML-IAP`) the swapped-in Python model, but these are
  not developed here because the tool is not currently in scope.
- **Parameters that must NOT be agent-varied:** n/a, same reason.

## Failure modes & what the agent must check
Not developed in depth given the Defer verdict. In general terms: LAMMPS input-script errors are
mostly loud (unknown command / style, non-zero exit); silent bad output follows the same MD-general
pattern as GROMACS (unequilibrated or drifting thermodynamic time series in `log.*` that never
triggers a hard error) — the `log.*` thermo output would need the same post-hoc sanity check GROMACS's
`.edr` does, if this tool were ever activated.

## Cost per unit of work
Not separately benchmarked here — LAMMPS's cost profile for a biomolecular system would be broadly
comparable to GROMACS's (same physics, same GPU classes), but LAMMPS's biomolecular pair styles are
less optimized than GROMACS's PME/nonbonded kernels, so it should not be expected to beat GROMACS on
the same hardware for the same protein-in-water system. This is not a load-bearing number for the
Defer verdict, which rests on scientific fit, not cost.

## Verdict
**Defer.** LAMMPS does not earn a place in a protein-design toolkit today: GROMACS and OpenMM already
cover biomolecular stability, binding, and relaxation MD with better-maintained CHARMM/AMBER force
fields, larger validation communities, and (for GROMACS specifically) comparable multi-vendor GPU
portability. LAMMPS's own bundled biomolecular examples (`examples/peptide`, `bench/rhodo`) are
decades-old scaling benchmarks, not evidence of an active biomolecular-design use case. This changes if
the project later needs (a) coarse-grained/Martini-style protein models for cheap large-scale
conformational screening, (b) peptide/protein-polymer materials work outside classical biomolecular MD,
or (c) MD driven by a learned interatomic potential via the `ML-IAP` package
(`src/ML-IAP/mliap_model_python.cpp`) rather than a classical force field — any of which would justify
revisiting this brief.

## Sources
- `<workspace>/impress-a-refcodes/tools/lammps/src/version.h`
- `<workspace>/impress-a-refcodes/tools/lammps/examples/peptide/in.peptide`
- `<workspace>/impress-a-refcodes/tools/lammps/examples/peptide/data.peptide`
- `<workspace>/impress-a-refcodes/tools/lammps/bench/in.rhodo`
- `<workspace>/impress-a-refcodes/tools/lammps/cmake/Modules/Packages/GPU.cmake`
- `<workspace>/impress-a-refcodes/tools/lammps/cmake/Modules/Packages/KOKKOS.cmake`
- `<workspace>/impress-a-refcodes/tools/lammps/doc/src/restart.rst`
- `<workspace>/impress-a-refcodes/tools/lammps/src/ML-IAP/` (`pair_mliap.cpp`, `mliap_model_python.cpp`, `mliap_model_python_couple.pyx`)
- `<workspace>/impress-a-refcodes/tools/lammps/python/lammps/`
- MCP LAMMPS Server (Chenghao-Wu) — glama.ai listing: community-reported, not independently verified; treated as unverified.
