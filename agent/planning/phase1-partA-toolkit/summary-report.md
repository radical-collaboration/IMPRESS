# Phase 1, Part A — Toolkit Summary Report

**Project:** IMPRESS-A — autonomous protein design on HPC
**Scope:** science background and toolkit structure. Not agent architecture (Part B), not project
structure (Part C), not middleware (Phase 2), not code (Phase 4).
**Date:** 2026-09-21
**Basis:** 38 tool briefs in `briefs/`, the classification scheme in `compute-pattern-taxonomy.md`, and the
MCP survey in `mcp-landscape.md`.

---

## 1. What this report concludes

Six findings drove the toolkit's shape. Each is argued in the briefs and summarized in the tables below.

**1. The portability picture is the inverse of what one would assume.** The classical simulation engines are
the *most* portable code in the toolkit and the modern ML models are the *least*. GROMACS builds from one
source tree for CUDA, HIP, SYCL and OpenCL; LAMMPS matches it via KOKKOS. Meanwhile a repo-wide grep of
`tools/foundry` for `hip`/`rocm`/`amd` returns **zero hits** — no code path, no CI job, no documentation. On
Frontier, the generative core of this project is an unproven from-source build spike, not a configuration
change. Aurora is in better shape than Frontier, which is also counterintuitive: foundry ships real Intel XPU
support (`src/foundry/utils/xpu/`, with custom Lightning Fabric accelerator and strategy classes) and RF3
documents a tested install order for it.

**This finding drove a scope decision.** Polaris and NSF ACCESS are now primary, Aurora second, and
**Frontier is deprioritized** with no HIP spike scheduled (`decisions/0008`). Frontier remains in the site
matrix so the compose-time portability gate refuses the ML core there rather than failing at runtime.

*Correction, on direct repo read:* Chai-1 was initially recorded as "likely CUDA-only" on a suspected
flash-attention dependency. That was wrong — a repo-wide grep of `tools/chai-lab` for
`flash|triton|cuequivariance|rocm|hip|xpu` returns zero hits, the only dependency is plain `torch>=2.3.1`,
and the model ships as TorchScript components including `traced_sdpa_esm2_...` (PyTorch native attention).
Its remaining NVIDIA coupling is three `torch.cuda.empty_cache()` calls and a `cuda:0` default. PLACER, by
contrast, is genuinely CUDA-only on much stronger evidence: no XPU branch in its device ladder, a `dgl`
dependency pinned to a cu121 channel with no ROCm backend, and NVIDIA's own se3-transformer package.

**2. The self-consistency loop, not any single tool, is the scientific core.** Generate a backbone (RFD3) →
design a sequence (MPNN) → predict that sequence's structure (Boltz/RF3/ESMFold) → superpose against the
original backbone (US-align). The accept/reject decision lives in that last comparison. Every tool in the
toolkit is positioned relative to this loop, and the single most important quantity the agent computes is a
TM-score or scRMSD, not a physics energy.

**3. Co-folding has largely absorbed classical docking.** Boltz-2 predicts structure *and* a trained affinity
estimate jointly from sequence plus SMILES, with no receptor structure or binding box required. Classical
docking's scoring power (PCC ≈ 0.6 on curated benchmarks) is not competitive as an affinity signal. Vina
survives as a near-zero-cost CPU geometric pre-filter and as the only option at virtual-screening scale;
DiffDock is deferred on a documented generalization collapse (≈12% success on novel targets — precisely our
use case).

**4. Silent failure, not crashes, is the dominant hazard.** This recurs in every cluster and is the single
most important theme for Part B. Rosetta completes happily on nonsense geometry. A mis-parameterized ligand
produces a full batch of confidently-scored, ranked designs. A folding model returns high confidence on a
wrong domain orientation. `foundry install` cannot detect a truncated download because every
`REGISTERED_CHECKPOINTS` entry has `sha256=None`. An autonomous loop that only checks exit codes will spend
its entire allocation producing invalid results and report success.

