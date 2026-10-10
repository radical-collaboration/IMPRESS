# Ligand Parameterization: Rosetta `.params`, Antechamber/GAFF, OpenFF + Espaloma, CCD Codes

**One-line identity.** The step that turns "a small molecule" into "a thing a force field or Rosetta can score" — four different routes to the same destination, and the most underrated silent-failure point in this entire toolkit's small-molecule work.

## Rosetta `.params` generation (`molfile_to_params.py`)

### Identity
- **Version / release examined:** `impress-a-refcodes/tools/rosetta/source/scripts/python/public/molfile_to_params.py` (docstring lines 1-14, option parser lines ~1387-1500), plus `batch_molfile_to_params.py` and the polymer variant `molfile_to_params_polymer.py` in the same directory. Ships as part of the Rosetta source tree, not a standalone package.
- **Provenance:** Rosetta Commons; same license as core Rosetta (academic-free / commercial-licensed dual model — see `rosetta.md`). Author credited in-file: Ian W. Davis.
- **Maturity:** production — this is the tool essentially every published Rosetta ligand-docking/enzyme-design paper's `.params` file traces back to.

### Scientific role
Converts an MDL Molfile/SDF/MOL2 ligand into one or more Rosetta `.params` residue-type definitions plus a matching `.pdb` template — the input format Rosetta's `fa_standard` and centroid score functions require to treat a small molecule as a scoreable residue type. Serves **enzyme/catalytic design** and **small-molecule binding** exclusively; irrelevant to stability or de novo binder design unless those campaigns incidentally touch a cofactor or crystallization additive. Pipeline stage: **prepare / I-O**, sitting between "I have a 3D ligand structure" and "Rosetta can score it."

### Invocation & I/O contract
- **CLI:** `python molfile_to_params.py [flags] INPUT.mol` (also accepts `.sdf`/`.mol2`). Key flags verified in-file: `-n/--name` (residue name, default `LG`), `--chain` (PDB chain letter, default `X`), `--root_atom`/`--nbr_atom` (manual override of automatically-chosen tree root / neighbor atom, 1-indexed), `--recharge CHG` ("ignore existing partial charges, setting total charge to CHG"), `--keep-names` ("leaves atom names untouched except for duplications" — off by default), `-a/--amino-acid` (noncanonical-residue mode, implies `--keep-names`), `--clobber`, `--no-param`/`--no-pdb` (debug-only skips), `-m/--max-confs` (proton-chi rotamer expansion cap, default 5000).
- **Inputs:** a molfile/SDF/MOL2 with 3D coordinates and **explicit hydrogens already placed in the intended protonation state** — the script does not compute or verify pKa/protonation itself.
- **Outputs:** `NAME.params` (Rosetta residue-type definition: `ATOM` lines with Rosetta atom types and partial charges, `BOND` connectivity, `CHI`/`PROTON_CHI` rotatable-bond definitions, `NBR_ATOM`/`NBR_RADIUS`, `ICOOR_INTERNAL` internal coordinates) and `NAME.pdb` (a matching coordinate template).
- **A concrete example (verified in refcode):** `impress-a-refcodes/tools/IMPRESS/examples/small_molecule_binding/p1_in/ALR.params` — a real, generated params file for a bis-sulfonamide ligand (`AA UNK`, 43 heavy+H atoms, 7 `CHI` entries with one `PROTON_CHI` hydroxyl rotamer sampled at `SAMPLES 3 60 -60 180 EXTRA 1 20`, full `ICOOR_INTERNAL` tree). This is exactly the artifact `molfile_to_params.py` produces and exactly what `rosetta-enzyme-design.md` (already written) consumes downstream.

### Compute pattern
- **Pattern:** P6. A single ligand's params generation is a pure-Python script over one small molecule — sub-second to low seconds even with proton-chi rotamer expansion. Never schedule a single invocation as a job; batch generation across a compound library (`batch_molfile_to_params.py`) is P2 fan-out.
- **GPU vendor portability:** CPU-only / n/a.
- **State model:** stateless.
- **Data locality:** self-contained (one molfile in, `.params`+`.pdb` out).
- **Staging burden:** none — ships inside the Rosetta source tree already required for every other Rosetta tool in this toolkit.
- **Container availability:** n/a beyond whatever container already carries Rosetta/PyRosetta.

