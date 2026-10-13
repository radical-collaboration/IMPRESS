# Structure Preparation: PDBFixer, packmol, and the protonation-state problem

**One-line identity.** The unglamorous system-building step — repairing a raw structure, packing it
into a solvent box, and assigning protonation states — that sits between every generative/predictive
tool in this project and every MD run, and is the point where automated pipelines most often fail
silently rather than loudly.

## Identity
- **Version / release examined:** not in refcodes; researched upstream for all three tools.
  - **PDBFixer**: maintained in `openmm/pdbfixer` on GitHub, installed via
    `conda install -c conda-forge pdbfixer`. License not independently confirmed in this research pass
    (upstream is an OpenMM-family project, historically MIT-licensed like core OpenMM; not verified
    line-by-line here — flagged as inferred).
  - **packmol**: maintained by L. Martínez et al. (`m3g/packmol` on GitHub / m3g.github.io/packmol).
    Currently distributed under the **MIT License** per the official download page as of this research;
    earlier releases were GPLv2 — a licensing change worth re-confirming against the exact version
    pinned at deployment time.
  - **PROPKA / pdb2pqr**: PDB2PQR (Nucleic Acids Research, Dolinsky et al.) embeds PROPKA as its pKa
    predictor for protonation-state assignment; both are long-standing, actively used academic tools.
- **Provenance:** PDBFixer — Stanford/OpenMM ecosystem (Chodera/Pande-lineage). packmol — University
  of Campinas / University of São Paulo (Martínez group). PDB2PQR/PROPKA — Baker lab (PDB2PQR) and the
  Jensen group (PROPKA), both widely cited academic tools.
- **Maturity:** all three production-grade and heavily used as de facto standard preprocessing steps
  across the structural-biology/MD community; none is exotic or experimental.

## Scientific role
None of these three tools does science on its own — they are **preparation**, the pipeline stage that
sits between a generated/predicted structure and any of the **simulate** or **score** stages that
depend on a physically sane input. They matter across all four in-scope problem classes, because every
one of them eventually needs a structure that is complete, correctly protonated, and (for explicit-
solvent MD) solvated, before GROMACS/OpenMM can be trusted to produce a meaningful trajectory.

- **PDBFixer** — repairs a designed or predicted structure: fills missing heavy atoms, models missing
  loops from SEQRES, converts nonstandard residues to standard equivalents, resolves alternate-location
  ambiguity, strips unwanted heterogens/chains, adds hydrogens at a target pH, and can generate an
  explicit water box. This is the **generate → simulate** bridge: raw output from a structure predictor
  or an inverse-folding/design tool is very often not immediately simulatable.
- **packmol** — builds initial spatial configurations by packing molecules (solvent, ions, co-solutes,
  membrane lipids) into geometric regions without steric overlap, using a fast, non-physical
  optimization (not MD) that just needs to produce *a* clash-free starting configuration for the real
  simulation to relax from. This is the classic tool for solvating a protein beyond what a simpler
  rectangular-box water-fill can do, e.g., non-cubic geometries, mixed solvents, or membrane + water +
  protein composites.
- **PROPKA / pdb2pqr (the protonation-state problem)** — at physiological pH, histidine's protonation
  state (HID/HIE/HIP), and occasionally glutamate/aspartate/lysine/cysteine states, are not
  determined by the PDB file itself; guessing wrong changes the electrostatics of a binding site or
  catalytic residue in ways that silently bias every downstream MD/scoring result. This is *the*
  classic silent-failure point in automated MD prep: a wrong protonation state produces a structure
  that loads, minimizes, and simulates without any error, and just quietly encodes the wrong chemistry.
  This matters most acutely for **enzyme/catalytic design** (catalytic residue protonation state is
  often the entire point) and **small-molecule binding** (ligand and pocket-residue protonation states
  both affect binding-mode fidelity).

