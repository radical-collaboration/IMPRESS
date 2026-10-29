# Rosetta Enzyme Design (match / enzyme_design, .cst / .params workflow)

**One-line identity.** Rosetta's theozyme-driven catalytic-site design pipeline — `match` (places an idealized active-site geometry, the "theozyme," into a scaffold) and `enzyme_design` (redesigns the surrounding shell for binding/catalysis under those geometric constraints) — built on hand-authored constraint (`.cst`) files and ligand `.params` files.

## Identity
- **Version / release examined:** app binaries in `source/src/apps/public/match/` (`match.cc`, `gen_lig_grids.cc`, `gen_apo_grids.cc`) and `source/src/apps/public/enzdes/` (`enzyme_design.cc`, `CstfileToTheozymePDB.cc`, `ES10_broad2.xml`); protocol library `source/src/protocols/enzdes/` (EnzdesBaseProtocol, EnzdesFixBBProtocol, EnzdesFlexBBProtocol, EnzdesTaskOperations, EnzdesMovers) and `source/src/protocols/toolbox/match_enzdes_util/` (constraint I/O, `EnzConstraintIO.cc`). Same refcode/version context as `rosetta.md`.
- **Provenance:** RosettaCommons; `enzyme_design.cc` authored by Florian Richter (Baker lab lineage). Refcode path: `tools/rosetta/source/src/apps/public/{match,enzdes}/`, `tools/rosetta/source/src/protocols/enzdes/`, `tools/rosetta/source/src/protocols/toolbox/match_enzdes_util/`.
- **Maturity:** production/active-research. The matching+enzdes pipeline dates to ~2006-2010 (Röthlisberger 2008 Kemp eliminase, Jiang 2008 retro-aldolase) and remains the standard Rosetta approach for new catalytic-site design, still maintained (`EnzdesFlexBBProtocol`, KIC loop sampling options present and current).

## Scientific role
Serves the **enzyme/catalytic design** problem class end-to-end, and touches **small-molecule binding** wherever a ligand `.params` file is required (any non-canonical residue or small molecule). Pipeline stages: **generate/search** (`match` — finds scaffold positions and rotamers satisfying the theozyme geometry), **design** (`enzyme_design` — `EnzdesFixBBProtocol`/`EnzdesFlexBBProtocol` redesign the shell around the matched catalytic residues), **score/analyze** (constraint-satisfaction + standard Rosetta energetics + optional `EnzFilters`).

The workflow has three artifacts that must exist before any design step runs:
1. **A theozyme specification** — a small hand-built PDB or set of idealized catalytic-residue/ligand geometries representing the proposed reaction mechanism (transition-state model + catalytic side chains). This is scientific/chemical judgment, not something Rosetta generates.
2. **A `.cst` constraint file** — machine-readable geometric constraints (distances, angles, torsions) between theozyme atoms and protein atoms, parsed by `EnzConstraintIO::read_enzyme_cstfile()` (`source/src/protocols/toolbox/match_enzdes_util/EnzConstraintIO.cc:91`). Real example, `source/test/protocols/enzdes/ligtest_it.cst` (esterase dyad + oxyanion hole):
   ```
   CST::BEGIN
     TEMPLATE::   ATOM_MAP: 1 atom_name: C6 O4 O2
     TEMPLATE::   ATOM_MAP: 1 residue3: D2N
     TEMPLATE::   ATOM_MAP: 2 atom_type: Nhis,
     TEMPLATE::   ATOM_MAP: 2 residue1: H
     CONSTRAINT:: distanceAB:    2.00   0.30 180.00  0
     CONSTRAINT::    angle_A:  105.10   6.00 100.00  360.00
     CONSTRAINT::    angle_B:  116.90   5.00   0.00  360.00
     CONSTRAINT::  torsion_A:  105.00  10.00   0.00  360.00
     CONSTRAINT::  torsion_B:  180.00  10.00   0.00  180.00
     CONSTRAINT:: torsion_AB:    0.00   0.00   0.00  180.00
   CST::END
   ```
   Each `CST::BEGIN`/`CST::END` block defines one catalytic interaction (here: proton-abstracting histidine, then two more blocks for oxyanion-hole Ser/Asn). Each block's numeric parameters are `ideal_value tolerance force_constant periodicity`, hand-derived from the intended reaction mechanism.
