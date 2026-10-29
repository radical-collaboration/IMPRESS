# Cheminformatics I/O: SMILES/InChI Canonicalization, Format Conversion, CCD-vs-SMILES

**One-line identity.** The data-plumbing layer beneath every small-molecule tool in this toolkit — short brief, but format mismatch between two tools that both claim to "handle SMILES" is a constant, silent, Pattern-P6 source of downstream error.

## Identity
- **Version / release examined:** no dedicated refcode — this brief's substance is the *usage pattern* of RDKit (`impress-a-refcodes/tools/rdkit/`, see `rdkit.md`) and Open Babel (see `openbabel.md`) for I/O specifically, plus the concrete CCD-vs-SMILES schema verified in `impress-a-refcodes/tools/boltz/src/boltz/data/parse/schema.py` and `impress-a-refcodes/tools/boltz/examples/ligand.yaml`.
- **Provenance:** RDKit (BSD-3), Open Babel (GPL-2.0) — both already covered as standalone briefs; this brief is the connective-tissue layer between them and every consumer (docking, Rosetta params, co-folding models).
- **Maturity:** production; the underlying format standards (SMILES, InChI, SDF, MOL2, PDBQT, CIF) are decades-stable, but tool-specific *implementations* of "read format X, write format Y" vary in fidelity in exactly the ways this brief documents.

