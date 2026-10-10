# Rejected and Deferred Candidates

**Purpose.** The search brief was *curated additions with justification*, not an exhaustive survey. That only
means something if the curation is auditable. This file records what was considered and not adopted, and why —
so a later reader can tell the difference between "we decided against it" and "we never looked."

Every entry names the condition that would change the answer. A `Defer` is a decision to revisit, not a
dismissal.

---

## Rejected outright

| Candidate | Reason |
|---|---|
| **Chai-2** | Closed weights, available only through commercial partnership (e.g. Eli Lilly). No self-hosted path exists, so it cannot be deployed on our HPC targets under any arrangement we control. Nothing short of a licensing change would alter this. |

---

## Deferred — blocked by licensing or access

These are scientifically sound and would be adopted if the gate cleared. None is load-bearing; each has a
substitute already in the toolkit.

| Candidate | Gate | Substitute in use | What would change the answer |
|---|---|---|---|
| **AlphaFold3** | Weights require a manual, discretionary, **non-commercial-only** grant from DeepMind — incompatible with on-demand autonomous provisioning. Also still needs ~630 GB of local genetic databases with no remote-MSA option. | Boltz-2 (Core), RF3 (Core), ColabFold (Core) | Org-level weight access already secured and pre-staged, **and** confirmation that downstream use stays non-commercial. |
| **FoldX** | Free only under CRG's academic/non-profit license; commercial use requires a separately negotiated paid license (2-week evaluation only). | Rosetta `cartesian_ddg` (Core), ThermoMPNN (Core) | An explicit license determination for a DOE/NSF facility's mixed-user operating model. If it clears, promote to Recommended — it is cheaper per mutation than `cartesian_ddg` at comparable accuracy. |
| **ESM-C / ESM3** | EvolutionaryScale's Cambrian Non-Commercial License, including a prohibition on hosting behind an API. Whether a DOE/NSF facility deployment counts as non-commercial is unresolved. | MIT-licensed ESM2 and ESM-IF1 (Recommended) | A specific legal determination. Do not assume favorable. |
| ~~**Chai-1**~~ | **RESOLVED — promoted to Recommended.** The refcode was added (`tools/chai-lab`) and the brief rewritten from source. The suspected flash-attention CUDA lock-in did not exist; Apache 2.0 covers code and weights; the invocation surface and output fields are now verified. Carried alongside Boltz-2 for its no-MSA primary path and atom-level restraint grammar. | — | — |

---

## Deferred — superseded or not yet earning their place

| Candidate | Reason | What would change the answer |
|---|---|---|
| **LAMMPS** | A materials and soft-matter engine, not a biomolecular one. GROMACS and OpenMM already cover protein MD with better-maintained CHARMM/AMBER support. Its own bundled biomolecular examples (`examples/peptide`, `bench/rhodo`) are decades-old scaling benchmarks, not active workflows. Retained in the toolkit only because it was explicitly named. | Coarse-grained or Martini peptide models; protein-polymer materials work; MD driven by a learned interatomic potential via the `ML-IAP` package. |
| **HMMER / HH-suite** | AlphaFold2's canonical MSA pipeline, but MMseqs2 and the ColabFold server are far faster for equivalent practical sensitivity in our use cases. | Work where remote-homolog detection sensitivity is the binding constraint and MMseqs2 demonstrably misses hits. |
| **DiffDock** | Blind docking without a pocket definition is genuinely convenient, but its PoseBusters generalization collapse (≈12% success, a ~40-point drop on truly novel targets) makes it untrustworthy for exactly our use case — novel enzyme and binder targets. Boltz-2 covers the no-predefined-pocket case better via full co-folding. | A version that demonstrably closes the PoseBusters generalization gap. |
| **Rosetta `ddg_monomer`** | Superseded by `cartesian_ddg` on accuracy. | Reproducing legacy published results. |
| **PROSS** | **RESOLVED by decision.** Stabilization protocols will be expressed as **skill definitions** rather than registry entries, left as later work. The in-house-vs-webserver classification is therefore moot for now. | Revisit when stabilization skill definitions are authored. |
| **ProDy** | Assessed against Biotite and BioPython in `structure-libraries.md` and not recommended as primary. Biotite wins on speed and modernity; BioPython on ubiquity and interop. | A specific need for ProDy's normal-mode or ensemble analysis. |

---

## Considered and subsumed into another brief

Not separate entries, but investigated and folded in where they belong.

| Candidate | Where it lives |
|---|---|
| **ProstT5** | `foldseek.md` — it is the sequence-to-3Di model bundled in FoldSeek, not a standalone tool for us. |
| **SolubleMPNN** | `proteinmpnn-ligandmpnn.md` — a variant of the MPNN family, covered with it. |
| **Espaloma, Antechamber/GAFF, OpenFF** | `ligand-parameterization.md` — treated as four routes to the same job rather than four tools. |
| **Meeko** | `docking.md` and `cheminformatics-io.md` — the RDKit-`Mol`-to-PDBQT boundary crossing, not an independent capability. |
| **pdb2pqr / PROPKA** | `structure-prep.md` — protonation assignment, treated as a required companion step rather than an optional tool. |
| **`paretoset`** | `agent-rosetta.md` — a directly adoptable dependency for multi-objective selection, recommended in T7. |

---

## Not investigated — honest gaps

Named or implied during planning but not researched in this pass. Recorded so they are not mistaken for
considered-and-rejected.

| Candidate | Note |
|---|---|
| ~~**PLACER**~~ | **RESOLVED.** Refcode added (`tools/PLACER`); briefed at `briefs/placer.md`. Verdict Recommended as a constraint-free, architecturally orthogonal validation layer over Rosetta-matched active sites. |
| ~~**Expression / solubility / aggregation predictors**~~ | **RESOLVED.** Briefed at `briefs/developability-surrogates.md`. NetSolP and Aggrescan3D Recommended as soft signals; CamSol/SoluProt as ensemble members; Protein-Sol/AGGRESCAN/TANGO/WALTZ deferred on deployment friction and license gates. Designed for later supersession by robotic-lab measurement. |
| **Immunogenicity prediction** | Out of scope for the four stated problem classes; would matter for therapeutic work. |
| **Multi-state / ensemble design methods** | Relevant to switches and allostery. Not covered by any current brief. |
| **Experimental-data ingestion** | No *tool* consumes assay results, and none is proposed. But the **architecture now accommodates them**: Part B `09` defines the measurement seam (one `Property`, two sources) and the taxonomy forward-declares pattern **P8**. Ingesting results remains future work; being unable to model them does not. |