## Invocation & I/O contract
- **How a unit of work is invoked:**
  - PDBFixer (Python API, the primary interface): standard pattern (per upstream README/Manual;
    reconstructed from documented capabilities, not verbatim-quoted from a live fetch in this
    research pass — flag as inferred-but-standard):
    ```python
    from pdbfixer import PDBFixer
    from openmm.app import PDBFile

    fixer = PDBFixer(filename='input.pdb')
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.0)      # target pH
    fixer.addSolvent(padding=1.0)       # nm, optional explicit water box
    PDBFile.writeFile(fixer.topology, fixer.positions, open('fixed.pdb', 'w'))
    ```
    A CLI entry point (`pdbfixer input.pdb --output fixed.pdb`) also exists for simple cases.
  - packmol: CLI, input redirected from a `.inp` script — `packmol < pack.inp` (classic) or
    `packmol -i pack.inp -o output.pdb` (v21.1.0+). Minimal input:
    ```
    tolerance 2.0
    output solvated.pdb
    filetype pdb
    structure protein.pdb
      number 1
      fixed 0. 0. 0. 0. 0. 0.
    end structure
    structure water.pdb
      number 2000
      inside box 0. 0. 0. 40. 40. 40.
    end structure
    ```
    A companion `solvate.tcl` script automates the common "solvate a protein with water + ions to a
    target shell/charge/density" case, generating the `.inp` for the user.
  - PROPKA / pdb2pqr: CLI — `pdb2pqr30 --ff=AMBER --with-ph=7.0 --titration-state-method=propka
    input.pdb output.pqr` is the standard pattern; PROPKA can also be invoked standalone
    (`propka3 input.pdb`) to get a pKa report without producing a re-protonated structure file.
- **Inputs:** PDB/PDBx-mmCIF for PDBFixer and PROPKA/pdb2pqr; arbitrary single-molecule PDB/XYZ/Tinker/
  Moldy structure files for packmol's per-species building blocks.
- **Outputs:** PDBFixer → repaired/protonated/solvated PDB (or directly usable `topology`/`positions`
  objects if staying in-process with OpenMM, avoiding a file round-trip entirely). packmol → a single
  packed PDB/XYZ configuration. pdb2pqr → a `.pqr` file (PDB-like, with charge/radius columns replacing
  occupancy/B-factor) plus, optionally, a re-protonated PDB.
- **A concrete example:** the packmol minimal input above follows the structure documented at
  `m3g.github.io/packmol/userguide.shtml`; the PDBFixer sequence mirrors the documented capability list
  ("add missing heavy atoms," "add missing hydrogen atoms based on pH," "build a water box") from the
  upstream `openmm/pdbfixer` README.

## Compute pattern
- **Pattern:** P6 (in-process/CPU, sub-second-to-low-minutes for the system sizes this toolkit deals
  with) for PDBFixer and pdb2pqr/PROPKA. **P6 primary / P2 secondary** for packmol specifically — its
  packing optimization is CPU-bound and scales with molecule count, so a large explicit-solvent box
  (many thousands of water molecules plus ions) can run tens of seconds to a few minutes, and packing
  many independent systems in parallel (one per design candidate) is an embarrassingly parallel fan-out.
- **GPU vendor portability:** n/a — all three are CPU-only tools; no GPU code path exists or is needed.
- **State model:** stateless. Each run reads input structure(s) and writes a new structure; there is no
  meaningful checkpoint concept and re-running is cheap.
- **Data locality:** self-contained / shared-FS for reading inputs and writing outputs; no streaming
  requirement.
- **Staging burden:** none of consequence — no model weights, no large reference database. PDBFixer's
  loop-building and mutation logic use small bundled residue-template data; pdb2pqr ships small
  force-field parameter files (AMBER/CHARMM/PARSE/TYL06 parameter sets) that are trivial in size.
- **Container availability:** community — all three install cleanly via conda-forge
  (`pdbfixer`, `packmol`, `pdb2pqr`), and no official leadership-machine container was identified for
  any of them; none is large enough to need Apptainer-level care — a conda environment shared across
  the design pipeline is the realistic deployment unit.