## Scientific role
Not a scientific step in itself — it is the **I/O** pipeline stage that sits between every pair of adjacent tools in a small-molecule workflow: a ligand generated as a SMILES by an LLM/generative source, converted to SDF for RDKit conformer generation, converted to PDBQT for Vina, or resolved to a CCD code for Boltz. Relevant to **enzyme/catalytic design** and **small-molecule binding** wherever two tools in the pipeline disagree on native format (which is most of the time — no two tools in this toolkit share one canonical format). Indirectly relevant to every problem class through structure-file conversion (PDB↔mmCIF, handled by `structure-libraries.md`'s Biotite/BioPython layer, not repeated here).

## Invocation & I/O contract
- **SMILES canonicalization (RDKit):** `Chem.MolToSmiles(Chem.MolFromSmiles(smi), canonical=True)` — round-trips to RDKit's own canonical form; **not** the same canonical string InChI or a different toolkit (OpenBabel, ChemAxon) would produce, because "canonical SMILES" is an algorithm-specific, not standard-mandated, output. Two structurally identical molecules canonicalized by two different toolkits can (and often do) produce different canonical SMILES strings — string equality across toolkits is not a valid identity check; graph/InChI equality is.
- **InChI canonicalization:** `Chem.MolToInchi(mol)` / `Chem.MolFromInchi(inchi)` — InChI **is** a cross-toolkit standard (IUPAC-maintained algorithm, same string from any correct implementation), making it the right choice for **identity/deduplication** checks across tools or across a generative campaign's output, where SMILES is the right choice for **exchange with a specific downstream tool's expected input format**. The InChIKey (a fixed-length hash of the InChI) is the practical form for fast set-membership/deduplication lookups (e.g., "has this campaign already generated this exact ligand before").
- **SDF/MOL2/PDBQT/CIF conversion:** RDKit natively reads/writes SMILES, SDF, MOL/MOL2 (basic); Open Babel is the broader-coverage converter (~108 read / ~107 write formats per `openbabel.md`) and is specifically the tool for **PDBQT** export, which RDKit does not write natively — PDBQT is required by AutoDock Vina/GNINA (`docking.md`) and carries AutoDock-specific atom typing and partial charges that neither RDKit's nor a generic SDF writer's charge model matches without an explicit preparation step (in practice, Meeko — see `docking.md`'s `ChemGraph` example, `docking_core.py:70-97` — sits between RDKit's `Mol` and a valid Vina-ready PDBQT).
- **A concrete example (verified in refcode):** `impress-a-refcodes/tools/boltz/examples/ligand.yaml:7-12` —
  ```yaml
  - ligand:
      id: [C, D]
      ccd: SAH
  - ligand:
      id: [E, F]
      smiles: 'N[C@@H](Cc1ccc(O)cc1)C(=O)O'
  ```
  one ligand specified by CCD code, the next by SMILES, in the same input file — the schema explicitly requires exactly one of the two per entry (`schema.py:1029-1030`: `assert "smiles" in item or "ccd" in item; assert not both`).

## The CCD-code-vs-SMILES decision

This is the sharpest concrete I/O decision an agent makes when specifying a ligand to a co-folding model (Boltz, Chai, RFD3), and it recurs every time a ligand enters the pipeline.

**Use a CCD code when one exists and is correct for the intended chemistry** — natural cofactors, common crystallographic ligands, standard metabolites (SAH, NAD, ATP, HEM, and the ~40,000 other wwPDB-curated entries). A CCD code resolves to a single, unambiguous, pre-validated reference structure: fixed connectivity, fixed (deposited) protonation state, fixed atom names, no re-derivation needed. Boltz's own pipeline (`tools/boltz/scripts/process/ccd.py`) trusts this reference enough to generate 3D conformers directly from it via the same RDKit ETKDGv3+UFF procedure documented in `rdkit.md`, with no separate sanitization pass.
- **What goes wrong with CCD codes:** the deposited reference is not always the chemically relevant state for the agent's specific design intent — a CCD entry's formal protonation state reflects *a* crystallographic deposition, not necessarily the physiological or reaction-relevant state the design campaign needs (see `ligand-parameterization.md`'s protonation-state failure mode — CCD codes reduce but do not eliminate this risk). Picking the *wrong* CCD code (a near-miss code for a similar-but-different cofactor, e.g. NAD vs. NADH vs. NADP) is a silent, high-consequence error: the code resolves cleanly, the model runs, and the output is confidently wrong because it was never the intended cofactor at all.

**Use SMILES when no CCD code exists** — this covers essentially every *novel* candidate small molecule a design campaign will generate or propose, since a genuinely new binder/inhibitor has no wwPDB deposition by definition. SMILES gives full control over the exact chemistry (protonation, tautomer, stereochemistry — all explicitly encodable) but places the entire correctness burden on whoever wrote the string.
- **What goes wrong with SMILES:** every failure mode in `ligand-parameterization.md`'s taxonomy applies at the moment a SMILES string is authored or generated — unspecified stereocenters silently default to *something*, protonation/tautomer state is whatever the source (an LLM, a generative model, a copy-paste from a paper) happened to emit, and there is no reference structure to check it against the way a CCD lookup implicitly provides one. A malformed or ambiguous SMILES that nonetheless parses (e.g., `Chem.MolFromSmiles` returns a non-`None` `Mol`) will proceed through the entire pipeline with no signal that it encodes the wrong molecule.

**The agent-facing rule:** prefer CCD code whenever the ligand is a known, cataloged entity — check first via a CCD name/formula lookup before defaulting to SMILES — and fall back to a carefully validated SMILES (canonicalized, tautomer-checked, stereochemistry-enumerated per `ligand-parameterization.md`) only for genuinely novel candidates. Never let an agent silently substitute "the closest-sounding CCD code" for an actual identity check, and never let an agent treat "a SMILES string that parses" as equivalent to "a SMILES string that encodes the intended molecule."

## Round-trip fidelity: what is lost converting between formats

- **Bond orders:** PDB/mmCIF coordinate-only formats do not natively encode bond order at all (a PDB `HETATM` block is just atom positions plus connectivity inferred by distance, not explicit bond-order fields) — round-tripping a ligand through a plain PDB file and back into RDKit **loses aromaticity and bond-order information** unless a separate CONECT-derived or template-matched re-perception step recovers it; SDF/MOL2/SMILES all encode bond order explicitly and do not have this problem. This is precisely why `docking.md` notes `ChemGraph`'s Vina pipeline keeps the ligand as an RDKit `Mol` object end-to-end rather than round-tripping through PDB.
- **Hydrogens:** implicit-hydrogen formats (bare SMILES, a PDB file written without explicit H) require an explicit `AddHs`/protonation step downstream (`rdkit.md`, `openbabel.md`) — a converter that silently drops explicit hydrogens on write (common with some PDB writers that default to heavy-atom-only output) silently reverts a carefully-assigned protonation state back to "whatever the next tool's default hydrogen-adding heuristic produces," undoing upstream work with no error.
- **Stereochemistry:** MOL2 and some PDB writers do not reliably round-trip `@`/`@@` stereocenter or E/Z double-bond descriptors — a conversion pass through a stereo-lossy intermediate format silently flattens stereochemistry, reproducing exactly `ligand-parameterization.md`'s wrong-stereochemistry failure mode, but introduced by the I/O layer itself rather than the original input.
- **Charges:** partial charges (Gasteiger, AM1-BCC, RESP) are not a standard SDF/MOL2 field in the way bond order is — different tools store them in different optional fields (MOL2's `SYBYL` charge column vs. a custom SDF property tag), so a naive format conversion can silently drop or fail to carry forward partial charges that were computed at real (non-trivial) cost upstream, forcing (or worse, not forcing, and silently defaulting to) a cheap re-computation downstream with a different charge model — directly reproducing `ligand-parameterization.md`'s wrong-formal-charge risk class at the I/O boundary.

## Compute pattern

**P6, without exception, for every operation in this brief.** SMILES/InChI canonicalization, single-molecule format conversion, and CCD lookup are all sub-second-to-millisecond, in-memory or single-file operations — RDKit calls and Open Babel single-file CLI invocations are both already classified P6 in their own briefs (`rdkit.md`, `openbabel.md`), and nothing about chaining them for I/O changes that classification. **These belong inline, never scheduled**, for the same reason the taxonomy gives for P6 generally: the scheduling/serialization/filesystem overhead of dispatching a format conversion as its own job would be orders of magnitude larger than the conversion itself. The only legitimate promotion to P2 is the same one `rdkit.md` and `openbabel.md` already name — batch conversion of a large compound library (thousands of independent files), which is embarrassingly parallel fan-out at the campaign level, not a change to the per-call pattern. An agent architecture that routes a single SMILES canonicalization or a single SDF→PDBQT conversion through a job scheduler (or, equivalently, through an MCP round-trip to an external server) has made the textbook P6 mistake this taxonomy exists to prevent.

## Deployment on DOE & ACCESS
Nothing in this brief has a platform story of its own — it inherits RDKit's and Open Babel's
(`rdkit.md`, `openbabel.md`). Pure CPU, no GPU code path, so the CUDA/HIP/SYCL question that dominates
the ML tools does not arise on Frontier, Aurora, Polaris, or any ACCESS machine. RDKit installs cleanly
from conda-forge or pip on every target; Open Babel is available from conda-forge and most site module
systems. The only deployment-relevant caveat is licensing, not portability: Open Babel is **GPL-2.0**
while RDKit is BSD-3, so any redistributed artifact that links Open Babel inherits GPL obligations —
prefer the RDKit path wherever both can do the job, and confine Open Babel to the conversions
(notably PDBQT) that RDKit genuinely cannot perform.

## Agentic surface
- **Native MCP:** no — and this is one of the few places in the toolkit where the right answer is
  *deliberately* no. Exposing single-molecule canonicalization or format conversion over MCP would add a
  network round trip to a sub-millisecond in-process call, which is precisely the P6 mistake the taxonomy
  exists to prevent. These belong as inline library calls inside a task agent, not as remote tools.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trades off |
|---|---|---|---|---|
| `Chem.MolToSmiles(canonical=)` | bool | `True` | `True` | Canonical form for logging/dedup vs. preserving an input atom ordering |
| `isomericSmiles` | bool | `True` | `True` | Keeping stereochemistry in the exchanged string vs. a flattened graph |
| Open Babel `-p <pH>` | float | 5.0–9.0 | 7.4 | Protonation state assigned at conversion; changes net charge downstream |
| `AddHs(addCoords=)` | bool | `True` when 3D follows | `False` | Explicit H with sensible geometry vs. graph-only H |

- **Parameters that must NOT be agent-varied:** the **identity-comparison method**. Cross-tool or
  cross-run deduplication must always go through InChI/InChIKey, never raw canonical SMILES string
  equality — "canonical" is algorithm-specific, not standard-mandated, so letting an agent choose the
  cheaper string comparison silently corrupts campaign-level dedup and diversity accounting. Likewise the
  round-trip validation check (heavy-atom count, net formal charge, stereo match) is a fixed gate, not a
  tunable: making it optional removes the only signal that a lossy conversion occurred at all.

## Failure modes & what the agent must check
- **Loud failure:** malformed SMILES/InChI (`MolFromSmiles`/`MolFromInchi` return `None`, per `rdkit.md`), unsupported format pair in Open Babel (non-zero exit).
- **Silent bad output — cross-toolkit canonical-SMILES mismatch:** treating two different toolkits' "canonical SMILES" output as comparable strings is a silent identity-check bug — they can differ for the identical molecule. **Check:** use InChI/InChIKey for any cross-tool or cross-run identity/deduplication comparison, never raw canonical-SMILES string equality across toolkits.
- **Silent bad output — lossy round-trip:** see the bond-order/hydrogen/stereochemistry/charge losses above; each is silent by construction (the file writes successfully, the file reads successfully, nothing errors). **Check:** for any ligand crossing a format boundary that matters to downstream chemistry (entering docking, entering Rosetta params, entering an MD topology), verify heavy-atom count, net formal charge, and (where relevant) a stereo-SMARTS match survive the round-trip — the same discipline `openbabel.md` recommends for its own `-p`/`-h` protonation calls, generalized to every format conversion in the pipeline.
- **Silent bad output — wrong CCD code:** a near-miss CCD code (NAD vs. NADH vs. NADP, or any structurally-similar-but-distinct cofactor pair) resolves cleanly and produces a fully valid but wrong-cofactor result. **Check:** verify the resolved CCD component's formula/name against the intended cofactor explicitly, not just that a code was accepted.

## Cost per unit of work
Sub-millisecond to low-tens-of-milliseconds per single-molecule operation (canonicalization, format conversion, CCD lookup) — see `rdkit.md`/`openbabel.md` for the underlying per-call cost figures, which this brief inherits without modification since it introduces no new computational method, only a usage discipline. **Checkpointable:** n/a at single-call granularity; batch conversions should write incrementally, same as every other P6 tool in this toolkit.

## Verdict
**Core.** This brief earns its place as a short, standalone entry precisely because format mismatch is the kind of error that is easy to dismiss as "just plumbing" and is in fact a constant, compounding source of silent invalidity across this toolkit's entire small-molecule surface — every one of RDKit, Open Babel, Antechamber, OpenFF, Rosetta's `.params`, and every co-folding model's own ligand input disagrees, in some detail, about native format, canonical form, or what survives a round trip. The concrete, load-bearing recommendation: **standardize the agent's internal ligand representation on an in-memory RDKit `Mol` object carried end-to-end wherever possible** (matching `ChemGraph`'s own verified pattern in `docking_core.py`), convert to a specific external format only at the exact boundary where a specific downstream tool requires it, and treat every such boundary crossing as a point that needs the round-trip-fidelity check named above — not a trivial format-flip to be done and forgotten. And keep every operation in this brief P6: never schedule what is, categorically, an in-process call.

## Sources
- `impress-a-refcodes/tools/boltz/examples/ligand.yaml:7-12`, `tools/boltz/src/boltz/data/parse/schema.py:1029-1030` (CCD-vs-SMILES schema, verified in refcode)
- `impress-a-refcodes/tools/boltz/scripts/process/ccd.py` (CCD → RDKit conformer generation, verified in refcode)
- `docs/phase1-partA-toolkit/briefs/rdkit.md`, `openbabel.md`, `docking.md`, `ligand-parameterization.md` (read/written this session; this brief deliberately does not repeat their per-tool cost/deployment detail)
- `impress-a-refcodes/tools/ChemGraph/src/chemgraph/tools/docking_core.py:70-97` (RDKit `Mol` carried end-to-end, Meeko boundary crossing into PDBQT — cited via `docking.md`'s own research)
- InChI/InChIKey standard: IUPAC InChI Trust, https://www.inchi-trust.org/ — general provenance, not independently re-verified beyond well-established public documentation in this pass.