3. **Ligand `.params` files** — Rosetta's residue-type definition for any non-standard chemical entity, generated from an MDL Molfile/SDF via `source/scripts/python/public/molfile_to_params.py` (documented purpose: "taking a ligand from an MDL Molfile and splitting it into one or more .params files for Minirosetta"). A minimal hand-written example exists at `source/test/devel/znhash/ZNX.params` (a Zn2+ center with virtual coordination atoms):
   ```
   NAME ZNX
   IO_STRING ZNX Z
   TYPE LIGAND
   ATOM ZN   Zn2p  X   2.0
   ATOM  V1  VIRT  X   0.0
   ...
   BOND  ZN   V1
   NBR_ATOM  ZN
   NBR_RADIUS 0.0
   ICOOR_INTERNAL ...
   ```
   In practice, most ligands go through `molfile_to_params.py` rather than hand-authoring, but the file format itself (atom types, bonds, internal coordinates, `NBR_ATOM`/`NBR_RADIUS` for neighbor detection) is always hand-inspectable and frequently needs hand-correction (protonation state, partial charges, rotatable-bond definitions) before it is fit for design use.

## Invocation & I/O contract
- **How a unit of work is invoked:** two-stage CLI.
  ```
  # Stage 1: matching — place theozyme onto scaffold positions
  match -s scaffold.pdb -match:lig_name LIG \
      -match:geometric_constraint_file theozyme.cst \
      -match:scaffold_active_site_residues active_site.pos \
      -extra_res_fa LIG.params

  # Stage 2: enzyme design — redesign shell under constraints
  enzyme_design -s matched_output.pdb \
      -enzdes:cstfile theozyme.cst \
      -enzdes:cst_opt -enzdes:cst_design -enzdes:cst_min \
      -enzdes:detect_design_interface -enzdes:favor_native_res 0.5 \
      -extra_res_fa LIG.params -nstruct 100
  ```
  (`match.cc` reads `option[basic::options::OptionKeys::match::lig_name]`, `match::ligand_rotamer_index`, confirmed at `source/src/apps/public/match/match.cc:112,116`; `enzyme_design.cc` calls `EnzdesBaseProtocol::register_options()` / `EnzdesFixBBProtocol::register_options()` / `EnzdesFlexBBProtocol::register_options()` at startup, `enzyme_design.cc:70-72`.)
