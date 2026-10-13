# OpenMM

**One-line identity.** A GPU-accelerated molecular dynamics library exposed as a first-class Python
API rather than a file-and-CLI contract — the MD engine built to be *programmed*, not just invoked.

## Identity
- **Version / release examined:** not in refcodes; researched upstream. Latest stable as of this
  writing: **8.6.1** (released 2026-09-11); 8.6.0 released 2026-08-19, 8.5.x series through
  2026-03/06. (github.com/openmm/openmm releases — inferred from search, not independently verified
  against a local checkout.)
- **Provenance:** originated at Stanford (Pande/Simbios group), now maintained by a broad open-source
  community backed in part by the Chodera Lab, MSKCC, and others; core repo `openmm/openmm` on GitHub.
  License: MIT for most of the codebase, LGPL for some CUDA/OpenCL-derived portions.
- **Maturity:** production. Used as the physics engine inside AlphaFold's own relaxation step, inside
  Folding@Home, and inside most modern ML-potential MD frameworks (TorchMD, OpenMM-ML) — this is a
  load-bearing dependency of the field, not a niche tool. Not present in
  `impress-a-refcodes/tools/`; would need to be added to the refcode set if adopted.

## Scientific role
OpenMM plays two distinct roles in this toolkit, and they have very different cost/value profiles:

1. **Relaxation/minimization of designed structures** (generate → **simulate**, immediately after a
   generative or inverse-folding step). Designed backbones and side chains from RFdiffusion/ProteinMPNN
   or AlphaFold-class predictors routinely contain small steric clashes and non-equilibrium bond/angle
   geometry that a downstream scorer (Rosetta energy, a binding-affinity predictor) can be misled by.
   A short energy minimization — and often a brief NVT/implicit-solvent relax — removes this noise
   cheaply. This is exactly what AlphaFold's own `alphafold/relax/amber_minimize.py` does: load the
   predicted structure, build an `amber99sb.xml`-parameterized `System`, run
   `LocalEnergyMinimizer`/short MD with position restraints, and re-extract coordinates. This
   relaxation step is cheap (seconds to low minutes) and is the single most defensible, "run-on-every-
   candidate" use of MD in an autonomous design loop.
2. **Stability assessment / conformational sampling** (short explicit-solvent MD, RMSD/RMSF read-out).
   Scientifically identical to what GROMACS does (see `gromacs.md`), and subject to the same cost
   ceiling: a real explicit-solvent trajectory is minutes-to-hours of GPU time per candidate, so it is
   a final-stage triage step, not a per-candidate filter, regardless of which engine runs it.

Serves **stability/thermostabilization** (relax + short MD → RMSD/RMSF), **de novo binder design** and
**enzyme/catalytic design** (post-design relaxation before scoring — the AlphaFold-relax pattern
generalizes to any generated backbone), and **small-molecule binding** (OpenMM plus OpenFF/openmmforcefields
is the natural engine for protein-ligand system minimization and short binding-pose MD, since it can
parameterize an arbitrary small molecule in-process rather than requiring a separate topology-building
tool run outside the loop). Occupies the **simulate** stage, and — uniquely among the MD engines in this
toolkit — also effectively occupies part of the **score** stage, since `minimizeEnergy()`'s converged
potential energy is itself a cheap, directly comparable number across candidates.

## Invocation & I/O contract
- **How a unit of work is invoked:** Python API only (there is no separate mdrun-style CLI binary to
  shell out to; the "CLI" *is* a short Python script). Canonical pattern:
  ```python
  from openmm.app import *
  from openmm import *
  from openmm.unit import *

  pdb = PDBFile('input.pdb')
  forcefield = ForceField('amber19-all.xml', 'amber19/tip3pfb.xml')
  system = forcefield.createSystem(pdb.topology, nonbondedMethod=PME,
                                    nonbondedCutoff=1*nanometer, constraints=HBonds)
  integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.004*picoseconds)
  platform = Platform.getPlatform('CUDA')
  simulation = Simulation(pdb.topology, system, integrator, platform)
  simulation.context.setPositions(pdb.positions)
  simulation.minimizeEnergy()
  simulation.reporters.append(DCDReporter('output.dcd', 1000))
  simulation.step(10000)
  simulation.saveState('output.xml')
  ```
  (Pattern is the standard OpenMM user-guide "Running Simulations" idiom; every object —
  `System`, `Integrator`, `Context`, `Simulation` — is a live Python object the agent can introspect,
  modify, and re-serialize between calls, which is the central practical advantage over GROMACS's
  file-mediated grompp/mdrun contract for an agent that wants to vary parameters and branch on
  intermediate state.)