### Deployment on DOE & ACCESS
No independent deployment question — it rides inside the Rosetta install already required by `rosetta.md`, `pyrosetta.md`, `rosetta-enzyme-design.md`, `rosetta-ddg.md`. Requires `rosetta_py` on `PYTHONPATH` (the script self-appends its own parent-parent directory, so it must be run from inside a checked-out Rosetta source tree or an equivalent layout). Portable everywhere Rosetta is, since it is CPU-only Python.

## Antechamber / GAFF

### Identity
- **Version / release examined:** not vendored in `impress-a-refcodes/tools/` — AmberTools' `antechamber` binary is referenced only indirectly, via GROMACS's own documentation: `impress-a-refcodes/tools/gromacs/docs/user-guide/force-fields.rst:31-38` ("ANTECHAMBER/GAFF … available either together with AMBER, or through the antechamber package, which is also distributed separately") and `impress-a-refcodes/tools/gromacs/docs/user-guide/system-preparation.rst:60-64` (listing `antechamber`/`acpype` as the recommended route to a ligand topology "For the AMBER force fields"). Upstream: AmberTools, `ambermd.org/antechamber`.
- **Provenance:** AmberTools has been distributed free of the older restrictive Amber license since AmberTools16 (2016) — the MD engine (`pmemd`) is the part that retains commercial licensing, not AmberTools/antechamber (general public knowledge, not independently re-verified against current license text in this pass — flagged as inferred).
- **Maturity:** production, the AMBER-ecosystem default for ~two decades.

### Scientific role
Assigns GAFF (Generalized Amber Force Field) atom types via bond-perception heuristics, then AM1-BCC (or RESP) partial charges, to an arbitrary small molecule — the standard route to an AMBER-compatible ligand topology for **small-molecule binding** MD (GROMACS/OpenMM, both covered elsewhere in this toolkit) and, less commonly, a cross-check source for Rosetta ligand charges. Pipeline stage: **prepare**.

### Invocation & I/O contract
- **CLI:** `antechamber -i ligand.mol2 -fi mol2 -o ligand.prepi -fo prepi -c bcc -nc 0` (AM1-BCC charges, net charge 0) is the canonical pattern; `parmchk2 -i ligand.prepi -f prepi -o ligand.frcmod` fills in any missing bond/angle/torsion parameters against the GAFF parameter library, flagging gaps with `ATTN` comments in the output `.frcmod` (see Failure modes).
- **Inputs:** MOL2/PDB/SDF with a defined net formal charge (`-nc`) and correct protonation already in place.
- **Outputs:** `.prepi`/`.mol2` (GAFF-typed topology) plus `.frcmod` (any parameters not already in the base GAFF library).
- **A concrete example** (from the GROMACS docs cited above): "There are scripts available for converting AMBER systems (set up, for example, with GAFF) to GROMACS (`amb2gmx.pl`, or ACPYPE)" — i.e. antechamber/GAFF output is not directly GROMACS-native and needs a conversion step (`acpype`) before it reaches `gmx`.

### Compute pattern
- **Pattern:** P6 (single-molecule bond-perception + AM1-BCC charge assignment is seconds, CPU-only). P2 for library-scale batches.
- **GPU vendor portability:** CPU-only / n/a.
- **State model:** stateless. **Data locality:** self-contained. **Staging burden:** none beyond the AmberTools install itself (small parameter-library files, not a large database). **Container availability:** community (conda-forge `ambertools`).

### Deployment on DOE & ACCESS
CPU-only, conda-installable identically on Frontier/Aurora/Polaris/ACCESS. No GPU-portability question. The one deployment nuance: `acpype` (or an equivalent hand conversion) is a required extra step before GAFF output is usable by GROMACS — budget it as part of the same prep stage, not an afterthought.

## OpenFF Toolkit + Espaloma

### Identity
- **Version / release examined:** not vendored in refcodes; web-sourced. OpenFF Toolkit (`openforcefield/openff-toolkit`), MIT license, Open Force Field Initiative. Espaloma / EspalomaCharge (`choderalab/espaloma`, `openforcefield/espaloma-charge`), MIT license; current production force field is **espaloma-0.3.x**, described in Wang et al., *"Machine-learned molecular mechanics force field for the simulation of protein-ligand systems and beyond"* (arXiv:2307.07085) and deployed via `docs.espaloma.org/en/stable/deploy.html`.
- **Provenance:** Open Force Field Consortium (academic/industry consortium, Chodera lab and collaborators at MSKCC and elsewhere).
- **Maturity:** active research/production-adjacent — OpenFF's "Sage" (2.x) line is used in production free-energy pipelines; Espaloma is newer (GNN-based) but already integrated as an `openmmforcefields`-installable backend and as an OpenFF Toolkit `ToolkitWrapper` for charge assignment.