**5. The MCP ecosystem is not ready to carry execution.** Of 26 surveyed entries, **2 are verified** (ChemGraph's
own servers, read on disk; RCSB PDB's official `rcsb/rcsb-mcp`, confirmed via the GitHub organization API).
Database lookup is a healthy corner. Every tool that runs real HPC computation is either absent from MCP
entirely or covered only by unaudited third-party wrappers. We build our own execution layer.

**6. Cost asymmetry across the toolkit spans seven orders of magnitude**, and the policy implications are
concrete. Rosetta `cartesian_ddg` costs 1–15 CPU-hours *per point mutation*, so a saturation scan on a
200-residue protein is thousands to tens of thousands of CPU-hours. ThermoMPNN answers the same question at
near-zero cost with independently-benchmarked accuracy in the same band (r ≈ 0.6–0.7). Mutation selection is
therefore a budget problem, and the correct pattern is cheap-screen-then-physics-confirm, not exhaustive scan.

---

## 2. T1 — Master roster

48 entities across 38 briefs. Some briefs cover several entities that differ in license or deployment; each
entity gets its own row. Patterns are defined in `compute-pattern-taxonomy.md`.

| # | Entity | Brief | Role | Pattern | GPU portability | MCP | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | RFdiffusion3 | `rfdiffusion3.md` | Backbone generation | P1 | CUDA + XPU proven; **HIP unproven** | none | **Core** |
| 2 | RFdiffusion3NA | `rfdiffusion3na.md` | NA-extended generation | P1 | as RFD3 | none | Recommended |
| 3 | ProteinMPNN / LigandMPNN | `proteinmpnn-ligandmpnn.md` | Inverse folding | P1 | CUDA + XPU; no cuEq dependency | none | **Core** |
| 4 | AtomWorks | `atomworks.md` | Structure I/O + featurization | P6 | portable (pure Python) | none | **Core** (transitive) |
| 5 | foundry (suite infra) | `foundry.md` | Engine, checkpoints, Hydra | P5 install / P6 engine | n/a | none | **Core** |
| 6 | RF3 | `rf3.md` | Structure prediction | P1 | CUDA + **first-party XPU**; HIP unproven | none | **Core** |
| 7 | AlphaFold2 | `alphafold.md` | Structure prediction | P1 + P2 (MSA) | CUDA; AMD precedent (LUMI) | lookup-only | Recommended |
| 8 | AlphaFold3 | `alphafold.md` | Structure prediction | P1 | CUDA | — | **Defer** (weights gate) |
| 9 | ColabFold | `alphafold.md` | MSA-as-a-service + AF2 | P5 (MSA) + P1 | CUDA | — | **Core** |
| 10 | ESMFold | `esmfold.md` | Fast single-seq folding | P1 | pure PyTorch — most portable | unverified | Recommended |
| 11 | Boltz-2 | `boltz.md` | Co-folding + affinity | P1 (+P5) | CUDA-primary; `--no_kernels` fallback | none | **Core** |
| 12 | Chai-1 | `chai.md` | Co-folding | P1 (+P5) | plain `torch`, TorchScript+sdpa; ROCm plausible-unverified | none | **Recommended** |
| 13 | Chai-2 | `chai.md` | Co-folding | n/a | n/a | none | **Reject** (confirmed: no code or weights in refcode) |
| 14 | Rosetta / RosettaScripts | `rosetta.md` | Physics design & scoring | P2 / P3 | CPU-only | community, low-trust | **Core** |
| 15 | PyRosetta | `pyrosetta.md` | Scriptable Rosetta API | P2 / P4 | CPU-only | community, low-trust | **Core** |
| 16 | Rosetta `cartesian_ddg` | `rosetta-ddg.md` | ΔΔG physics | P2 | CPU-only | — | **Core** |
| 17 | `ddg_monomer` | `rosetta-ddg.md` | ΔΔG (legacy) | P2 | CPU-only | — | Defer |
| 18 | PROSS | `rosetta-ddg.md` | Stabilization protocol | undetermined | CPU | — | Defer (needs decision) |
| 19 | Rosetta enzyme design / match | `rosetta-enzyme-design.md` | Catalytic design | P2 | CPU-only | — | **Core**, human-gated |
| 20 | AgentRosetta | `agent-rosetta.md` | Prior-art agent | P1+P2+P3/P4 | CUDA (ESMFold reward) | none | Mine for patterns |
| 21 | GROMACS | `gromacs.md` | Explicit-solvent MD | P3 / P4 | **CUDA+HIP+SYCL+OpenCL** | none | Recommended |
| 22 | LAMMPS | `lammps.md` | Materials MD | P3 / P4 | CUDA+HIP+SYCL | unverified | Defer |
| 23 | OpenMM | `openmm.md` | GPU MD, Python API | P1 / P4 | CUDA+OpenCL; HIP plugin; **no SYCL** | unverified | **Core** |
| 24 | MDAnalysis / MDTraj | `mdanalysis-mdtraj.md` | Trajectory → metric | P6 / P2 | CPU-only | none | **Core** |
| 25 | PDBFixer / packmol / PROPKA | `structure-prep.md` | System preparation | P6 / P2 | CPU-only | none | **Core** |
| 26 | FoldSeek | `foldseek.md` | Structural search / novelty | P2 (GPU optional) | CUDA optional | see landscape | **Core** |
| 27 | MMseqs2 | `mmseqs2.md` | Sequence search / MSA | P2 | CPU (+GPU) | see landscape | **Core** |
| 28 | HMMER / HH-suite | `hmmer-hhsuite.md` | Sensitive MSA | P2 | CPU-only | — | Defer |
| 29 | US-align / TM-align | `us-align.md` | **Self-consistency metric** | P6 | CPU-only | — | **Core** |
| 30 | RCSB PDB API | `bio-databases.md` | Structure lookup | P5 | n/a | **official (verified)** | **Core** |
| 31 | UniProt API | `bio-databases.md` | Sequence/annotation | P5 | n/a | community (unaffiliated) | **Core** |
| 32 | AlphaFold DB API | `bio-databases.md` | Predicted-structure lookup | P5 | n/a | community (unaffiliated) | **Core** |
| 33 | ESM Atlas API | `bio-databases.md` | Fold / embedding service | P5 | n/a | — | Core (budget conservatively) |
| 34 | ColabFold MSA server | `bio-databases.md` | MSA-as-a-service | P5 | n/a | — | **Core by necessity** |
| 35 | RDKit | `rdkit.md` | Cheminformatics | P6 (P2 batch) | CPU-only | see landscape | **Core** |
| 36 | Open Babel | `openbabel.md` | Format conversion | P6 | CPU-only | — | Recommended |
| 37 | AutoDock Vina | `docking.md` | Geometric pre-filter | P2 | CPU (+GPU fork) | — | Recommended |
| 38 | GNINA | `docking.md` | CNN pose rescoring | P1 | CUDA | — | Recommended (conditional) |
| 39 | DiffDock | `docking.md` | Blind docking | P1 | CUDA | — | **Defer** |
| 40 | Ligand parameterization | `ligand-parameterization.md` | params/GAFF/OpenFF/CCD | P6 / P2 | CPU-only | — | **Core** |
| 41 | Cheminformatics I/O | `cheminformatics-io.md` | Format plumbing | P6 | CPU-only | none (deliberately) | **Core** |
| 42 | DSSP / FreeSASA / MolProbity | `structure-qc.md` | Cheap sanity gates | P6 | CPU-only | — | **Core** |
| 43 | Biotite / BioPython / ProDy | `structure-libraries.md` | Parsing substrate | P6 | CPU-only | — | **Core** (Biotite primary) |
| 44 | PyMOL | `pymol.md` | Geometry + human review | P6 | CPU-only | identified, **not runtime-verified** | Recommended |
| 45 | ThermoMPNN | `ddg-predictors.md` | Cheap ΔΔG screening | P1 | CUDA | — | **Core** |
| 46 | Stability Oracle | `ddg-predictors.md` | Second ΔΔG opinion | P1 | CUDA | — | Recommended |
| 47 | FoldX | `ddg-predictors.md` | ΔΔG | P2 | CPU-only | — | **Defer** (license gate) |
| 48 | ESM2 scoring / ESM-IF1 | `esm-scoring.md` | Likelihood, embeddings, inverse folding | P1 (+P5) | CUDA | — | Recommended |
| 49 | ESM-C / ESM3 | `esm-scoring.md` | Newer ESM family | P1 | CUDA | — | Defer (license) |
| 50 | IMPRESS | `impress.md` | **Composite pipelines** | **P7** | n/a | none (verified absent) | **Core** |
| 51 | ChemGraph | `chemgraph.md` | Prior-art agent framework | n/a | n/a | **yes (verified)** | Mine for patterns |
| 52 | LLM oracle | `llm-oracle.md` | Control mode B reasoning | P5 | n/a | n/a | **Core** |
| 53 | PLACER | `placer.md` | Active-site / ligand conformer prediction | P1 | **CUDA-only** (no XPU branch; `dgl` cu121; NVIDIA se3-transformer) | none | Recommended |
| 54 | NetSolP | `developability-surrogates.md` | Solubility prediction | P1 | CUDA | none | Recommended |
| 55 | Aggrescan3D | `developability-surrogates.md` | Structure-aware aggregation | P6 | CPU-only | none | Recommended (verify Py3) |
| 56 | CamSol, SoluProt | `developability-surrogates.md` | Solubility, ensemble members | P5 / P6 | CPU | none | Recommended (ensemble only) |
| 57 | Protein-Sol, AGGRESCAN, TANGO, WALTZ | `developability-surrogates.md` | Solubility / aggregation | P5 / P6 | CPU | none | Defer (friction, license) |

**Counts:** 25 Core · 18 Recommended · 11 Defer · 1 Reject · 3 mine-for-patterns/infrastructure.

*Updated 2026-09-21 after the Phase 1 decision round: Chai-1 promoted Defer → Recommended on a direct repo
read; PLACER and the developability surrogates added at user request. 57 entities across 40 briefs.*

---

## 3. T2 — Compute-pattern taxonomy

| ID | Pattern | Scheduling implication | Exemplars in this toolkit |
|---|---|---|---|
| **P1** | GPU-node-local, in-job | Placed on a GPU the agent already holds; contends with other P1 work | RFD3, MPNN, Boltz-2, RF3, ESMFold, ThermoMPNN, OpenMM |
| **P2** | CPU-parallel fan-out, in-job | Scales by replica count; the natural knob for adaptive batch sizing | Rosetta `nstruct`, `cartesian_ddg`, FoldSeek, MMseqs2, Vina |
| **P3** | MPI multi-node, in-job | Needs a reserved rank topology; not resizable mid-run | GROMACS `mdrun`, LAMMPS, Rosetta MPI |
| **P4** | External HPC job | Async submit/poll; outlives the agent; needs a durable job ledger | Long MD production, `PyRosettaCluster`, oversized ensembles |
| **P5** | Network service over HTTPS | No local resource cost; fails by latency, quota, outage, **schema drift** | RCSB, UniProt, AFDB, ESM Atlas, ColabFold MSA, LLM oracle |
| **P6** | In-process library call | **Must never be scheduled** — overhead would exceed the work | RDKit, AtomWorks, US-align, DSSP, Biotite, MDAnalysis |
| **P7** | Composite pipeline | Parameterize and launch; internal stages not individually steered | IMPRESS `protein_binding`, `small_molecule_binding`, `discontinuous_scaffolds` |

The P1/P4 boundary is the consequential one for an autonomous outer loop: P4 work can outlive the agent, so
it demands durable job state and introduces queue wait as a cost term unrelated to the science. The P6
designation is equally load-bearing in the opposite direction — it is an instruction to inline the call.

---

## 4. T3 — Coverage matrix

Problem class × pipeline stage. **Bold** = load-bearing. Gaps are called out below the table.

| Stage | Stability / thermostabilization | De novo binder design | Enzyme / catalytic design | Small-molecule binding |
|---|---|---|---|---|
| **Generate** | (mutation enumeration) | **RFD3**, RFD3NA | **RFD3** motif scaffolding, Rosetta `match` | **RFD3** ligand-conditioned |
| **Inverse-fold** | ProteinMPNN (soluble variants) | **ProteinMPNN** | **LigandMPNN** | **LigandMPNN** |
| **Predict** | ESMFold, Boltz-2 | **Boltz-2**, RF3, ColabFold | RF3, Boltz-2 | **Boltz-2** (+ affinity head) |
| **Score** | **ThermoMPNN**, **`cartesian_ddg`**, Stability Oracle, ESM2 likelihood | ipTM/pTM, Rosetta InterfaceAnalyzer | Rosetta enzdes constraints, catalytic geometry | **Boltz-2 affinity**, Vina (pose only) |
| **Simulate** | OpenMM relax; GROMACS triage | OpenMM relax | OpenMM relax; GROMACS | OpenMM relax; GROMACS |
| **Search** | FoldSeek, MMseqs2, UniProt | **FoldSeek** (novelty), ColabFold MSA | FoldSeek, RCSB | RCSB ligand search |
| **Analyze** | **US-align**, DSSP, FreeSASA, MolProbity, MDAnalysis | **US-align**, MolProbity, PyMOL | US-align, PyMOL `get_distance` | US-align, RDKit |
| **Developability** | NetSolP, Aggrescan3D, SolubleMPNN | NetSolP, Aggrescan3D | NetSolP | NetSolP |

### Gaps this matrix exposes

- **Experimental-data ingestion is absent.** Nothing in the toolkit consumes assay results. A genuinely
  autonomous design–build–test–learn loop closes through the wet lab; this toolkit closes through *in silico*
  self-consistency only. That is a scope boundary worth stating rather than discovering later.
- **Developability is now represented but weakly evidenced.** `developability-surrogates.md` was added at
  user request. The honest accuracy picture: NetSolP is the best-evidenced (independent test AUC 0.76,
  MCC 0.40), while on SoluProt's own fair comparative benchmark everything else clusters near chance
  (SoluProt 58.5% acc, PROSO II 58.0%, SWI 55.9%, CamSol 54.1%). Aggregation tools have no comparable
  independent figure at all. **No single-predictor score is a gate; cross-predictor agreement is a soft
  signal only.** None were trained on computationally designed sequences, so the de novo generalization gap
  applies with full force. These are the surrogates Part B `09` is designed to let robotic-lab measurements
  supersede.
- **Enzyme design's generate stage depends on a human.** Theozyme and constraint-file authoring is expert
  mechanistic judgment. The agent can vary parameters and run QC, but cannot author the hypothesis. PLACER
  (added) needs no constraint file at all — it predicts active-site geometry from a learned prior — so it
  serves as an architecturally orthogonal cross-check on Rosetta-matched sites, but it does not supply the
  catalytic hypothesis either.
- **Binding free energy is out of reach.** FEP/alchemical methods need too much expert setup and too many
  node-hours for an autonomous loop. Boltz-2's affinity head is the practical substitute, with the accuracy
  caveats its brief documents.
- **Multi-state and conformational-ensemble design** is not covered — relevant to switches and allostery.

---

## 5. T4 — MCP readiness

Full evidence in `mcp-landscape.md`. Summary by tier:

| Tier | Count | Entries |
|---|---|---|
| **Verified** | 2 | ChemGraph (13 server modules read on disk; `mcp==1.28.1`, `fastmcp==3.4.4`); RCSB PDB (`rcsb/rcsb-mcp`, GitHub org-confirmed) |
| **Official, adjacent** | 1 | PDBe (`PDBeurope/PDBe-MCP-Servers`, org-confirmed) |
| **Identified, not runtime-verified** | 1 | PyMOL — schemas registered in this session but `mcp__pymol__status` returns connection-refused on 127.0.0.1:9877 |
| **Community / unverified** | 11 | Rosetta, OpenMM, LAMMPS, AlphaFold (lookup-only), UniProt, AFDB, and others — existence confirmed, trust not |
| **Verified absent** | 12 | RFD3, RFD3NA, MPNN, RF3, AtomWorks, foundry, Boltz, Chai, ColabFold, IMPRESS, and others — repo-wide greps return zero |

**Assessment.** The ecosystem splits cleanly by difficulty. Wrapping a read-only public API is shallow work
that many independent developers have converged on correctly — that corner is healthy and adoptable.
Exposing real HPC computation through a synchronous tool interface is hard, and essentially nobody has done
it for protein design; ChemGraph is the sole well-engineered example and it wraps computational chemistry.

Two cautions carry into Part B. First, **PyMOL's architecture is the general shape of the problem**: a plugin
inside a live GUI process on a local TCP port is a desktop pattern that cannot run unattended in a batch job.
Second, **supply-chain trust is a real dimension, not a formality** — an unaffiliated `Augmented-Nature`
organization publishes multiple `<Database>-MCP-Server` repos that read as official once a marketplace strips
provenance, and one scanner flags the third-party Rosetta server as low-trust. Adopting unaudited MCP servers
into an unattended HPC pipeline is a risk decision, not a convenience.

**Recommendation:** adopt the two verified database servers if MCP integration is wanted there; build our own
execution layer for everything else.

---

## 6. T5 — Cost and scale

| Tool | Unit of work | Typical wall-clock | Resource shape | Checkpointable |
|---|---|---|---|---|
| RFD3 | 1 backbone design | seconds–minutes | 1 GPU | no |
| ProteinMPNN | 1 sequence | sub-second–seconds | 1 GPU (CPU viable) | no |
| ESMFold | 1 prediction | **5–15 s** | 1 GPU | no |
| Boltz-2 | 1 complex prediction | minutes | 1 GPU | no |
| AF2 (fresh target) | 1 prediction | 5 min – 2 hr (MSA-dominated) | 1 GPU + CPU MSA | no |
| Rosetta FastRelax | 1 decoy (~200 res) | **3–15 CPU-min** | 1 core | yes |
| Rosetta `cartesian_ddg` | **1 point mutation** | **1–15 CPU-hr** | 1 core | yes |
| ThermoMPNN | 1 mutation | milliseconds | 1 GPU | no |
| OpenMM relaxation | 1 structure | **seconds – 2 min** | 1 GPU | yes |
| GROMACS production | 20 ns, ~80k atoms | **~1.5–2.5 hr** (241 ns/day, 1×A100) | 1+ GPU, MPI | yes (`.cpt`) |
| FoldSeek `easy-search` | 1 query vs. DB | seconds–hours | CPU (GPU optional) | no |
| US-align | 1 pairwise comparison | milliseconds | 1 core | n/a |
| LLM oracle | 1 call (~5k in / 1k out) | seconds | network | n/a |

**The two numbers that should drive policy.** A `cartesian_ddg` saturation scan on a 200-residue protein
(~3,800 mutations) is **thousands to tens of thousands of CPU-hours**. ThermoMPNN answers the same question
in milliseconds per mutation at r ≈ 0.6–0.7 on independent benchmarks — statistically indistinguishable from
Rosetta's r ≈ 0.63–0.66 once out of distribution. The recommended strategy is therefore: screen exhaustively
with ThermoMPNN (cross-checked against Stability Oracle for disagreement), gate on the free antisymmetry
self-check, then forward a **tens-to-low-hundreds** shortlist to `cartesian_ddg` for physics confirmation.

**Oracle cost is not the binding constraint.** At verified pricing — Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5
$1/$5 per 1M tokens — 5,000 oracle calls on Sonnet 5 costs roughly $100 uncached, well under $50 with prompt
caching. That is negligible against the GPU- and CPU-hours it steers. Call *frequency* design (per-candidate
vs. per-batch) moves the figure by one to two orders of magnitude and matters more than model choice.

---

## 7. T6 — Platform deployment matrix

✅ native/proven · ⚠️ plugin, unproven, or degraded · ❌ no path · — not applicable

| Tool | Frontier (HIP) | Aurora (SYCL/XPU) | Polaris (CUDA) | ACCESS (CUDA) | Mechanism |
|---|---|---|---|---|---|
| RFD3 / RFD3NA | ⚠️ unproven | ✅ documented XPU | ✅ | ✅ | Apptainer (`rosettacommons/foundry`) or pip |
| ProteinMPNN | ⚠️ best HIP candidate (no cuEq) | ✅ | ✅ | ✅ | same |
| RF3 | ⚠️ unproven | ✅ first-party XPU path | ✅ | ✅ | cuEquivariance is CUDA-12-only |
| Boltz-2 | ⚠️ `--no_kernels` fallback | ⚠️ unverified | ✅ | ✅ | pip |
| ESMFold | ⚠️ plausible (pure PyTorch) | ⚠️ plausible | ✅ | ✅ | pip |
| AlphaFold2 | ⚠️ precedent (LUMI/Pawsey) | ❌ | ✅ | ✅ | container + ~2.6 TB DBs |
| ColabFold | ⚠️ | ⚠️ | ✅ | ✅ | P5 MSA removes the DB burden |
| Rosetta / PyRosetta | ✅ CPU | ✅ CPU | ✅ | ✅ | scons build; MPI variants |
| GROMACS | ✅ **HIP native** | ✅ **SYCL native** | ✅ | ✅ | `GMX_GPU` multichoice |
| LAMMPS | ✅ KOKKOS HIP | ✅ KOKKOS SYCL | ✅ | ✅ | KOKKOS / GPU package |
| OpenMM | ⚠️ `amd/openmm-hip` plugin | ❌ **no SYCL platform** | ✅ | ✅ | conda-forge |
| FoldSeek / MMseqs2 | ✅ CPU | ✅ CPU | ✅ | ✅ | `ENABLE_CUDA` optional |
| RDKit / Biotite / US-align / DSSP | ✅ | ✅ | ✅ | ✅ | CPU-only, no concerns |
| Bio-database APIs | ✅ | ✅ | ✅ | ✅ | requires egress only |

**Reading this table.** Aurora is better supported than Frontier for the ML core, and worse for MD. On
Aurora, **GROMACS must carry the MD workload** because OpenMM has no SYCL platform at all; OpenMM falls back
to CPU-only relaxation there. On Frontier, the generative core needs a verification spike before it can be
planned around — MPNN is the cleanest candidate to attempt first, since it carries no cuEquivariance
dependency whatsoever.

---

## 8. T7 — Curated additions

Tools not in the original list that were investigated and are recommended for inclusion.

| Addition | Gap it fills | Verdict | Justification |
|---|---|---|---|
| **OpenMM** | Cheap per-candidate relaxation with a real Python API | **Core** | The one MD-adjacent step affordable on every candidate (seconds–2 min). Already the field-standard post-prediction relax (AlphaFold's own Amber relax). Python API suits agent-driven parameter variation far better than `gmx`'s file-and-CLI contract. Caveat: no Aurora GPU path. |
| **US-align / TM-align** | The self-consistency metric itself | **Core** | Closes the design loop. Length-normalized TM-score with a citable ≥0.5 "same fold" threshold; stateless, CPU-trivial, zero licensing friction. Preferred over PyMOL's `align`/`rms` for this purpose. |
| **ThermoMPNN** | Affordable ΔΔG screening | **Core** | Makes saturation scans routine at ~10⁶× lower cost than `cartesian_ddg`, at comparable out-of-distribution accuracy. Load-bearing for the stability problem class. |
| **MDAnalysis / MDTraj** | Trajectory → scalar metric | **Core** | Without it, MD output is dead weight. This is the mechanism that turns an expensive simulation into a number a policy can act on. |
| **Structure prep (PDBFixer / packmol / PROPKA+pdb2pqr)** | System preparation | **Core** | The classic silent-failure point in automated MD. Cheap to run, catastrophic to get wrong. |
| **Ligand parameterization discipline** | Correct small molecules | **Core** | Six-item silent-failure taxonomy (protonation, tautomer, charge, stereochemistry, missing torsions, atom naming), each with a specific catching check. Recommended as a mandatory automated gate. |
| **Structure QC (DSSP / FreeSASA / MolProbity)** | Cheap physical sanity gates | **Core** | Catches nonsensical designs before expensive tools are spent on them. |
| **Biotite** (over BioPython) | Parsing substrate | **Core** | Faster and more modern; BioPython retained for specific interop. A real recommendation, not a tie. |
| **MMseqs2** | MSA generation workhorse | **Core** | The engine behind ColabFold and the local fallback when the public MSA server is unavailable. |
| **Stability Oracle** | Second ΔΔG opinion | Recommended | Independently trained; enables free disagreement-detection ensembling against ThermoMPNN. Verify license first. |
| **ESM2 scoring / ESM-IF1** | Zero-shot fitness, embeddings, second inverse-folder | Recommended | Embeddings uniquely enable design-population diversity monitoring — nothing else in the toolkit provides it. MIT-licensed. |
| **AutoDock Vina** | Virtual-screening-scale pre-filter | Recommended | Use its docking power (pose plausibility), never its scoring power (affinity). |
| **Open Babel** | PDBQT and broad format conversion | Recommended | Fills the formats RDKit cannot write. GPL-2.0 — confine rather than embrace. |
| **LiteLLM** | Provider abstraction for the oracle | Recommended | Thin, swappable, built-in retry/backoff/failover. Preferred over LangChain's larger, churning surface unless we independently commit to LangGraph. |
| **`paretoset`** | Multi-objective selection | Recommended | Lightweight, directly adoptable dependency (already used by AgentRosetta) for ranking designs without collapsing to a scalar reward. |

| **PLACER** | Constraint-free active-site geometry prediction | Recommended | Needs no `.cst`/theozyme file — predicts ligand and active-site geometry from a learned CSD+PDB prior. Architecturally orthogonal to Rosetta matching, so it is a genuine independent cross-check rather than a second opinion from the same assumptions. BSD-3, 61 MB weights, 1–3 s/sample on GPU. Added at user request. |
| **NetSolP + Aggrescan3D** | Developability — solubility and aggregation | Recommended | Closes a real coverage gap: a design can be stable *in silico* and unexpressible. Soft ranking signals only, never gates. Added at user request, explicitly designed for later supersession by robotic-lab measurement (Part B `09`, `decisions/0012`). |

Considered and not adopted: see `rejected-candidates.md`.

---

## 9. Risk register

| # | Risk | Severity | Evidence | Mitigation |
|---|---|---|---|---|
| **R1** | **Frontier cannot run the generative core.** No HIP path exists for foundry. | ~~High~~ **Accepted / scoped out** | Repo-wide grep of `tools/foundry` for `hip`/`rocm`/`amd`: zero hits. NVIDIA-oriented Docker image. | **Resolved by decision (`decisions/0008`):** Frontier deprioritized; Polaris/ACCESS primary, Aurora second. No spike scheduled. `frontier` stays in the site matrix with `gpu.api: hip` so composition is refused there rather than failing at runtime. If revisited: MPNN first, RF3 last. |
| **R2** | **Silent failure across the whole toolkit.** Tools complete successfully on invalid input or produce confidently wrong output. | **High** | Rosetta nonsense geometry; ligand mis-parameterization; high pLDDT on wrong domain orientation; `sha256=None` in every `REGISTERED_CHECKPOINTS` entry. | Post-hoc validation gates are mandatory, not optional. Every tool brief names its specific checks. Exit code is never sufficient evidence of success. |
| **R3** | **ColabFold MSA server is a shared single point of failure** for two Core tools. | **High** | Self-described free academic resource, ~few thousand MSAs/day aggregate globally; FAQ requests serial single-IP queries. Boltz retries `RATELIMIT` in an **uncapped** loop. | Monitor as one named dependency. Cache aggressively. Provision local MMseqs2 (768–1024 GB RAM) or a self-hosted server proactively. Never inherit the uncapped retry. |
| **R4** | **Budget exhaustion via naive `cartesian_ddg` use.** | **High** | 1–15 CPU-hr/mutation; ~3,800 mutations for a 200-residue saturation scan. | Cheap-screen-then-confirm. ML predictors first; physics on a shortlist of tens. |
| **R5** | **Aurora has no OpenMM GPU path.** | Medium | No SYCL platform exists; HIP is a separate AMD-maintained plugin. | GROMACS carries MD on Aurora; OpenMM degrades to CPU relaxation. |
| **R6** | **License gates block several tools.** | Medium | AF3 (discretionary, non-commercial), Chai-2 (partnership-only), FoldX (paid commercial), ESM-C/ESM3 (Cambrian NC, hosting prohibition). | All deferred pending explicit determination for a DOE/NSF mixed-user model. None is load-bearing; substitutes exist. |
| **R7** | **Oracle unavailability stalls the campaign.** | Medium | Demonstrated in this project: four subagents killed by HTTP 429 in one session. | Backoff honouring `Retry-After`; distinguish 429 from 529; checkpoint *before* each oracle call; explicit degraded-mode fallback to a deterministic policy. |
| **R8** | **Oracle non-determinism undermines reproducibility.** | Medium | Anthropic's API has no `seed`; temperature 0 does not guarantee determinism. | Full provenance logging of every prompt/response with pinned dated model ID and sampling params — treated on par with recording a Rosetta scorefunction version or a checkpoint hash. |
| **R9** | **Python floor conflict:** IMPRESS `>=3.9`, foundry `>=3.12`. | Low now | Verified in both `pyproject.toml` files. | Not blocking today — they integrate via subprocess/container boundaries. Forecloses future in-process integration without reconciliation. |
| **R10** | **Unaudited MCP servers as a supply-chain vector.** | Low–Medium | `Augmented-Nature` publishes official-looking `<Database>-MCP-Server` repos; third-party Rosetta server flagged low-trust. | Adopt only the two verified servers. Treat MCP adoption as a review decision. |
| **R11** | **P5 schema drift**, not just downtime. | Low–Medium | AlphaFold DB breaking-change migration with sunset **2026-06-25 — already passed**. A naive client may be silently receiving null fields now. | Validate response schemas; alert on unexpected nulls rather than propagating them. |
| **R12** | **Rosetta refcode documentation is unavailable.** | Low | `documentation/`, `demos/`, `rosetta_scripts_scripts/`, `pyrosetta_scripts/`, `PyRosetta.notebooks/` are all empty (uninitialized submodules). | All Rosetta claims sourced from `source/src` and `database/` instead. Initialize submodules if protocol-level docs are needed later. |

---

## 10. Hand-off to Parts B and C

Part A deliberately did not decide these. Each is a real open question the research surfaced.

**For Part B (agent architecture):**

1. **What is the agent's relationship to IMPRESS's `adaptive_fn`?** It is the existing adaptivity seam, and
   `examples/protein_binding/protein_binding_run.py` already contains a **working LLM-oracle precedent** —
   exactly the P5-oracle-inside-a-P7-pipeline integration control mode B describes. Study it before designing
   an alternative.
2. **Silent failure must be architectural, not incidental.** Given R2, validation gates belong in the task-agent
   contract (the post-processing responsibility already in scope), not scattered through tool wrappers.
3. **Patterns worth reimplementing, from prior art rather than invention:** AgentRosetta's tree-structured
   trajectory with non-destructive `go_back_to_step` (~45 lines) and its Pareto-front multi-objective selection;
   ChemGraph's `TaskSpec` with `is_async_remote`/`shares_filesystem` flags, its disk-persisted `JobTracker`, and
   its repeated-tool-call-cycle guard. None should be adopted as a dependency; `paretoset` is the one exception.
4. **Neither prior-art execution layer speaks PBS Pro.** `PyRosettaCluster` (dask-jobqueue) and AgentRosetta's
   blocking `sbatch --parsable --wait` are both SLURM/SGE-only, and Polaris and Aurora use PBS Pro. This is a
   direct argument for the rhapsody backend abstraction over adopting either.
5. **Decide the oracle's degraded-mode policy.** R7 makes this concrete: what does the agent do for the hour the
   API is unavailable, holding a multi-GPU allocation?

**For Part C (project structure):**

6. **P6 tools must be inlinable.** The structure has to make it natural to call RDKit or US-align in-process and
   unnatural to schedule them.
7. **The P4 durable job ledger is a first-class component**, not an afterthought — required by any tool that
   outlives the agent's allocation.
8. **Response caching for P5 is infrastructure**, shared across campaigns, keyed by request — the mitigation for
   R3 and R11 both.
9. **Provenance logging is a cross-cutting concern** spanning tool versions, model checkpoints, and oracle
   prompts (R8).

**Explicitly out of scope and worth confirming:** the toolkit closes its loop *in silico*. There is no
experimental-data ingestion path, so "autonomous" here means autonomous over computational experiments, not
over a design–build–test–learn cycle that includes the wet lab.