- **Inputs:** PDB/PDBx-mmCIF structure, force-field XML (bundled AMBER/CHARMM ffXML files, or
  generated on the fly for small molecules via `openmmforcefields`/OpenFF — see below).
- **Outputs:** trajectory via `Reporter` objects (DCD, PDB, XTC via third-party reporters), an XML
  `State` (`saveState`, portable across platforms/hardware, human-inspectable), and a binary
  `Checkpoint` (`saveCheckpoint`, platform- and hardware-specific, not portable).
- **A concrete example:** AlphaFold's Amber-relax module,
  `alphafold/relax/amber_minimize.py` (google-deepmind/alphafold) — loads a predicted PDB, builds an
  `amber99sb.xml` system with `HBonds` constraints, and calls `LocalEnergyMinimizer` on either the
  `CUDA` or `CPU` platform. This is the concrete, already-in-production precedent for "OpenMM as a
  relaxation step downstream of a structure predictor," and is the closest existing analogue to how
  this toolkit would use OpenMM.

**Force field handling:** `openmm/openmmforcefields` (a companion package, not core OpenMM) supplies a
`SystemGenerator` and residue-template generators — `GAFFTemplateGenerator`, `SMIRNOFFTemplateGenerator`
— that auto-parameterize small molecules lacking native templates, drawing on the Open Force Field
Initiative's SMIRNOFF-format force fields (the `openff-2.x.y` "Sage" line via the `openff-forcefields`
package). This is what makes OpenMM viable for small-molecule/ligand systems without a separate manual
parameterization step outside the agent's loop — a real capability gap relative to GROMACS, whose
`share/top/*.ff` directories only cover protein/nucleic-acid/lipid force fields and require external
tools (e.g., ACPYPE, CGenFF) for arbitrary ligands.

## Compute pattern
- **Pattern:** P1 (single-node, in-job GPU work — a `Simulation` binds to one `Context` on one
  `Platform` instance; OpenMM does not use an MPI rank layout the way GROMACS/LAMMPS do, even though it
  can address multiple GPUs on one node via platform properties). Secondary: P4 when a long production
  trajectory is submitted as its own batch job outside the agent's allocation.
- **GPU vendor portability:** **CUDA+HIP (partial/plugin), OpenCL (portable but declining), no native
  SYCL/XPU.** Evidence:
  - `CUDA` and `OpenCL` platforms are built into the core `openmm/openmm` repository.
  - `HIP` support (AMD GPUs, ROCm) is a **separate plugin**, `amd/openmm-hip`, AMD-maintained, not part
    of the core repo — installed via a distinct conda package (`conda create -n openmm-env -c streamhpc
    -c conda-forge --strict-channel-priority openmm-hip`) or built from source against `hipFFT`/`rocFFT`.
    This is architecturally different from GROMACS's single-source-tree `GMX_GPU=HIP` and is a real,
    documented gap: deploying OpenMM on Frontier is a second package with its own release cadence and
    compatibility matrix to track, not a build flag.
  - **No SYCL/XPU platform exists for OpenMM as of this research.** There is no core or
    widely-adopted community OpenMM SYCL backend for Intel GPUs; Aurora deployment of OpenMM is
    therefore an open problem, not a solved one — a sharp contrast with GROMACS's native DPCPP support.
    (Absence-of-evidence claim: multiple targeted searches for "OpenMM SYCL/XPU Aurora" returned no
    OpenMM-specific results, only adjacent projects adding SYCL backends for other codes. Flagged as
    inferred-from-absence, not a positive citation.)
- **State model:** checkpointable, with two distinct mechanisms and an important asymmetry —
  `saveCheckpoint`/`loadCheckpoint` (binary, exact, but tied to identical `System`, `Platform`,
  OpenMM version, and hardware) versus `saveState`/`loadState` (XML, portable across platforms and
  hardware, but does not preserve RNG state, so does not guarantee bit-identical continuation).
  For an agent that may resume a run on a *different* node than it started on (common after
  preemption/requeue on a leadership machine), **`saveState` is the safer default** — `saveCheckpoint`
  only works if the resumed job lands on matching hardware.
- **Data locality:** shared-FS for reading structures/force fields and writing trajectories/state;
  otherwise self-contained (no external database dependency at run time).