## Deployment on DOE & ACCESS
No platform-specific blockers on Frontier, Aurora, Polaris, or ACCESS — all three tools are CPU-only
and portable via conda/pip identically across every target machine. This is a genuinely easy deployment
relative to every GPU-dependent tool elsewhere in this toolkit: install once into the shared
Python/conda environment used for pre- and post-processing, no vendor-specific build variant needed.
No license gate identified for any of the three (PDBFixer inferred MIT-family; packmol currently MIT
per upstream; PDB2PQR/PROPKA both open-academic-license, non-restrictive).

## Agentic surface
- **Native MCP:** no, for all three. No upstream MCP server was found for PDBFixer, packmol, or
  PROPKA/pdb2pqr in this research pass. Given how small and scriptable each tool's interface is (a
  handful of Python calls or a short CLI invocation), a bespoke thin wrapper is the realistic path
  rather than waiting on a community server.
- **Parameters worth exposing for autonomous variation:**

  | parameter | type | sane range | default | trade-off |
  |---|---|---|---|---|
  | PDBFixer target pH (`addMissingHydrogens(pH)`) | float | 5.0–9.0 | 7.0 | shifts histidine/other titratable-residue protonation states — a scientific choice tied to the intended assay condition, not free-tuning |
  | PDBFixer solvent padding (`addSolvent(padding=...)`) | float, nm | 0.8–1.5 | tool default (~1.0) | larger padding reduces periodic self-interaction artifacts at higher atom-count/compute cost |
  | packmol `tolerance` | float, Å | 1.5–2.5 | 2.0 (typical convention) | tighter tolerance packs closer (denser, more realistic) but is slower to converge and more prone to failure-to-converge on dense systems |
  | packmol ion count / target salt concentration (via `solvate.tcl -charge`) | int / float | neutralizing + ~0.1–0.15 M physiological | neutralizing only | affects electrostatic screening in the simulation — a scientific choice for binding/catalytic work, not cosmetic |
  | pdb2pqr `--with-ph` | float | 5.0–9.0 | 7.0 | same protonation-state consequences as PDBFixer's pH parameter — **must be set consistently with whatever pH PDBFixer used for the same candidate** |

- **Parameters that must NOT be agent-varied:** pH must be held identical across PDBFixer and
  pdb2pqr/PROPKA *for the same structure* — using different pH values in the repair step versus the
  protonation-assignment step produces an internally inconsistent structure with no error raised.
  Force-field identity passed to pdb2pqr (`--ff=AMBER` vs `--ff=CHARMM`, etc.) must match whatever force
  field the downstream MD engine will use — a mismatch here is a silent-invalidity trap, not a
  performance trade-off. Nonstandard-residue replacement (`replaceNonstandardResidues`) should not be
  applied blindly to a design that *intentionally* contains a nonstandard residue (e.g., a designed
  noncanonical catalytic residue) — this is a correctness question the agent cannot resolve from the
  structure alone and must be gated by the design's own metadata.

## Failure modes & what the agent must check
This is explicitly the classic silent-failure point in automated MD, and the template's distinction
between loud and silent failure matters more here than almost anywhere else in the toolkit.

- **Loud failure:** PDBFixer raises on structures it cannot parse at all (severely malformed PDB);
  packmol exits non-zero (or, notoriously, simply fails to converge within its iteration budget and
  reports it did not reach the requested tolerance) on over-constrained packing problems (too many
  molecules requested for too small a box).
