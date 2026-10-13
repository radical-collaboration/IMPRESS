# RDKit

**One-line identity.** A BSD-licensed, C++-core/Python-wrapped cheminformatics library — the canonical in-process toolkit for everything a small-molecule workflow needs between "I have a SMILES string" and "I have a 3D conformer, a fingerprint, or a validated substructure match."

## Identity
- **Version / release examined:** `ReleaseNotes.md` header → `Release_2026.09.1`. Version macro in `Code/RDGeneral/versions.h.cmake` (`RDKIT_VERSION`, year*1000+month*10+rev scheme). No `pyproject.toml`/`setup.py` at repo root — RDKit is built via CMake + Boost.Python, not a pure pip package; the conda-forge/PyPI `rdkit` wheel is the redistributed artifact. Refcode: `<workspace>/impress-a-refcodes/tools/rdkit/`.
- **Provenance:** rdkit.org / `rdkit/rdkit` on GitHub, originating from Rational Discovery LLC (Greg Landrum, Julie Penzotti et al.), now community-governed. **BSD 3-Clause** (`license.txt`) — "a business friendly license for open source" per the README, no commercial-use restriction.
- **Maturity:** production. Ships as `conda install -c conda-forge rdkit` (README's own recommended install path) or PyPI `rdkit`; has a PostgreSQL cartridge, Java/C#/JS wrappers, and is the de facto substrate under nearly every other cheminformatics and generative-chemistry tool in this space (Meeko, OpenFF, DiffDock's ligand handling, ChemGraph — see `tools/ChemGraph/src/chemgraph/tools/docking_core.py`, which builds ligand 3D coordinates with `Chem.AddHs` + `AllChem.EmbedMolecule` + `AllChem.MMFFOptimizeMolecule` before ever touching Vina).

## Scientific role
The in-process substrate for **small-molecule binding** and **enzyme/catalytic design** work: every ligand that enters a docking run, a co-folding model (Boltz/Chai), or a Rosetta `.params` file passes through RDKit for parsing, sanitization, conformer generation, or descriptor/fingerprint computation first. Also supports stability and binder-design problem classes indirectly (structure I/O, distance/geometry utilities). Pipeline stages: **generate** (conformers), **analyze** (descriptors, fingerprints), **search** (substructure match, similarity), and format **I/O** (SDF/MOL/SMILES) — not a single stage but the connective tissue between stages.

## Invocation & I/O contract
- **How a unit of work is invoked:** Python API only (no CLI entrypoint). `import` paths verified against `Docs/Book/GettingStartedInPython.rst`:
  - Parse/validate: `from rdkit import Chem; m = Chem.MolFromSmiles('Cc1ccccc1')` (rst:52) — returns `None` on invalid SMILES rather than raising, which the agent must check.
  - Conformers: `m2 = Chem.AddHs(m); AllChem.EmbedMolecule(m2, params)` with `params = AllChem.ETKDGv3()` (rst:319-328); multi-conformer via `cids = AllChem.EmbedMultipleConfs(m2, numConfs=10)` (rst:742), optionally `params.numThreads = 0` for embarrassingly-parallel embedding (rst:778-780).
  - Descriptors: `Descriptors.CalcMolDescriptors(m)` returns a dict of every available descriptor (rst:2384-2389); individual calls like `Descriptors.TPSA(m)`, `Descriptors.MolLogP(m)` (rst:2376-2378).
  - Fingerprints/similarity: `fpgen = AllChem.GetMorganGenerator(radius=2); fp1 = fpgen.GetFingerprint(m1); DataStructs.TanimotoSimilarity(fp1, fp2)` (rst:1919-1939, 1784-1789).
  - Substructure: `mol.HasSubstructMatch(patt)`, `mol.GetSubstructMatches(patt)` where `patt = Chem.MolFromSmarts(...)` (rst:1097-1106).
  - SDF I/O: `Chem.SDMolSupplier('data/5ht3ligs.sdf')` for reading, `Chem.SDWriter('data/foo.sdf')` for writing (rst:110, 395-399); `ForwardSDMolSupplier` for streaming large files without random access (rst:149-155).
- **Inputs:** SMILES/SMARTS strings, SDF/MOL/MOL2 files, pickled `Mol` objects.
- **Outputs:** in-memory `rdkit.Chem.Mol` objects; on request, SMILES strings, SDF blocks, descriptor dicts, fingerprint bit/count vectors — all in-process, no filesystem round-trip required unless the caller asks for one.
- **A concrete example**, verbatim from `Docs/Book/GettingStartedInPython.rst`:
```python
m = Chem.MolFromSmiles('C1CCC1OC')
m2 = Chem.AddHs(m)
params = AllChem.ETKDGv3()
params.numThreads = 0
cids = AllChem.EmbedMultipleConfs(m2, 10, params)
res = AllChem.MMFFOptimizeMoleculeConfs(m2, numThreads=0)
```