### Scientific role
**OpenFF Toolkit** assigns SMIRNOFF-format force-field parameters by **direct chemical perception** — SMIRKS substructure patterns matched straight against the molecular graph — rather than atom-typing-then-library-lookup (GAFF's approach). **Espaloma** replaces the parameter-assignment step itself with a graph neural network trained to predict bonded parameters and partial charges directly, self-consistently across proteins, small molecules, and RNA (per the Open Force Field Initiative's own science update on espaloma-0.3). Both feed **small-molecule binding** MD (GROMACS/OpenMM); EspalomaCharge specifically is also usable as a fast partial-charge-only assignment method (comparable to Antechamber/AM1-BCC in accuracy per its own benchmarking against AmberTools/OpenEye, per arXiv:2302.06758). Pipeline stage: **prepare**.

### Invocation & I/O contract
- **Python API (OpenFF Toolkit):** `from openff.toolkit import Molecule, ForceField; mol = Molecule.from_smiles(smiles); ff = ForceField("openff-2.x.x.offxml"); interchange = ff.create_interchange(mol.to_topology())`, exported to any MD engine via `openff-interchange`.
- **Python API (EspalomaCharge, via OpenFF ToolkitWrapper):** `from openff.toolkit.utils.toolkits import EspalomaChargeToolkitWrapper` — registered as a drop-in charge-assignment backend, callable wherever OpenFF Toolkit would otherwise call AM1-BCC.
- **Inputs:** SMILES, SDF, or an RDKit/OpenEye `Mol` object with defined protonation/stereochemistry already resolved by the caller — like every tool in this brief, OpenFF/Espaloma parameterize *whatever molecule they are handed*, they do not independently validate it.
- **Outputs:** an `Interchange`/OpenMM `System` object (in-process) or exported topology/parameter files, depending on the target MD engine.