- **Staging burden:** none beyond the OpenMM install itself — bundled AMBER/CHARMM force-field XML
  ships with `openmm`/`openmmforcefields`; OpenFF SMIRNOFF force fields ship with `openff-forcefields`
  (small, a few MB).
- **Container availability:** community — official conda-forge packages (`openmm`, `openmm-hip`)
  exist and are the standard install path; no single official multi-platform container covering
  CUDA+HIP was identified, so a leadership deployment would assemble a container per target GPU vendor
  from conda-forge packages.

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA):** straightforward — `conda install -c conda-forge openmm`, `Platform` =
  `'CUDA'`. This is OpenMM's best-supported, most heavily used path.
- **Frontier (HIP):** requires the separate `openmm-hip` plugin package on top of a base `openmm`
  install (`conda -c streamhpc -c conda-forge`), built against ROCm's `hipFFT`/`rocFFT`. Workable, but
  a second, less mainstream dependency to validate and pin per ROCm version.
- **Aurora (SYCL/XPU):** **not currently deployable on GPU.** No SYCL/XPU platform exists; OpenMM would
  fall back to the CPU platform on Aurora, losing essentially all of the performance case for using it
  there. This is the single most important platform-risk finding for OpenMM in this project and should
  be weighed directly against GROMACS's native Aurora support when deciding which engine carries the
  Aurora MD workload.
- No license gate on any platform (MIT/LGPL).

## Agentic surface
- **Native MCP:** **community.** `PhelanShao/openmm-mcp-server` (GitHub) is a community MCP server
  offering "a structured communication interface for task submission, management, and execution" over
  OpenMM plus DFT via Abacus, with templates for protein/membrane simulations and CUDA/OpenCL GPU
  support. A second community project, `oumiya-pharm/openMM-Doc-MCP`, indexes OpenMM's documentation
  for semantic search rather than running simulations. Neither is an upstream/official OpenMM project.
  Downgraded per template rule: **community / unverified** (not independently run or audited here).
  Given OpenMM's native, idiomatic Python API, a bespoke thin MCP wrapper written for this project is
  likely lower-risk than adopting either community server as-is.
- **Parameters worth exposing for autonomous variation:**

  | parameter | type | sane range | default | trade-off |
  |---|---|---|---|---|
  | `nonbondedCutoff` | float, nm | 0.9–1.2 | 1.0 | accuracy vs. cost; too small silently changes the physics |
  | integrator timestep | float, fs | 1–4 | 2 (4 with HBonds constraints) | larger step is cheaper, requires H-bond constraints for stability |
  | `simulation.step(N)` | int | 10³–10⁷ | n/a | wall-clock vs. sampling |
  | minimization `tolerance`/`maxIterations` | float/int | tool defaults usually fine | library default | under-minimizing leaves clashes; over-minimizing wastes time for little gain |
  | `Platform` choice + precision (`'single'`/`'mixed'`/`'double'`) | enum | `'mixed'` for production | `'mixed'` | `'double'` is markedly slower with little practical accuracy benefit for relaxation use |
  | small-molecule template generator (`GAFFTemplateGenerator` vs `SMIRNOFFTemplateGenerator`) | enum | n/a | n/a | changes ligand force-field family — a scientific choice, not a free-for-all tuning knob |

- **Parameters that must NOT be agent-varied:** force-field identity mid-campaign (silently invalidates
  cross-candidate energy comparisons — a design scored with `amber14-all.xml` is not comparable to one
  scored with `amber99sb.xml`); `nonbondedMethod` (switching away from `PME` for a solvated system is a
  correctness error, not a tuning choice); random seed handling when reproducibility of a specific run
  is required for debugging (letting the agent silently vary this makes failures unreproducible).

## Failure modes & what the agent must check
- **Loud failure:** missing residue template (ligand/nonstandard residue with no force-field match)
  raises a Python exception at `createSystem()` — this is the single most common OpenMM failure for
  de novo/small-molecule work and is loud, which is good, but the fix (supply a template generator) is
  not automatic.
- **Silent bad output:** minimization can converge to a local minimum that still has a badly distorted
  region (e.g., a knotted loop) without raising any error — `minimizeEnergy()` succeeding is not proof
  the structure is sane. **Check:** compare pre/post-minimization RMSD (large values, e.g. > a few Å,
  flag a structure that moved further than "relaxation" should); re-run a quick structure-quality check
  (e.g., clash count, Ramachandran outliers via an external tool) on the minimized coordinates, not just
  the raw generative output. A converged-but-wrong potential energy is a classic confident-wrong-score
  failure mode this brief's template explicitly warns about.
