# MDAnalysis & MDTraj

**One-line identity.** Two complementary Python trajectory-analysis libraries — MDAnalysis for
selection-grammar-driven, multi-engine analysis; MDTraj for lightweight, fast, ad-hoc geometric
metrics — that together are the mechanism by which a raw MD trajectory becomes the scalar number an
autonomous agent can actually act on.

## Identity
- **Version / release examined:** not in refcodes; researched upstream.
  - MDAnalysis: 2.8.0 (2024-11-22) is the most recent version release confirmed by name in research;
    development continues on `2.11.0-dev0` per `docs.mdanalysis.org/dev/`. GPLv2 core license (PMDA
    parallel-analysis companion package is also GPLv2).
  - MDTraj: latest release found is `1.11.1.post2` (2026-07-08). License: LGPL v2.1 (or later, at the
    user's option).
- **Provenance:** MDAnalysis — Beckstein/Oliver lab and a broad academic collaboration
  (mdanalysis.org). MDTraj — originated at Stanford (Pande lab), now maintained by community
  contributors including Folding@Home, the Molecular Sciences Software Institute, and the Open Force
  Field Initiative.
- **Maturity:** both production, both very widely cited/used across the MD community. Neither is
  present in `impress-a-refcodes/tools/`; both would need to be added if adopted.

## Scientific role
This is the step that closes the autonomous loop: MD engines (GROMACS, OpenMM) produce a trajectory,
but a trajectory is not a decision input — it is a large binary blob of coordinates. **The agent needs
a number** (an RMSD value, an RMSF profile summarized to a scalar, a SASA delta, a contact-map
similarity, a hydrogen-bond-occupancy fraction) that it can threshold, rank candidates by, or feed to a
policy. MDAnalysis and MDTraj are the tools that make that reduction:

- **RMSD / RMSF** → stability/thermostabilization: does the designed fold hold its backbone geometry
  over the trajectory, and which residues/regions are the floppiest?
- **SASA (solvent-accessible surface area)** → binding-interface burial in de novo binder design and
  small-molecule binding: does a putative interface actually bury surface area over the trajectory, or
  does it dissociate?
- **Hydrogen bonds / contacts** → enzyme/catalytic design and small-molecule binding: are the
  catalytic-residue or binding-pocket contacts that the design intended actually maintained under
  thermal motion, or do they break within nanoseconds?
- **Radius of gyration** → coarse compactness/unfolding signal, cheap early warning that a design is
  coming apart.

Occupies the **analyze** pipeline stage exclusively — it does not generate structures or run physics,
it reads what GROMACS/OpenMM/LAMMPS already wrote and reduces it. This is the single most important
tool pairing for making MD *useful* to an autonomous loop rather than merely descriptive: without this
step, an MD trajectory is inert output; with it, MD becomes a scored filter.

**Division of labor:** MDTraj (`md.load`, `md.rmsd`, `md.compute_rg`, `shrake_rupley`,
`compute_contacts` — all pure-Python-callable, no object-oriented ceremony) is the right choice for a
single, ad-hoc metric on one trajectory — minimal boilerplate, fast. MDAnalysis (`Universe`,
`select_atoms`, the `analysis.rms.RMSD`/`RMSF` classes built on the `AnalysisBase` framework, and
`analysis.hydrogenbonds`) is the right choice when the agent needs (a) MDAnalysis's atom-selection
grammar for complex, named selections (e.g., "binding-pocket residues within 5 Å of the ligand"), (b)
native readers for LAMMPS/NAMD/CHARMM-format trajectories GROMACS/OpenMM tooling doesn't cover, or (c)
`AnalysisBase`-level parallelism (the `pmda`/in-development-core `analysis` parallel split-apply-combine
path) across many independent trajectories. An independent comparison found both libraries deliver a
standard RMSD/RMSF/Rg pipeline in a comparable ~100-120 lines of code — neither has a decisive ergonomic
edge for the common case, so the practical choice is driven by selection-grammar and format-support
needs, not raw convenience.

## Invocation & I/O contract
- **How a unit of work is invoked:** Python API only, in both cases.
  - MDTraj: `t = md.load('trajectory.xtc', top='topology.pdb')`; then `md.rmsd(t, t, 0)`,
    `md.compute_rg(t)`, `md.shrake_rupley(t)`, `md.compute_contacts(t)`.
  - MDAnalysis: `u = mda.Universe('topology.tpr', 'trajectory.xtc')`; `calphas =
    u.select_atoms("name CA")`; `from MDAnalysis.analysis.rms import RMSF; rmsfer =
    RMSF(calphas, verbose=True).run()`; result in `rmsfer.results.rmsf`. Alignment + RMSD:
    `aligner = align.AlignTraj(u, reference, select="protein and name CA",
    in_memory=True).run()`, result in `aligner.results.rmsd`.
- **Inputs:** any trajectory/topology pair either library's format readers cover — GROMACS `.xtc`/`.trr`
  + `.tpr`/`.gro`, OpenMM DCD + PDB, LAMMPS dump formats (MDAnalysis has native LAMMPS readers; MDTraj's
  LAMMPS support is narrower). This is the direct downstream consumer of the `.trr`/`.xtc`/`.dcd`
  outputs documented in `gromacs.md` and `openmm.md`.
- **Outputs:** in-memory NumPy arrays / typed `.results` objects (MDAnalysis `AnalysisBase` subclasses
  since the 2.x refactor expose results under a uniform `.results` namespace) — not files, unless the
  agent's own code writes them out. This is exactly the shape an agent wants: a plain array or scalar
  to compare, threshold, or log, not another file to parse.
- **A concrete example:** MDAnalysis RMSF pattern (`analysis.rms.RMSF`) and the `AlignTraj`-based RMSD
  pattern above are both current, documented, stable public API (MDAnalysis 2.x `analysis.rms` module).

## Compute pattern
- **Pattern:** P6 (primary — in-process, sub-second-to-low-seconds for a single metric on a single
  trajectory of the size this toolkit deals with) / P2 (secondary — when the agent needs the same
  metric computed over a large ensemble of independent trajectories, e.g., scoring 50 finalist
  candidates' stability trajectories in one fan-out batch; MDAnalysis's `AnalysisBase`
  parallel-split-apply-combine path and the standalone `pmda` package exist specifically for this case).
- **GPU vendor portability:** n/a — both libraries are CPU-only, NumPy/Cython-based analysis code; no
  GPU kernel exists or is needed at this trajectory-analysis scale.
- **State model:** stateless. Each analysis run reads a trajectory file and produces a result; there is
  nothing to checkpoint, and re-running is cheap and idempotent.
- **Data locality:** shared-FS required to read the trajectory/topology files the MD engine wrote;
  otherwise self-contained once loaded into memory.
- **Staging burden:** none — pure pip/conda-installable Python packages, no model weights, no external
  database.
- **Container availability:** community (conda-forge packages `mdanalysis` and `mdtraj` are the
  standard install path; no official multi-arch container specific to either library was identified,
  but neither needs one — they layer trivially into any Python environment that already has the MD
  engine's output on disk).

## Deployment on DOE & ACCESS
No platform-specific concerns on any of Frontier, Aurora, Polaris, or ACCESS — both libraries are
CPU-only and install via `pip`/`conda` identically everywhere. The only per-platform consideration is
ensuring the analysis environment can read the trajectory format the site's MD engine wrote (e.g., TNG
support in MDAnalysis if GROMACS was built with `GMX_USE_TNG=ON`, the default per
`gromacs/CMakeLists.txt:386`). No license gate (GPLv2 / LGPLv2.1).

## Agentic surface
- **Native MCP:** no. No upstream MCP server was found for either library. (A community MCP server
  wrapping ChimeraX/PyMOL for molecule *visualization* — `ChatMol/molecule-mcp` — exists but is not a
  trajectory-analysis server and is out of scope for this brief; not claimed as coverage.)
- **Parameters worth exposing for autonomous variation:**

  | parameter | type | sane range | default | trade-off |
  |---|---|---|---|---|
  | atom selection string (e.g., `"name CA"`, `"protein and backbone"`) | str | selection-grammar-valid | tool-specific | which atoms define the metric — changes the number's meaning, not just its precision |
  | reference frame for RMSD/alignment | int (frame index) or separate reference structure | frame 0 or a relaxed/minimized reference | frame 0 | RMSD-to-start vs. RMSD-to-a-known-good reference measure different things |
  | H-bond distance/angle cutoffs | float (Å) / float (deg) | 3.0–3.5 Å, 120–150° | MDAnalysis default ≈ 3.0 Å / 120° | looser cutoffs count more (weaker) bonds — changes occupancy fractions materially |
  | SASA probe radius | float (Å) | 1.4 (water probe, standard) | 1.4 | almost never worth varying; listed for completeness |
  | trajectory stride/frame subsampling | int | 1–10 | 1 | cheaper analysis vs. temporal resolution of the metric |

- **Parameters that must NOT be agent-varied:** the atom selection used for a *specific declared
  metric* must stay fixed across all candidates being compared in one ranking pass (varying the CA
  selection between candidate A and candidate B silently makes their RMSD/RMSF values incomparable —
  this is a correctness trap, not a tuning knob); do not let the agent silently change H-bond/contact
  cutoffs between a baseline measurement and a comparison measurement for the same claim.

## Failure modes & what the agent must check
- **Loud failure:** malformed/truncated trajectory files raise parser exceptions on `Universe()`/`md.load()`;
  an atom-selection string that matches zero atoms in MDAnalysis raises (empty `AtomGroup` used in an
  analysis class typically errors or warns loudly).
- **Silent bad output — the dominant risk here:** an atom-selection typo that matches the *wrong but
  non-empty* set of atoms (e.g., `"name CA"` accidentally including a ligand's carbon atoms because of
  a naming collision, or a selection that silently drops a chain) produces a plausible-looking RMSD/RMSF
  number that is simply not measuring what the agent thinks it is. **Check:** log the resolved atom
  count and a spot-check identity (e.g., first/last residue name and number in the selection) alongside
  every computed metric, not just the metric itself, so a downstream reviewer (or a sanity-check rule)
  can catch a selection that silently changed scope between runs. A second silent failure: computing
  RMSD/RMSF over an **unequilibrated** portion of the trajectory (the first few hundred ps before the
  system has relaxed from its initial conditions) inflates the metric in a way that looks like genuine
  instability — **check** that the equilibration check from the MD engine's own brief (temperature/
  energy plateau) has been satisfied before trusting the analysis window.

