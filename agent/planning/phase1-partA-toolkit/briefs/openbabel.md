# Open Babel

**One-line identity.** A GPL-2.0 chemical-format-conversion toolbox ("speak the many languages of chemical data") whose one genuinely load-bearing capability for this project is pH-dependent protonation and PDBQT export that RDKit does not natively provide.

## Identity
- **Version / release examined:** no refcode present in `<workspace>/impress-a-refcodes/tools/` — Open Babel is **not vendored in this repo**; everything below is from upstream docs/search, not a local read. Current stable line per upstream docs is the 3.x series (`open-babel.readthedocs.io`, 3.0.1/3.1.x docs examined).
- **Provenance:** openbabel.org / `openbabel/openbabel` on GitHub, community project (originated from the Babel format-conversion tool). **License: GPL v2.0** — this is copyleft, not permissive; a hard architectural fact, not a detail (see Deployment section).
- **Maturity:** production/mature, long-lived (originally released mid-2000s), broad adoption as the field's default format-swiss-army-knife; actively maintained on GitHub.

## Scientific role
Supports **small-molecule binding** and **enzyme/catalytic design** exclusively as a **format-interconversion and ligand-preparation** utility — it does not itself predict structure, dock, or score. Pipeline stage: **I/O / prepare**, sitting between "I have a ligand from somewhere" (PubChem, a SMILES the agent generated, an SDF from a vendor) and "I have exactly the file format and protonation state the next tool needs" (PDBQT for Vina, protonated SDF for a force field).

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, binary `obabel`. Canonical form: `obabel input.smi -O output.sdf --gen3d --p 7.4` (generates 3D coordinates and protonates for pH 7.4 in one call). Also has a Python binding (`pybel`/`openbabel.pybel`) for in-process use, and a C++ API.
- **Inputs:** any of ~108 readable formats (SMILES, SDF, MOL2, PDB, InChI, CIF, and many quantum-chemistry program formats).
- **Outputs:** any of ~107 writable formats, including **PDBQT** — the AutoDock/Vina-family input format that RDKit cannot write natively (see `cheminformatics-io.md` for the format-decision detail).
- **A concrete example** (from upstream CLI docs, `open-babel.readthedocs.io/en/latest/Command-line_tools/babel.html`):
```
obabel input.smi -O output.sdf --gen3d --p 7.4
```
generates 3D coordinates and adds hydrogens appropriate for neutral physiological pH in a single pipeline stage.

## Compute pattern
- **Pattern:** **P6 (primary)** — a single-molecule format conversion or protonation call is sub-second CLI/library work, same scheduling class as an RDKit call. **P2 (secondary)** for batch conversion of large ligand libraries (thousands of files), which is embarrassingly parallel and can legitimately be fanned out across cores.
- **GPU vendor portability:** CPU-only / n/a. No GPU code path exists or is relevant to what this tool does.
- **State model:** stateless.
- **Data locality:** self-contained per call; streams from stdin/stdout or single files, no shared-FS requirement beyond the input/output files themselves.
- **Staging burden:** none (no model weights, no reference database — though some substructure/fragment operations use small bundled data tables).
- **Container availability:** community (widely packaged: conda-forge `openbabel`, Debian/Ubuntu `openbabel` package, Docker images from various academic groups). No first-party official container found.

## Deployment on DOE & ACCESS
Trivial across every platform — CPU-only, no vendor GPU dependency, so Frontier/Aurora/Polaris/ACCESS all run the identical conda-forge `openbabel` build. Module or conda are both viable; Apptainer wrapping either is equally fine. **The one deployment-relevant fact is the GPL-2.0 license**: unlike RDKit (BSD) or Vina (Apache-2.0), GPL-2.0 has copyleft implications if Open Babel code is linked into a distributed derivative work — irrelevant for this project's use pattern (calling the `obabel` CLI binary as a subprocess, not linking its library into a compiled product), but worth flagging explicitly if any future integration considers embedding Open Babel's C++ library directly rather than shelling out to the CLI. This same GPL dependency is why GNINA (see `docking.md`) is dual-licensed GPL/Apache depending on whether Open Babel is compiled in.

## Agentic surface
- **Native MCP:** no. No Open Babel-specific MCP server (official or community) found in search.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `-p <pH>` | float | 0-14, physiological default 7.4 | none (must be requested) | Sets target pH for protonation state; wrong pH silently produces the wrong charge state for a ligand headed into docking or MD |
| `--gen3d` | flag | on/off | off | Generates 3D coordinates from a 2D/SMILES input via Open Babel's own conformer generator — a weaker generator than RDKit's ETKDG; prefer RDKit for 3D generation and use Open Babel only for the format/protonation step it's actually good at |
| `--partialcharge <method>` | enum (`gasteiger`, `mmff94`, `eem`, etc.) | n/a | `gasteiger` (fast, approximate) | Cheap heuristic charges vs. more expensive/accurate methods; Gasteiger charges are not a substitute for QM-derived charges (see `ligand-parameterization.md`) and should not be trusted for anything quantitative |