- **Inputs:** scaffold PDB, theozyme `.cst` file, ligand `.params` file(s) (via `-extra_res_fa`), optionally a PSSM/sequence profile for `-enzdes:make_consensus_mutations` or `-enzdes:favor_native_res`.
- **Outputs:** matched PDB structures with the theozyme placed (from `match`); designed PDB/silent-file decoys plus a scorefile from `enzyme_design`, with constraint-satisfaction terms (`atom_pair_constraint`, `angle_constraint`, `dihedral_constraint`) reported alongside standard Rosetta energy terms.
- **A concrete example (from the repo's own test data):** `source/test/protocols/enzdes/ligtest_it.cst` is a genuine, runnable 3-block cstfile for an esterase dyad+oxyanion-hole theozyme (esterase active site featuring a catalytic dyad, author F. Richter, Baker lab — header comment in the file itself).

## Compute pattern
- **Pattern:** **P2** (CPU-parallel fan-out, in-job) for the design stage — `enzyme_design` `nstruct` decoys are independent, identical fan-out to FastDesign. The `match` stage is also fundamentally P2 (each candidate scaffold position/rotamer combination can be evaluated independently), though it is often run as a single longer job that internally enumerates a combinatorial rotamer/position search rather than being split externally by the user.
- **GPU vendor portability:** CPU-only — same evidence base as `rosetta.md` (no CUDA/HIP/SYCL in `protocols/enzdes/` or `protocols/toolbox/match_enzdes_util/`).
- **State model:** restart-required per decoy/match search; checkpointable at the ensemble level via `-enzdes:checkpoint <filename>` — an explicit, named checkpoint-file option exists (`Option('checkpoint', 'String', default='', ...)`, `options_rosetta.py:5977`), unusual among Rosetta apps and worth using for long enzdes campaigns.
- **Data locality:** self-contained per matched structure; shared-FS only matters if a shared PSSM/consensus-mutation profile or large ligand rotamer grid file is reused across a fan-out batch.
- **Staging burden:** standard Rosetta `database/`, plus per-campaign ligand `.params`/`.cst` files (small, KB-scale, but must be hand-validated — see Failure modes).
- **Container availability:** official (same `rosettacommons/rosetta` image; `match`/`enzyme_design` are standard `apps/public` binaries).

## Deployment on DOE & ACCESS
Same CPU-only, build-required, license-gated story as `rosetta.md` — nothing platform-specific changes for the enzyme-design apps beyond what already applies to the Rosetta binary as a whole. No additional staging burden beyond the standard database and small per-project `.cst`/`.params` files, which travel trivially with the job (no large external database download required for matching/enzdes itself, unlike e.g. MSA-based generative tools).

## Agentic surface
- **Native MCP:** no (same community-MCP caveat as `rosetta.md`).
- **Parameters worth exposing for autonomous variation:**

| parameter | type | sane range | default | trade-off |
|---|---|---|---|---|
| `nstruct` | int | 20–500 | protocol-dependent | more decoys = better chance of finding a low-energy, constraint-satisfying design; linear cost |
| `enzdes:favor_native_res` | real | 0.0–2.0 | 0.5 | bonus energy for keeping the native residue during design; higher = more conservative redesign, safer but less exploratory |
| `enzdes:ex_catalytic_rot` | int (0-7) | 1–3 typical | 1 | extra rotamer sampling levels specifically for catalytic residues; higher improves geometric precision of the catalytic constraint at real cost in packer runtime |
| `enzdes:design_min_cycles` | int | 1–5 | 1 | number of design/minimize iteration cycles; more cycles converge design further from the starting sequence, at linear cost |
| `enzdes:cst_opt` / `cst_min` / `cst_design` (stage toggles) | bool | — | all `false` | these gate which sub-stages actually run; turning on `cst_design` without `cst_opt` skips the pre-design constraint-geometry optimization step, risking a design built around a poorly-satisfied theozyme |
| `enzdes:detect_design_interface` | bool | — | `false` | auto-detects the design/repack shell around the ligand instead of requiring a hand-specified resfile; convenient for autonomous use but must be paired with `include_catres_in_interface_detection` (below) to avoid missing catalytic-adjacent positions |
| `match:lig_name` / mutation of the theozyme geometry itself | n/a | n/a | n/a | **must not be auto-varied** — see below |

- **Parameters that must NOT be agent-varied:** the `.cst` file's `CONSTRAINT::` numeric parameters (ideal value/tolerance/force constant) encode the chemist's mechanistic hypothesis — an agent that "optimizes" these to make constraints easier to satisfy is optimizing away the scientific content of the design, not improving it. Similarly `enzdes:bb_min_allowed_dev`/`loop_bb_min_allowed_dev` (how far the backbone is allowed to drift before a penalty) should be treated as a scientific tolerance set by domain judgment, not a free autonomous-search knob. `enzdes:cst_dock`'s implicit behavior — "constraints (except covalent connections) will be turned off for this stage" (`options_rosetta.py`, `cst_dock` description) — means docking-stage results must never be read as constraint-satisfying without re-verification after the constraints are turned back on.

## Failure modes & what the agent must check
This is the protocol family where **honesty about required expert hand-holding matters most** for an autonomy assessment.
- **Loud failure:** missing `.params` for a HETATM/ligand residue (exits with "residue type not found" or similar), malformed `.cst` file — `EnzConstraintIO::read_enzyme_cstfile` explicitly exits with "Undefined error when reading cstfile. Something is wrong with the format (no CST::END tag maybe?)" (`EnzConstraintIO.cc:158`) and "Error: catalytic map in pdb file and information in cst file don't match... there is no correctly formatted info given in the REMARK block, or there are more constraint REMARKS than blocks in the .cst file" (`EnzConstraintIO.cc:279`) — this second error is a common, informative loud failure when the matched PDB's `REMARK` block (which records which cst block maps to which residue) gets out of sync with the `.cst` file itself.
- **Silent bad output — the dominant hazard for this protocol family:**
  - **Constraint satisfaction achieved geometrically but chemically meaningless** — the packer/minimizer can find a low-`atom_pair_constraint`/`angle_constraint` solution that technically satisfies the numeric tolerances in the `.cst` file while placing the catalytic residue in an orientation that makes no chemical sense (wrong protonation state accessible, wrong face of the ring, etc.) if the theozyme geometry itself was under-specified. The agent must check the **energy breakdown of individual constraint terms**, not just the total constraint score, and should not accept a design purely because `atom_pair_constraint ≈ 0`.
  - **Ligand `.params` chemistry errors are silent at the Rosetta level** — an incorrect protonation state, wrong bond order, or wrong partial charge in a `.params` file does not cause `match`/`enzyme_design` to fail; it causes them to succeed at optimizing the wrong molecule. This is arguably the single highest-leverage manual-review point in the entire pipeline, and is exactly the kind of chemistry judgment that historically required an expert to eyeball the `.params` file (or the Molfile/SDF that generated it) before trusting downstream results.
  - **Interface-detection under- or over-reach** — `enzdes:detect_design_interface` without `include_catres_in_interface_detection` can leave positions immediately adjacent to the catalytic residue as non-designable, silently freezing the shell exactly where it most needs to be optimized; conversely `arg_sweep_interface` (an aggressive interface-detection mode) can pull in irrelevant distal positions.
  - **KIC/backrub loop sampling for flexible-backbone enzdes** (`enzdes:flexbb_protocol`, `kic_loop_sampling`) is explicitly marked experimental in places — `remodel_secmatch`'s own description says "very experimental at this point" (`options_rosetta.py`) — and the agent should not treat flexbb output with the same confidence as fixed-backbone `enzyme_design` output without additional structural sanity checks (Ramachandran, clash, buried-unsat — same checks as `rosetta.md`).
- **How much expert hand-holding this historically requires (honest assessment):** substantial, and this is the central autonomy risk for the enzyme/catalytic design problem class. The theozyme specification and `.cst` file authoring step is fundamentally a mechanistic-chemistry judgment call that Rosetta does not automate — published enzyme-design campaigns (Kemp eliminase, retro-aldolase, and successors) were driven by expert-specified catalytic geometries, and even so, the *initial* computational designs were only weakly catalytic (see Cost/accuracy note below); most of the eventual activity came from subsequent laboratory directed evolution, not from the computational design step alone. An autonomous agent operating this pipeline end-to-end would need either (a) a pre-vetted library of theozyme/cstfile templates for known reaction classes that a domain expert has already validated, with the agent only varying design-stage parameters (favor_native_res, nstruct, interface detection), or (b) a much stronger LLM-driven mechanistic-chemistry reasoning capability than currently exists to author novel `.cst` files unsupervised. Recommend treating **theozyme/cstfile authoring as a human-in-the-loop gate**, not something Phase 1 autonomy should attempt to close end-to-end; the agent's autonomous surface should be scoped to design-parameter variation and post-hoc structural QC given a human-supplied (or template-library-supplied) theozyme.

## Cost per unit of work
- **1 `enzyme_design` decoy** (fixed-backbone, `cst_opt`+`cst_design`+`cst_min` stages, moderate `design_min_cycles`): comparable order of magnitude to a FastDesign pass — CPU-minutes to low tens of CPU-minutes per decoy for a ~200-residue scaffold, scaling up with `ex_catalytic_rot` level and interface size.
- **1 `match` run** (scaffold-wide theozyme placement search): highly variable — can range from CPU-minutes for a tightly pre-filtered active-site-residue list (`-match:scaffold_active_site_residues`) to CPU-hours for an unrestricted whole-scaffold search, because match enumerates position×rotamer combinations combinatorially. Always constrain the search space (active-site residue list, ligand rotamer pruning) rather than letting `match` search the full scaffold.
- **Flexible-backbone enzdes** (`flexbb_protocol`, `single_loop_ensemble_size` default 100, `loop_generator_trials` default 200) is substantially more expensive — each loop ensemble member is itself a backrub/KIC sampling run, multiplying cost by roughly the ensemble size relative to fixed-backbone design; budget accordingly before turning this on for autonomous campaigns.
- **Checkpointable:** yes, via `-enzdes:checkpoint <filename>` — an explicit checkpoint-file mechanism exists in this protocol family, unusual relative to most other Rosetta apps, and should be used for any campaign expected to run near a walltime boundary.

## Verdict
**Core** for the design-execution machinery (`enzyme_design`, `.params`/`.cst` I/O), **Recommended-with-a-human-gate** for the theozyme-specification step. The protocol family is the only enzyme/catalytic-design capability in this toolkit and there is no substitute — but its accuracy and reliability are fundamentally bottlenecked by the quality of a hand-authored theozyme and cstfile that Rosetta itself does not generate or validate for chemical sense, and by ligand `.params` correctness that fails silently rather than loudly. Include it as load-bearing infrastructure, but scope autonomous variation strictly to design-stage parameters and post-hoc structural QC; do not scope Phase 1 autonomy to include unsupervised theozyme/cstfile authoring.

## Sources
- `tools/rosetta/source/src/apps/public/enzdes/enzyme_design.cc` (main(), `register_options()` calls, lines 1-80)
- `tools/rosetta/source/src/apps/public/match/match.cc` (option usage, lines 112, 116)
- `tools/rosetta/source/src/protocols/enzdes/EnzdesBaseProtocol.cc` (register_options, lines 96-276)
- `tools/rosetta/source/src/protocols/toolbox/match_enzdes_util/EnzConstraintIO.cc` (cstfile parser and error messages, lines 88-164, 279)
- `tools/rosetta/source/test/protocols/enzdes/ligtest_it.cst` (real 3-block cstfile example, esterase dyad + oxyanion hole)
- `tools/rosetta/source/test/devel/znhash/ZNX.params` (hand-written ligand `.params` example)
- `tools/rosetta/source/scripts/python/public/molfile_to_params.py` (docstring, lines 1-14; option list, lines 1387-1500)
- `tools/rosetta/source/src/basic/options/options_rosetta.py:5975-6070+` (`Option_Group('enzdes', ...)` — all `enzdes::*` flags, defaults, and descriptions cited above, including the "very experimental at this point" `remodel_secmatch` note)
- Enzyme design success-rate and directed-evolution figures (Kemp eliminase HG3→HG4, retro-aldolase >4,400-fold evolution boost, GH10/PLL design success rates ~49%/21%): via WebSearch, Baker lab publications (nature.com/articles/s41467-018-05205-5, nchembio.1276, and related enzyme-design literature) — not independently re-derived from primary sources, cited as reported.