### Compute pattern
- **Pattern:** P6 — SMIRKS matching and GNN forward-pass parameter prediction are both sub-second, single-molecule, in-process operations (Espaloma's GNN is small enough to run on CPU; GPU is an optional speed-up, not a requirement).
- **GPU vendor portability:** CPU-only viable / GPU optional (PyTorch backend for Espaloma — same CUDA-primary, HIP/XPU-unverified posture as other PyTorch tools in this toolkit, but irrelevant at this problem size).
- **State model:** stateless. **Data locality:** self-contained. **Staging burden:** OpenFF force-field `.offxml` files and the Espaloma model checkpoint (small, low-hundreds-of-MB class, not independently measured here). **Container availability:** community (conda-forge `openff-toolkit`, PyPI `espaloma`/`espaloma-charge`).

### Deployment on DOE & ACCESS
No platform blocker — pure Python + small PyTorch model, installs via conda/pip identically everywhere. This is the most portable of the three non-Rosetta routes precisely because SMIRKS-based/GNN-based parameter assignment carries no compiled, vendor-coupled backend the way a full MD engine does.

## CCD codes (Boltz/Chai/RFD3 ligand identity)

### Identity
- **Provenance:** the wwPDB **Chemical Component Dictionary** — a curated registry of ~40,000 three/five-letter codes (e.g. `SAH`, `ATP`, `HEM`), each mapping to a fixed reference molecular graph, atom names, bond orders, and formal charges, maintained centrally by the PDB.
- **Verified locally:** `impress-a-refcodes/tools/boltz/scripts/process/ccd.py` builds Boltz's local CCD cache using `pdbeccdutils.core.ccd_reader.read_pdb_components_file`, then RDKit ETKDGv3 + UFF to generate 3D conformers per component (`compute_3d`, lines ~46-80). `impress-a-refcodes/tools/boltz/examples/ligand.yaml:7-9` shows the literal input syntax: `ligand: {id: [C, D], ccd: SAH}` alongside `ligand: {id: [E, F], smiles: 'N[C@@H](Cc1ccc(O)cc1)C(=O)O'}` for the same schema — i.e. Boltz's own YAML input format accepts **either** a CCD code **or** a SMILES string per ligand entry, never both (`schema.py:1029-1030`: `assert "smiles" in item or "ccd" in item; assert not both`). RFdiffusion3's own input spec also takes ligands "as CCD codes" per `rfdiffusion3.md:24`.
- **Maturity:** the CCD itself is production/canonical (it *is* the PDB's own controlled vocabulary); `pdbeccdutils` (EBI-maintained) is the standard reader.

### Scientific role
CCD codes are the **identity/naming layer**, not a parameterization method in themselves — but they resolve directly to a fixed, unambiguous reference structure (correct connectivity, correct formal protonation state as deposited, correct atom names), which is exactly what a bare SMILES string does not guarantee (see `cheminformatics-io.md` for the full CCD-vs-SMILES decision). Relevant to **enzyme/catalytic design** (natural cofactors — SAH, NAD, heme — are almost always specified by CCD code, not re-derived from SMILES) and **small-molecule binding** (novel candidate ligands are almost always SMILES, since they have no CCD entry). Pipeline stage: **prepare / identity resolution**, feeding directly into Boltz/Chai/RFD3's own internal parameterization (each model computes its own 3D conformer and internal feature representation from either input type — CCD lookup vs. RDKit-from-SMILES — the co-folding models handle this step themselves, unlike Rosetta/GAFF/OpenFF which require it as an explicit upstream step).

### Invocation & I/O contract
- **Not a separate tool call** — it is a field value (`ccd: <code>`) in Boltz's/RFD3's own YAML/JSON input schema, resolved internally against a locally-staged CCD pickle (`ccd.pkl`, ~0.3 GB per `boltz.md:38`) rather than a live network fetch at inference time.
- **Inputs:** a 3-5 character CCD code string.
- **Outputs:** internally, an RDKit `Mol` with a computed 3D conformer (via the same ETKDGv3+UFF pattern documented in `rdkit.md`).

### Compute pattern
- **Pattern:** P6 (dictionary lookup against a locally-cached pickle, sub-millisecond) once the CCD cache is staged. The one-time cache build/staging (`ccd.py`'s conformer-generation pass over the entire dictionary) is a P2-shaped batch job run once at toolkit setup, not per-inference.
- **GPU vendor portability:** n/a. **State model:** stateless per lookup. **Data locality:** shared-FS for the cache file. **Staging burden:** the CCD pickle itself (~0.3 GB, bundled with Boltz's cache per `boltz.md`). **Container availability:** ships as part of whatever container carries Boltz/Chai/RFD3.

### Deployment on DOE & ACCESS
No independent deployment question — piggybacks entirely on whichever co-folding model's own staging step is already required (`boltz.md`, `chai.md`, `rfdiffusion3.md`).

## Agentic surface
- **Native MCP:** no, for all four routes — none of `molfile_to_params.py`, Antechamber/GAFF, OpenFF/Espaloma, or CCD lookup has a dedicated MCP server (community or official). All are called via direct CLI/Python invocation from the agent's own process or a co-located worker, consistent with P6 discipline elsewhere in this toolkit (`rdkit.md`'s "an MCP wrapper is the wrong integration point" argument applies identically here).
- **Parameters worth exposing for autonomous variation:**

| Parameter | Tool | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|---|
| target pH | all (upstream protonation step, not the parameterizer itself) | float | 5.0-9.0 | 7.4 | See structure-prep.md; must be identical across every stage that touches the same ligand |
| `--recharge CHG` | `molfile_to_params.py` | int | ligand's true net formal charge | unset (use existing molfile charges) | Silent override — see Failure modes #3; should be **set explicitly and asserted**, never left to whatever the upstream molfile happened to encode |
| `-c bcc` vs `-c resp` | Antechamber | enum | n/a | `bcc` (AM1-BCC) | AM1-BCC is fast/good-enough for screening; RESP is slower and more rigorous, worth reserving for a final validated ligand, not every candidate in a search |
| force-field version (`openff-2.x.x.offxml` vs `espaloma-0.3.x`) | OpenFF/Espaloma | string | n/a | pin per campaign | Must be held fixed across a campaign — comparing binding energies computed under different force-field versions is not a valid comparison |
| `ccd` vs `smiles` | Boltz/Chai/RFD3 input | choice | n/a | prefer `ccd` when a code exists | The load-bearing decision covered in depth in `cheminformatics-io.md` |

- **Parameters that must NOT be agent-varied:** `--recharge` must never be silently defaulted or auto-guessed by the agent — it must be derived from an explicit net-charge computation on the *already-protonated* input molecule (e.g. `Chem.GetFormalCharge(mol)` post-sanitization) and asserted equal to whatever value is passed, or omitted entirely and the input molfile's own charges trusted and logged. GAFF/OpenFF force-field family and version must be pinned per campaign, not chosen per-ligand — mixing force fields across a comparison set silently invalidates energy comparisons (the same principle `rdkit.md` states for MMFF vs. UFF).

## Failure modes & what the agent must check

**This is the center of gravity of this brief.** Every tool covered above shares one property: **none of them independently validates the chemistry of what they are handed.** They are all, by design, faithful-but-uncritical converters — given a molfile/SMILES/CCD code, they produce a complete, internally consistent, loudly-nothing-wrong output artifact regardless of whether the *input* encoded the chemically correct molecule for the problem at hand. An agent that treats "the params/topology file generated without error" as evidence of correctness is making a category error, and the consequence is concrete: **a wrongly-parameterized ligand fed into a Rosetta enzyme-design run or a Boltz-2 affinity campaign produces a full batch of scored, ranked, plausible-looking designs — and every one of them is scored against the wrong chemistry.** Nothing in the pipeline downstream (Rosetta's score function, Boltz's affinity head, an MD trajectory's RMSD) has any way to detect that the ligand it was handed wasn't the one the campaign intended; the agent will report high-confidence "successful" designs, rank them, and potentially advance them to the next campaign stage, and the error surfaces — if it ever does — only at wet-lab validation, by which point the entire compute budget spent on that ligand across every design iteration was spent scoring the wrong molecule.

The six-item failure taxonomy:

1. **Wrong protonation state at physiological pH.**
   - *Manifests as:* a carboxylic acid encoded as neutral -COOH instead of ionized -COO⁻, or a basic amine as neutral -NH₂ instead of protonated -NH₃⁺, at the pH the design is meant to represent.
   - *Why it does not throw an error:* every tool in this brief accepts whatever explicit hydrogens are already present in the input structure. RDKit's sanitizer, Antechamber's bond perception, and `molfile_to_params.py` all validate valence/connectivity, not physiological relevance — a wrong-but-internally-consistent protonation state parses, embeds a valid 3D conformer, gets valid partial charges, and produces a complete `.params`/topology file with zero warnings.
   - *The check that catches it:* compute the net formal charge and per-titratable-group ionization state programmatically (`Chem.GetFormalCharge`, or a dedicated predictor — Dimorphite-DL, OpenBabel `-p <pH>` per `openbabel.md`) and diff against the expected state for the design's target pH; log the assumed protonation state as explicit campaign metadata, the same discipline `structure-prep.md` mandates for protein titratable residues, extended to the ligand.

2. **Wrong tautomer.**
   - *Manifests as:* a keto/enol pair, or an imidazole/heterocycle N-H tautomer, that shares the same molecular formula and often the same naive SMILES atom count but represents a chemically distinct molecule — particularly consequential for catalytic ligands where the reactive tautomer *is* the mechanistic hypothesis.
   - *Why it does not throw an error:* RDKit's default sanitizer does not canonicalize tautomers unless `rdMolStandardize.TautomerEnumerator` is explicitly invoked; two different tautomer SMILES for "the same" compound parse, embed, and parameterize independently and successfully as two different, individually valid molecules.
   - *The check that catches it:* explicitly run tautomer canonicalization (`rdMolStandardize.TautomerEnumerator().Canonicalize`) and compare the result against the intended tautomer before parameterization; for catalytically relevant ligands, cross-check against the stated mechanistic hypothesis rather than trusting whichever tautomer an upstream source (PubChem, a generative model's SMILES output) happened to emit.

3. **Wrong formal charge.**
   - *Manifests as:* `molfile_to_params.py`'s own `--recharge CHG` flag is a direct silent-override mechanism ("ignore existing partial charges, setting total charge to CHG"); an agent (or a copy-pasted default) that passes the wrong integer, or that omits the flag while the ambient molfile charges were never correct, gets a fully generated `.params` file with no complaint.
   - *Why it does not throw an error:* the script's job is to encode whatever charge it is told (or whatever is already present) — it has no independent notion of "correct" net charge for a given ligand at a given pH.
   - *The check that catches it:* sum the atom partial charges in the generated `.params` `ATOM` lines (or the equivalent in a GAFF/OpenFF topology) and assert the total matches the intended net formal charge; run this as an automated post-generation gate on every ligand, not a manual spot-check.

4. **Wrong stereochemistry.**
   - *Manifests as:* an unspecified or inverted stereocenter (`@` vs `@@`, or a missing wedge/hash in a 2D source structure) — connectivity and valence are identical, so bond-order sanitization passes cleanly; the resulting 3D conformer is a real, physically valid molecule, just the wrong enantiomer or diastereomer, which can bind a chiral active site with completely different (or zero) affinity.
   - *Why it does not throw an error:* none of `MolFromSmiles`, Open Babel, Antechamber, or `molfile_to_params.py` validates stereochemistry against an external "correct" reference — there is no such reference available to the tool; a stereo-flipped molecule is entirely self-consistent on its own terms.
   - *The check that catches it:* `useChirality=True` on any substructure/identity comparison against the intended reference (the same flagged parameter in `rdkit.md`); for CCD-specified ligands, verify the fetched component's stereo descriptors match intent before parameterization; enumerate stereoisomers explicitly (`EnumerateStereoisomers`) rather than accepting RDKit's arbitrary default assignment when a source structure leaves a center unspecified.

5. **Missing / guessed torsion parameters.**
   - *Manifests as:* Antechamber/GAFF's `parmchk2` step fills any chemical environment not covered by the GAFF parameter library with a generic substitute and flags it with an `ATTN`/"needs revision" comment inside the generated `.frcmod` file; OpenFF's SMIRKS-based assignment falls back to the broadest matching (least-specific) pattern when no precise match exists — also silent. In Rosetta, the analogous risk is a badly chosen `--root_atom`/`--nbr_atom` or default `CHI`/`PROTON_CHI` definition producing rotamer sampling that never actually covers the ligand's true low-energy conformers.
   - *Why it does not throw an error:* in every case the tool's job is to *always produce a complete parameter set* — a guessed or generic fallback parameter is a completed, not a missing, entry, and none of these pipelines treat "generic fallback used" as failure by default.
   - *The check that catches it:* grep every generated `.frcmod` for `ATTN`/"guessed" flags as a hard pipeline gate (not optional — this is exactly the kind of comment automated pipelines are known to never parse); for OpenFF, use the toolkit's own parameter-assignment provenance (which SMIRKS pattern matched each term) to flag wildcard/generic matches; for Rosetta, compare the generated `CHI` line count against RDKit's `rdMolDescriptors.CalcNumRotatableBonds` on the same molecule and treat a mismatch as a correctness bug.

6. **Mismatched atom naming between the ligand definition and the structure file.**
   - *Manifests as:* atom names in a `.params`/`.prepi`/topology file don't exactly match the atom names in the PDB/complex structure the ligand is meant to sit inside — common when a ligand was renamed/renumbered by a generative model, or when a format-conversion tool silently reassigns atom names on write (this is exactly why `molfile_to_params.py` has a `--keep-names` flag in the first place: the default behavior does **not** preserve input atom names).
   - *Why it does not throw an error:* Rosetta and most MD loaders match atoms by name+residue when loading a complex; an unmatched name (especially a hydrogen) is often silently dropped as absent rather than raising — the structure loads, scores, and simulates with a silently incomplete or mistyped ligand.
   - *The check that catches it:* programmatically diff the atom-name set in the parameter/topology file against the atom-name set in the actual structure/complex file before any design or MD job runs on it; treat any non-empty symmetric difference as a hard failure.

**Scope note on problem classes:** ligand parameterization is load-bearing for **enzyme/catalytic design** and **small-molecule binding** — both require a small molecule to be scored, docked, or simulated with a specific, correct chemistry. It is **not** relevant to stability/thermostabilization or de novo binder design in their pure protein-only form; those problem classes never construct a `.params`/GAFF/OpenFF artifact unless a campaign incidentally involves a cofactor, in which case it inherits this brief's failure modes.

## Cost per unit of work
- **`molfile_to_params.py`:** sub-second to a few seconds per ligand (proton-chi rotamer expansion can push this to several seconds for flexible ligands near the `--max-confs` cap). Single CPU core.
- **Antechamber + parmchk2:** low seconds per ligand (AM1-BCC semi-empirical charge calculation dominates). Single CPU core.
- **OpenFF Toolkit parameter assignment / EspalomaCharge:** sub-second (SMIRKS matching) to low seconds (GNN forward pass) per ligand. Single CPU core sufficient; GPU optional.
- **CCD lookup:** sub-millisecond once the cache is staged.
- **Checkpointable:** n/a at single-ligand granularity — all are stateless, atomic, cheap-to-rerun calls; batch runs across a compound library should write outputs incrementally (P2-level checkpointing, not per-call).

## Verdict
**Core.** Every enzyme-design and small-molecule-binding campaign in this toolkit's scope eventually needs at least one of these four routes, and the brief's own research converges on one clear operational finding: **the danger here is not that these tools fail — it is that they never fail when they should.** Rosetta `.params` generation is mandatory for any Rosetta-side enzyme design or ligand docking (`rosetta-enzyme-design.md`); Antechamber/GAFF or OpenFF/Espaloma is mandatory for any MD-side small-molecule work (`gromacs.md`, `openmm.md`); CCD-code resolution is mandatory whenever a co-folding model (`boltz.md`, `chai.md`, `rfdiffusion3.md`) needs to specify a natural cofactor unambiguously. The concrete, load-bearing recommendation for the agent architecture: **treat the six-item failure taxonomy above as a mandatory automated gate between ligand parameterization and every downstream design/scoring/simulation step**, not as documentation to consult after something looks wrong — because nothing will look wrong until it is far too late and far too expensive to matter.

## Sources
- `impress-a-refcodes/tools/rosetta/source/scripts/python/public/molfile_to_params.py` (docstring, option parser lines ~1387-1500)
- `impress-a-refcodes/tools/rosetta/source/scripts/python/public/batch_molfile_to_params.py`, `molfile_to_params_polymer.py`
- `impress-a-refcodes/tools/IMPRESS/examples/small_molecule_binding/p1_in/ALR.params`, `IND.params`, `RED.params` (real generated `.params` artifacts)
- `impress-a-refcodes/tools/gromacs/docs/user-guide/force-fields.rst:31-38`, `system-preparation.rst:55-65` (Antechamber/GAFF, acpype)
- `impress-a-refcodes/tools/boltz/scripts/process/ccd.py`, `impress-a-refcodes/tools/boltz/examples/ligand.yaml:7-12`, `impress-a-refcodes/tools/boltz/src/boltz/data/parse/schema.py:1029-1030` (CCD-vs-SMILES schema, verified in refcode)
- `docs/phase1-partA-toolkit/briefs/rosetta-enzyme-design.md`, `boltz.md`, `rdkit.md`, `openbabel.md`, `structure-prep.md` (read this session, cross-referenced to avoid duplication)
- [OpenFF Toolkit](https://github.com/openforcefield/openff-toolkit), MIT license — web-sourced, not in refcodes
- [EspalomaCharge: Machine learning-enabled ultra-fast partial charge assignment, arXiv:2302.06758](https://arxiv.org/pdf/2302.06758)
- [Self-consistently simulating small molecules, proteins and RNAs with the "espaloma-0.3" force field — OpenFF science update](https://openforcefield.org/community/news/science-updates/espaloma-03/)
- [Espaloma-0.3.0 paper, arXiv:2307.07085](https://arxiv.org/pdf/2307.07085)
- [Espaloma deployment docs](https://docs.espaloma.org/en/stable/deploy.html)
- [Reproducibility, validation, and failure modes across classical and AI-driven molecular docking, J. Comput.-Aided Mol. Des. 2026](https://link.springer.com/article/10.1007/s10822-026-00849-8) — general ligand-state-ambiguity/reproducibility framing
- Brink & Exner, "Influence of Protonation, Tautomeric, and Stereoisomeric States on Protein-Ligand Docking Results," *J. Chem. Inf. Model.* 2009, https://pubs.acs.org/doi/10.1021/ci800420z
- Martin, "The Effect of Ligand-Based Tautomer and Protomer Prediction on Structure-Based Virtual Screening," *J. Chem. Inf. Model.* 2009, https://pubs.acs.org/doi/10.1021/ci900364w
- AmberTools free-licensing-since-2016 claim — general knowledge, not independently re-verified against current license text in this pass; flagged as inferred.