## Cost per unit of work
- **Unit of work:** one metric (RMSD, RMSF, SASA, or an H-bond/contact count) computed over one
  trajectory of the size this toolkit produces (tens of ns, thousands of frames at typical output
  stride).
- **Wall-clock:** sub-second to a few seconds per metric per trajectory on a single CPU core — this is
  the textbook P6 case the taxonomy calls out: scheduling this as a discrete task would cost more in
  orchestration overhead than the computation itself.
- **Resource shape:** none beyond the agent's own process; no dedicated allocation needed.
- **Checkpointable:** n/a (stateless, re-runnable at negligible cost).
- **Implication for the agent's budget:** free relative to every MD or structure-prediction step in
  this toolkit. The cost-gating conversation in `gromacs.md`/`openmm.md` (whether to run MD on every
  candidate) does not apply here — once a trajectory exists, extracting every metric this brief
  describes from it is essentially free, so the agent should compute the full metric suite on every
  trajectory it *does* produce, not economize on analysis once the expensive MD step has already run.

## Verdict
**Core.** This is not optional infrastructure — it is the mechanism by which the expensive, sparingly-
run MD steps (GROMACS/OpenMM, gated to final-stage triage per those briefs' cost analysis) actually
produce a decision-usable output. Without MDAnalysis/MDTraj (or an equivalent), MD trajectories are
dead weight: correct physics, unusable results. Both libraries should be in the toolkit; MDTraj as the
lightweight default for single-metric ad-hoc checks, MDAnalysis for anything needing its selection
grammar, multi-format readers, or ensemble-parallel analysis path.

## Sources
- MDAnalysis documentation, `analysis.rms` module: https://docs.mdanalysis.org/stable/_modules/MDAnalysis/analysis/rms.html
- MDAnalysis RMSD/alignment user guide: https://userguide.mdanalysis.org/1.0.1/examples/analysis/alignment_and_rms/rmsd.html
- MDAnalysis release notes (2.8.0): https://www.mdanalysis.org/2024/11/22/release-2.8.0/
- MDAnalysis PMDA (parallel analysis): https://github.com/MDAnalysis/pmda
- MDTraj GitHub / analysis reference: https://github.com/mdtraj/mdtraj ; https://mdtraj.org/1.9.4/analysis.html
- MDTraj PyPI (version/license): https://pypi.org/project/mdtraj/
- `<workspace>/impress-a-refcodes/tools/gromacs/CMakeLists.txt:386` (`GMX_USE_TNG` default ON — trajectory format an analysis environment must support)
- Comparative LOC/workflow observation (MDTraj vs. MDAnalysis, ~103 vs. 118 lines for a standard RMSD/RMSF/Rg pipeline) — external secondary source, not independently re-verified.
- No upstream MCP server found for either library (absence-of-evidence, September 2026 research).