- **Parameters that must NOT be agent-varied:** `-h` (add-all-hydrogens, pH-independent) must never be silently substituted for `-p <pH>` — the two produce different protonation states and the agent must track which one was used, since downstream affinity/docking results are only meaningful if the protonation state matches the intended physiological condition. `--gen3d`'s conformer should not be used as the final geometry for anything that will be scored (see Failure modes).

## Failure modes & what the agent must check
- **Loud failure:** unreadable/corrupt input file, unsupported format pair — non-zero exit, stderr message.
- **Silent bad output (protonation):** a community-reported GitHub issue (`openbabel/openbabel#2677`, "Adding hydrogens with -p messes up the entire structure") documents cases where `-p` corrupts more than intended (residue numbering/naming, not just missing hydrogens) on certain inputs — the agent should **not assume `-p` output is correct by default**; a post-hoc check (heavy-atom count and total formal charge before/after) is cheap insurance. A second issue (`openbabel/openbabel#162`, "Need more generic protonation/pKa rules") documents that Open Babel's pKa rule set is limited/heuristic, not a rigorous pKa predictor — treat `-p 7.4` output as "plausible default protonation," not "correct microstate," especially for less-common functional groups.
- **Silent bad output (geometry quality):** `--gen3d` conformers are not run through the same ETKDG+torsion-correction pipeline RDKit uses; geometries can be strained. The agent should prefer RDKit `AllChem.EmbedMolecule`/ETKDGv3 for anything that needs a trustworthy 3D structure and reserve Open Babel's `--gen3d` for quick-and-dirty cases only.
- **Specific checks:** compare atom/heavy-atom counts and net formal charge before and after any `-p`/`-h` call; for PDBQT export specifically, verify the output still parses as a valid ligand in the receiving tool (e.g., re-read with RDKit or check Vina/Meeko accepts it without warning) before trusting it downstream.

## Cost per unit of work
- **Unit of work:** one format conversion or one protonation call on a single small molecule: low tens of milliseconds to ~1 second depending on operation (`--gen3d` is the slowest single step). (Approximate; not independently benchmarked here.)
- **Resource shape:** single CPU core per call; batch conversion parallelizes trivially across cores/nodes (P2 fan-out) since each file is independent.
- **Checkpointable:** n/a at single-call granularity (stateless, cheap to re-run); batch jobs should write outputs incrementally so a partial batch is not lost.

## Verdict
**Recommended**, not Core, and the brief should say plainly why: **against RDKit, Open Babel genuinely adds two things and duplicates the rest.** It genuinely adds (1) broader raw format coverage — ~108 readable/107 writable formats versus RDKit's narrower native set, which matters when an upstream source hands the agent a format RDKit doesn't read directly, and (2) `-p <pH>` pH-dependent protonation, which RDKit has no native equivalent for (RDKit's `AddHs` adds all hydrogens unconditionally, pH-independent — confirmed via `rdkit/rdkit` GitHub discussion #4078, "pH-dependent protonation"). Everything else in Open Babel's surface — SMILES parsing, basic 3D generation, descriptor-adjacent calculations — is either duplicated by RDKit or done *better* by RDKit (ETKDG conformers are the stronger generator; RDKit's sanitization/valence model is stricter). The practical recommendation for this project: **use RDKit as the default cheminformatics engine, and shell out to Open Babel specifically for (a) `-p` protonation-state assignment and (b) PDBQT export**, not as a general-purpose replacement. GPL-2.0 licensing is a non-blocking but real consideration if any future component considers linking rather than subprocess-calling it.

## Sources
- No refcode in `<workspace>/impress-a-refcodes/tools/` — Open Babel is not vendored in this project; all claims below are from upstream sources, marked as such.
- [Open Babel CLI docs](https://open-babel.readthedocs.io/en/latest/Command-line_tools/babel.html) — `-p`/`-h` semantics, example command
- [Open Babel Supported File Formats](https://open-babel.readthedocs.io/en/latest/FileFormats/Overview.html) — format count (~108 read / ~107 write)
- [openbabel/openbabel GitHub](https://github.com/openbabel/openbabel) — license (GPL v2.0), project status
- [openbabel/openbabel#2677](https://github.com/openbabel/openbabel/issues/2677) — `-p` structure-corruption report
- [openbabel/openbabel#162](https://github.com/openbabel/openbabel/issues/162) — pKa rule generality issue
- [rdkit/rdkit discussion #4078](https://github.com/rdkit/rdkit/discussions/4078) — RDKit's lack of native pH-dependent protonation, cited for the RDKit-vs-OpenBabel comparison
- GNINA license note (GPL/Apache dual-license driven by optional Open Babel linkage) cross-referenced from `docking.md` research pass, source: [gnina/gnina LICENSE.GNU](https://github.com/gnina/gnina/blob/master/LICENSE.GNU)