- **Silent bad output — the dominant risk class:**
  - **Wrong protonation state** (histidine tautomer, unexpected Asp/Glu/Lys/Cys ionization) changes
    electrostatics without any tool raising an error. **Check:** for any residue in or near a declared
    binding pocket or catalytic site, log the assigned protonation state explicitly (PROPKA's own pKa
    report, `propka3 input.pdb`, gives per-residue predicted pKa values) and flag any titratable
    residue whose predicted pKa sits within ~1 pH unit of the chosen simulation pH — these are the
    genuinely ambiguous cases that deserve a second look rather than a silent default.
  - **Modeled-in loops that are structurally implausible.** PDBFixer's missing-loop building uses a
    generic modeling procedure, not a validated structure-prediction model — a loop it fills in for a
    long missing stretch can be geometrically valid but scientifically meaningless. **Check:** flag any
    candidate where PDBFixer had to model a missing-residue stretch longer than a few residues, and
    treat the region as lower-confidence in downstream scoring rather than trusting it equally with
    resolved/predicted regions.
  - **packmol "success" that is actually a poor pack.** packmol can report convergence while leaving a
    configuration with borderline-close contacts that a subsequent energy minimization has to resolve
    aggressively — this is usually harmless (minimization fixes it) but **check** that a post-pack
    minimization is always run before production MD, never skipped as an optimization, because the
    packing step's job is "no hard overlaps," not "physically relaxed."
  - **Inconsistent pH/force-field pairing across the PDBFixer → pdb2pqr → MD-engine chain** (see
    Parameters that must NOT be agent-varied) — this produces a structure that loads and simulates
    without complaint while encoding the wrong chemistry throughout. **Check:** assert pH and
    force-field family match across every stage of the prep chain for a given candidate before handing
    it to the MD engine, as an explicit pipeline invariant rather than an implicit assumption.

## Cost per unit of work
- **Unit of work:** preparing one design candidate for MD (repair + protonate + solvate).
- **Typical wall-clock:** PDBFixer — seconds for a single-chain protein of the size this toolkit deals
  with (hundreds of residues); pdb2pqr/PROPKA — seconds; packmol — seconds to a couple of minutes
  depending on box size and solvent molecule count (a many-thousand-water explicit box is the slow end
  of this range).
- **Resource shape:** single CPU core, no GPU, no special node type.
- **Checkpointable:** n/a (stateless, cheap to re-run in full rather than partially resume).
- **Implication for the agent's budget:** negligible relative to every other stage in the pipeline —
  this is not a cost-gating decision the way MD or structure prediction are. The gating concern here is
  correctness, not compute: the cost of getting this step wrong is not wasted GPU-hours, it is a
  downstream MD trajectory (hours of real compute) built on a silently wrong input, which is a far more
  expensive failure than the prep step itself.

## Verdict
**Core.** Every MD run and every relaxation step in this toolkit depends on structure preparation
having been done correctly, and this cluster's own research explicitly frames prep as the classic
silent-failure point in automated MD — an assessment this brief's Failure modes section bears out
directly. PDBFixer and packmol are the load-bearing repair/packing tools (both should be included);
PROPKA/pdb2pqr-driven protonation assignment is the load-bearing correctness check that must run
alongside them whenever a candidate's binding-site or catalytic-residue chemistry actually matters to
the design goal (enzyme/catalytic design, small-molecule binding) — treated as a required companion
step, not an optional add-on, given how easily a wrong protonation state produces a confident, silently
wrong downstream result.

## Sources
- PDBFixer README/repository: https://github.com/openmm/pdbfixer — capability list (missing atoms/
  hydrogens/loops, nonstandard-residue conversion, water box). Python API code pattern in this brief is
  reconstructed from documented capabilities and standard published usage, not verbatim-quoted from a
  successfully fetched live source in this research pass — flagged as inferred-but-standard, not
  independently verified against the exact current API signature.
- packmol user guide: https://m3g.github.io/packmol/userguide.shtml — input syntax, CLI invocation.
- packmol download/license page: https://m3g.github.io/packmol/download.shtml — MIT license claim for
  current releases; historical GPLv2 licensing noted from the public GitHub mirror's `LICENSE` file
  (external, not independently reconciled to a specific version here).
- PDB2PQR: Dolinsky et al., Nucleic Acids Research, "PDB2PQR: expanding and upgrading automated
  preparation of biomolecular structures for molecular simulations" — https://academic.oup.com/nar/article/35/suppl_2/W522/2920806
- PROPKA integration in PDB2PQR — general description per PDB2PQR documentation; not independently
  re-verified against a specific PROPKA version in this research pass.
- No upstream MCP server found for PDBFixer, packmol, or PROPKA/pdb2pqr (absence-of-evidence, September
  2026 research).