## Compute pattern
- **Pattern:** **P6 (primary)** — every operation above (parse, single-conformer embed, descriptor, fingerprint, substructure match) is sub-second, in-memory, single-molecule work. **P2 (secondary)**, and only for one specific case named in this project's method note: `EmbedMultipleConfs` run across a **large ensemble** (many molecules × many conformers, e.g. a virtual-screening library) — this is embarrassingly parallel CPU work whose aggregate wall-clock can legitimately justify a scheduled fan-out (`numThreads` already exposes the parallelism; the P2 promotion is about batch size across an allocation, not about the API itself).
- **Why routing single calls through a scheduler is actively harmful:** an ETKDG embed of one drug-like molecule or a Morgan fingerprint/Tanimoto comparison completes in low milliseconds. Dispatching that as a scheduled task pays SLURM/PBS submission latency, serialization, and filesystem round-trip cost that is 100-10,000x the work itself — exactly the P6 failure mode the taxonomy's "Why P6 is called out at all" section warns about. The correct architecture is an agent process (or a co-located worker) that imports `rdkit` once and calls it inline, the same way `ChemGraph`'s `docking_core.py` calls `Chem.AddHs`/`AllChem.EmbedMolecule` directly inside its own Python process rather than shelling out.
- **GPU vendor portability:** **CPU-only / n/a.** RDKit's core is C++ with Boost.Python bindings; no CUDA/HIP/SYCL dependency anywhere in the build (`CMakeLists.txt` has no GPU toolkit `find_package`). This is a feature for this project: RDKit runs identically on Frontier, Aurora, Polaris, and every ACCESS machine with zero vendor-portability risk — the opposite risk profile of every P1 structure-prediction model in this toolkit.
- **State model:** stateless (each call is a pure function of its inputs; no persistent process state between calls).
- **Data locality:** self-contained (in-memory `Mol` objects); file I/O only when the caller explicitly reads/writes SDF/MOL.
- **Staging burden:** none. No model weights, no reference database.
- **Container availability:** official (conda-forge `rdkit` package, README's own recommended install: `conda install -c conda-forge rdkit`; also PyPI wheels). No first-party Apptainer image, but the conda package trivially containerizes.

## Deployment on DOE & ACCESS
Identical on every target platform because it has no GPU dependency: **Frontier, Aurora, Polaris, Delta, Bridges-2, Expanse all run the same conda-forge `rdkit` build.** Deployment mechanism: conda/mamba environment (module-provided Python + conda-forge channel) is the simplest path; Apptainer container wrapping the same conda env is equally viable for reproducibility. No license gate (BSD 3-Clause). The only staging concern is ensuring the conda environment is built once on a login/build node and available on compute nodes via shared FS — trivial relative to any P1 model's weight-staging burden.

## Agentic surface
- **Native MCP:** **community**, unverified maturity. Two third-party servers found: `tandemai-inc/rdkit-mcp-server` (github.com/tandemai-inc/rdkit-mcp-server) — MIT license, claims "agent-level access to every function in RDKit 2025.3.1... without writing any code," 42 stars/7 forks/76 commits at time of search, third-party (not RDKit-project-affiliated); and `s20ss/mcp_rdkit` (github.com/s20ss/mcp_rdkit), less-documented. Neither is an RDKit-project-official server. **Given P6's core instruction ("must never become a scheduled task"), an MCP wrapper around RDKit is the wrong integration point for this project anyway** — MCP round-trips add exactly the latency P6 exists to avoid. RDKit belongs imported directly into the agent's own process or a co-located worker, not called through a tool-protocol hop.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `numConfs` (`EmbedMultipleConfs`) | int | 1-50 (small molecules), up to 200-300 for flexible/macrocyclic ligands | n/a (caller-specified) | More conformers → better coverage of accessible conformational space, linear cost; the P6→P2 promotion lever for large batches |
| `pruneRmsThresh` (`ETKDGv3` params / `EmbedMultipleConfs`) | float, Å | 0.0 (no pruning) - 2.0 | 0.0 (RDKit default: no pruning) — literature/community practice commonly uses 0.5-1.0 | Higher → discards near-duplicate conformers, keeping the ensemble diverse per unit compute; too aggressive silently under-samples the real conformational landscape |
| `params.numThreads` (`ETKDGv3`) | int | 0 (use all cores) - N | 1 | Parallelizes embedding across a single node's cores; the mechanism that makes large-ensemble embedding a legitimate P2 fan-out rather than a serial P6 loop |
| `radius` (`GetMorganGenerator`) | int | 1-3 | 2 (ECFP4-equivalent) | Larger radius → captures more distal substructure context in fingerprints, changes similarity search recall/precision |
| `fpSize` (fingerprint generators) | int | 1024-4096 | 2048 | Larger → fewer bit collisions, better discrimination, marginal memory/compute cost |
| `useChirality` (`HasSubstructMatch`) | bool | on/off | off | Off silently matches both enantiomers as identical — must be on for any stereochemistry-sensitive catalytic/binding-site query |

- **Parameters that must NOT be agent-varied:** `sanitize=False` on `MolFromSmiles`/`MolFromMolBlock` — disabling sanitization skips valence/aromaticity checks and can silently admit chemically invalid molecules into a pipeline; only ever used deliberately for debugging malformed input, never as a default. The choice of force field for conformer cleanup (UFF vs MMFF94) should be fixed per problem class, not toggled per-call, since MMFF re-derives its own aromaticity model on the fly (rst:709-711) and mixing force fields across a comparison set silently invalidates energy comparisons.

## Failure modes & what the agent must check
- **Loud failure:** malformed SMILES/SMARTS via `MolFromSmiles`/`MolFromSmarts` returns `None` rather than raising — this is a *silent-looking* API but is easy to gate: **the agent must always check `mol is not None` after any `MolFrom*` call**, since a `None` propagating into `AddHs`, `EmbedMolecule`, etc. raises an unhelpful `AttributeError` several calls downstream.
- **Silent bad output (embedding failure):** `AllChem.EmbedMolecule` returns `-1` on failure to find a valid embedding (rather than an exception) — the getting-started examples show checking the return code (`>>> AllChem.EmbedMolecule(m3, params)` → `0` on success); an agent that doesn't check this return value will silently carry a molecule with **no 3D coordinates** (a `Conformer`-less `Mol`) into downstream code, which then fails opaquely or, worse, some tools construct a default all-zero conformer.
- **Silent bad output (ugly/strained conformers):** the docs explicitly warn *"the conformers that result from this procedure tend to be fairly ugly. They should be cleaned up using a force field"* (rst:684-685) — the agent must run `MMFFOptimizeMolecule`/`UFFOptimizeMolecule` (or trust ETKDG's built-in torsion corrections, per rst:688-692) and should not treat a raw distance-geometry embed as production-quality geometry for anything downstream that cares about strain energy.
- **Specific checks:** verify `mol.GetNumConformers() > 0` post-embed; check `AllChem.MMFFOptimizeMoleculeConfs()`'s returned `(not_converged, energy)` tuples per conformer (rst: "If not_converged is 0, the minimization... converged") rather than assuming convergence; for substructure queries, confirm `useChirality` matches the scientific intent before trusting a match/no-match result.

## Cost per unit of work
- **Unit of work:** one SMILES parse + sanitize: sub-millisecond. One ETKDG single-conformer embed of a drug-like molecule (~20-40 heavy atoms): low tens of milliseconds. One Morgan fingerprint + Tanimoto comparison: sub-millisecond. One `EmbedMultipleConfs(numConfs=50)` for a flexible ligand: on the order of a second, single-threaded. (Approximate, order-of-magnitude; not independently benchmarked in this pass — state as assumption pending empirical calibration on target hardware.)
- **Resource shape:** single CPU core per call by default; `numThreads=0` fans out across all cores on the node for multi-conformer/multi-molecule batches.
- **Checkpointable:** n/a at the single-call level (stateless, re-runs trivially); at the P2 batch level, checkpointing is the caller's responsibility (e.g., write completed conformers/descriptors incrementally rather than holding an entire library in memory).

## Verdict
**Core.** RDKit is the load-bearing cheminformatics substrate for this entire cluster and for every other tool in the toolkit that touches a small molecule (Boltz-2's SMILES input, Rosetta's ligand params pipeline, any docking tool's ligand prep). It is licensed permissively, has zero GPU-portability risk (uniquely valuable given how much of the rest of this toolkit is CUDA-anxious), and its P6 classification is not a footnote — it is the concrete argument for why this project's execution layer needs an inline-call path distinct from its job-scheduling path. The one caveat worth tracking operationally is the P6→P2 promotion boundary for large conformer ensembles; get that threshold wrong and either single calls get scheduled (wasteful) or a 10,000-molecule embedding job runs serially inside an agent's own walltime (also wasteful, just differently).

## Sources
- `<workspace>/impress-a-refcodes/tools/rdkit/Docs/Book/GettingStartedInPython.rst` (line numbers cited inline)
- `<workspace>/impress-a-refcodes/tools/rdkit/ReleaseNotes.md`
- `<workspace>/impress-a-refcodes/tools/rdkit/license.txt`
- `<workspace>/impress-a-refcodes/tools/rdkit/README.md`
- `<workspace>/impress-a-refcodes/tools/rdkit/Code/RDGeneral/versions.h.cmake`
- `<workspace>/impress-a-refcodes/tools/ChemGraph/src/chemgraph/tools/docking_core.py` (example of RDKit called in-process ahead of a P1/P2 docking step)
- [tandemai-inc/rdkit-mcp-server](https://github.com/tandemai-inc/rdkit-mcp-server) — community MCP server, inspected via WebFetch; MIT license, third-party, not RDKit-project-affiliated
- [s20ss/mcp_rdkit](https://github.com/s20ss/mcp_rdkit) — second community MCP server, found but not independently inspected beyond search snippet
- rdkit.org, `conda-forge rdkit` package — general provenance, not independently re-verified beyond README claim