- **Checkpoint/hardware mismatch:** attempting to `loadCheckpoint` a binary checkpoint on a different
  GPU architecture or OpenMM build silently produces either a load error or, worse per upstream issue
  reports, subtly wrong continuation — prefer `saveState`/`loadState` whenever the agent cannot
  guarantee identical hardware on resume (see State model above).

## Cost per unit of work
- **Relaxation/minimization unit:** one designed structure, `minimizeEnergy()` + a few thousand steps
  of restrained MD — **seconds to a couple of minutes** on one GPU. This is cheap enough to run on
  *every* design candidate and is the primary reason this brief treats OpenMM as high-value: it is the
  one MD-adjacent operation in this toolkit that survives contact with a per-candidate budget.
- **Short stability-MD unit:** directly comparable to GROMACS — published DHFR (~23,558-atom) benchmark
  on a single NVIDIA A100 reaches **32.3 ns/day** (scaling to 70.9 ns/day on 4 GPUs with NVLink); on
  AMD hardware, DHFR reaches roughly **417 ns/day (OpenCL) to 1,031 ns/day (HIP)** on a V620-class GPU
  in independent benchmarks (both figures from public OpenMM benchmark reporting, not re-verified
  in-house). A 20 ns trajectory at ~32 ns/day costs on the order of **15 hours on one A100** for this
  particular (smaller, unsolvated-shell) benchmark system — noticeably worse than the GROMACS figure
  quoted in `gromacs.md` for a larger, membrane-embedded system, a reminder that ns/day figures are not
  transferable across system composition/size and must be re-benchmarked per actual design-candidate
  system before being used in a budget policy.
- **Resource shape:** 1 GPU, 1 node for both use cases; no MPI rank layout to reserve.
- **Checkpointable:** yes (`saveState`/`saveCheckpoint`).
- **Implication for the agent's budget:** run relaxation/minimization on every candidate (cheap, high
  value, catches structural garbage early); reserve explicit-solvent stability MD for a short list of
  finalists, same as GROMACS.

## Verdict
**Core.** OpenMM is the single highest-value addition this cluster identifies: a genuine Python API
over a real GPU MD engine, cheap enough at the relaxation/minimization scale to run on every design
candidate (unlike full stability MD), already the field-standard choice for post-prediction relaxation
(AlphaFold's own Amber-relax step), and the natural engine for small-molecule/ligand systems via
`openmmforcefields`/OpenFF integration that GROMACS cannot match without external tooling. The one
serious caveat that must be carried forward into deployment planning: **OpenMM has no SYCL/XPU
platform**, so it cannot run on Aurora's GPUs today, and its HIP support is a separate,
less-mainstream plugin rather than a first-class build option. On Aurora specifically, GROMACS should
carry the explicit-solvent MD workload; OpenMM's relaxation role there would fall back to CPU-only
execution unless and until a SYCL backend appears.

## Sources
- OpenMM GitHub: https://github.com/openmm/openmm — version/license/platform info (external, not in refcodes).
- OpenMM User Guide, "Running Simulations": https://docs.openmm.org/latest/userguide/application/02_running_sims.html — code pattern, platform names, saveState/saveCheckpoint semantics.
- OpenMM User Guide, "Platform-Specific Properties": https://docs.openmm.org/latest/userguide/library/04_platform_specifics.html
- AlphaFold Amber-relax module: https://github.com/google-deepmind/alphafold/blob/main/alphafold/relax/amber_minimize.py — concrete relaxation-step precedent.
- openmmforcefields: https://github.com/openmm/openmmforcefields — SystemGenerator, GAFF/SMIRNOFF template generators.
- OpenFF force fields: https://github.com/openforcefield/openff-forcefields
- AMD openmm-hip plugin: https://github.com/amd/openmm-hip — HIP-as-separate-plugin architecture, conda install path.
- openmm/openmm GitHub issue #2306 (checkpoint vs. state XML semantics) and #3995 (restart from checkpoint/state) — external, cited for checkpoint/state distinction, not independently re-verified.
- Community MCP servers (unverified): https://github.com/PhelanShao/openmm-mcp-server ; https://github.com/oumiya-pharm/openMM-Doc-MCP
- DHFR/A100 and DHFR/AMD-V620 benchmark figures — public OpenMM benchmark reporting (biorxiv supplementary data, SaladCloud OpenMM GPU benchmark post) — external, secondary-source, flagged as not independently re-run.
- No OpenMM SYCL/XPU platform found in research (absence-of-evidence, multiple targeted searches, September 2026).
