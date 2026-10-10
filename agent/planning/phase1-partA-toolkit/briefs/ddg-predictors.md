# ML-based ΔΔG / stability predictors (ThermoMPNN, Stability Oracle, FoldX)

**One-line identity.** Fast, learned or empirical-potential point-mutation stability predictors — ThermoMPNN (ProteinMPNN-backbone, structure-conditioned deep learning), Stability Oracle (structure-based graph-transformer), and FoldX (empirical force-field, license-gated) — evaluated here specifically as the cheap-screening counterpart to Rosetta `cartesian_ddg` (briefed in `rosetta-ddg.md`).

None of the three are present in `impress-a-refcodes/tools/` (confirmed: no `thermompnn`, `stabilityoracle`, or `foldx` directory under `tools/`, mirroring `esmfold.md`'s situation). Everything below is WebSearch-derived from upstream papers, repos, and comparative-benchmarking literature, not independently reproduced or verified against vendored code. Numbers should be treated as reported-by-source, not re-derived.

---

## ThermoMPNN

### Identity
- **Version / release examined:** GitHub `Kuhlman-Lab/ThermoMPNN` (public repo, no local refcode). Companion extension `Kuhlman-Lab/ThermoMPNN-D` adds double-mutant prediction. Primary paper: Dieckhaus, Leman & Kuhlman, "Transfer learning to leverage larger datasets for improved prediction of protein stability changes," *PNAS* 121(6), 2024 (PMC10861915 / PMC10402116).
- **Provenance:** Kuhlman Lab, UNC Chapel Hill. Built as a lightweight fine-tuned head on top of a frozen or lightly-tuned ProteinMPNN backbone (same architecture family as `proteinmpnn-ligandmpnn.md`, but not the same weights or codebase). **License not independently confirmed in this search** — the repo is public on GitHub but its LICENSE file was not read; verify before treating it as a frictionless dependency the way ESMFold's MIT license is confirmed.
- **Maturity:** active research tool with real community uptake — hosted deployments exist on at least two third-party platforms (BioLM, Levitate Bio, Tamarind), which is a signal of practical adoption beyond the original lab, but not a signal of production-grade API stability.

### Scientific role
Structure-conditioned point-mutation ΔΔG prediction — the **score** stage, same role as Rosetta `cartesian_ddg`, for the **stability/thermostabilization** problem class. Takes a backbone structure plus a target position and predicts folding free-energy change for all 19 substitutions at that position in a single forward pass, rather than requiring one physics simulation per mutation. ThermoMPNN-D extends this to double mutants (relevant to combinatorial stabilization design, at reduced but still practical throughput).

### Invocation & I/O contract
- **How a unit of work is invoked:** Python/PyTorch, via the repo's inference notebook/scripts (`ThermoMPNN-D.ipynb` documents the pattern for the double-mutant variant); no CLI entrypoint comparable to `mpnn`'s `[project.scripts]` was found. Loads a structure (PDB/CIF), runs the ProteinMPNN-derived encoder once, then the ΔΔG head scores all requested substitutions from the shared embedding.
- **Inputs:** a structure file; optionally a position list (defaults to full site-saturation scan of every residue × 19 alternate amino acids).
- **Outputs:** a table of per-mutation predicted ΔΔG (kcal/mol-scale, sign convention: positive = destabilizing, matching Rosetta's convention per the comparative literature).
- **A concrete example:** not available from a repo-local example (no refcode present); the documented usage pattern (single structure in, full-scan ΔΔG table out) is consistent across all three third-party hosting platforms' documentation pages.

### Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job). One structure encode + one ΔΔG head forward pass covers an entire site-saturation scan — no per-mutation relaunch, unlike `cartesian_ddg`.
- **GPU vendor portability:** plausible-portable, unverified. Built on a ProteinMPNN-family encoder, which the `proteinmpnn-ligandmpnn.md` brief confirms has zero `cuequivariance` dependency and a pure-PyTorch device ladder including XPU — the same structural argument applies to ThermoMPNN's added transformer head, but this has not been independently confirmed for ThermoMPNN's own codebase, and no ROCm/XPU report was found for it specifically.
- **State model:** stateless per structure.
- **Data locality:** self-contained; one structure in, one score table out.
- **Staging burden:** model weights only, small (fine-tuned head weights on top of a ProteinMPNN checkpoint — tens of MB class, not multi-GB).
- **Container availability:** not established in this sweep; no official container found, third-party hosting (BioLM/Levitate/Tamarind) wraps it themselves rather than publishing a standard image.

### Deployment on DOE & ACCESS
No CUDA-only kernel dependency identified (inherited reasoning from the ProteinMPNN backbone) makes ThermoMPNN a plausible Frontier/Aurora candidate, but this is an inference from architectural similarity, not a verified deployment. Polaris/ACCESS: straightforward, standard PyTorch + small checkpoint. No license gate found blocking any platform (pending the license-verification caveat above).

---

## Stability Oracle

### Identity
- **Version / release examined:** GitHub `danny305/StabilityOracle` (public repo, no local refcode). CLI entrypoint documented as `scripts/run_stability_oracle.py`, with example invocations in `scripts/generate_predictions.sh`. Paper: Diaz, D.J. et al., "Stability Oracle: a structure-based graph-transformer framework for identifying stabilizing mutations," *Nature Communications* 15, 6170 (2024).
- **Provenance:** academic (authorship/affiliation not independently re-verified beyond the Nature Communications citation). **License not independently confirmed in this search.**
- **Maturity:** research-grade, single-paper release; less third-party hosting adoption found than ThermoMPNN in this search (no equivalent BioLM/Tamarind listing surfaced).

### Scientific role
Same **score** stage / stability problem-class role as ThermoMPNN, but a materially different architecture and training regime: pretrained on >2M masked amino-acid microenvironments (a self-supervised structural-context pretraining task, not fine-tuned directly from an inverse-folding model), then fine-tuned on a curated ~120K-mutation subset of the Tsuboyama/Megascale cDNA-display proteolysis dataset using a data-augmentation technique the paper calls **Thermodynamic Permutations (TP)** — augmenting training by permuting wild-type/mutant identity, which is directly relevant to (and a partial mitigation for) the antisymmetry problem discussed below, since it explicitly trains the model on both mutation directions rather than only the naturally-more-abundant destabilizing direction.

### Invocation & I/O contract
- **How a unit of work is invoked:** Python CLI, `python scripts/run_stability_oracle.py` per the repo's documented usage pattern (exact flag set not independently verified beyond the general pattern reported in search results).
- **Inputs:** a structure file plus mutation specification (per-position or full-scan, analogous to ThermoMPNN).
- **Outputs:** per-mutation predicted ΔΔG and, notably, a **stabilizing/destabilizing classification** output alongside the regression score (the paper reports both regression and classification metrics, distinct from ThermoMPNN's pure-regression framing).
- **A concrete example:** repo ships example datasets/predictions under a `data/` directory per search results; not independently read.

### Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job), same reasoning as ThermoMPNN — a graph-transformer forward pass over a structural microenvironment per mutation, batchable.
- **GPU vendor portability:** plausible-portable, unverified — graph-transformer architectures are typically pure-PyTorch/PyG, but no explicit CUDA-kernel-dependency check was performed against this specific repo.
- **State model:** stateless per structure.
- **Data locality:** self-contained.
- **Staging burden:** model weights, small-to-moderate (a pretrained microenvironment encoder plus a fine-tuned head; exact size not found).
- **Container availability:** not established; no official container found.

### Deployment on DOE & ACCESS
Same general picture as ThermoMPNN: no confirmed platform blocker, but also no confirmed positive deployment evidence on Frontier/Aurora. Treat identically to ThermoMPNN as an unverified-portability P1 GPU tool pending a pilot.

---

## FoldX

### Identity
- **Version / release examined:** FoldX Suite, distributed as dated closed-source binary builds (e.g. `foldx5`) via the CRG (Centre for Genomic Regulation) licensing portal — no version pin available from a local file since it is not, and cannot be, vendored in an open refcode collection.
- **Provenance:** originally Schymkowitz/Serrano labs; currently maintained and licensed by CRG (Barcelona). **Closed-source, license-gated binary — this is the load-bearing fact for this entry.**
- **Maturity:** mature, long-established (the empirical-potential ΔΔG tool most frequently cited alongside Rosetta in the literature; the Ssym benchmark study cited in `rosetta-ddg.md` reports FoldX and Rosetta cartesian ΔΔG protocols as comparably accurate, r≈0.63).

### Scientific role
Empirical-force-field point-mutation ΔΔG prediction — same **score** stage. Conceptually closer to Rosetta than to the two ML predictors above: FoldX evaluates a parameterized energy function over relaxed wild-type and mutant structures rather than learning a mapping end-to-end from data, so its accuracy/cost profile sits between physics-based Rosetta and the ML predictors, but its licensing profile is categorically different from all three other tools in this toolkit sweep.

### Invocation & I/O contract
- **How a unit of work is invoked:** CLI binary, documented public usage pattern (not refcode-verified):
  ```
  foldx --command=RepairPDB --pdb=input.pdb
  foldx --command=BuildModel --pdb=input_Repair.pdb \
        --mutant-file=individual_list.txt --numberOfRuns=5
  ```
  A Python wrapper, `pyFoldX`, exists (Oxford Bioinformatics 2022) for programmatic/ensemble-oriented automation and is the more agent-friendly invocation surface than raw CLI + flat-file config.
- **Inputs:** a PDB structure and a semicolon-terminated mutation list (`individual_list.txt`, e.g. `KA6R;`); a `RepairPDB` pre-pass is required before `BuildModel` to relax clashes/rotamers in the input structure.
- **Outputs:** `Dif_<name>.fxout`, a per-mutation ΔΔG table (kcal/mol) averaged over `numberOfRuns` replicate builds.
- **A concrete example:** the `RepairPDB` → `BuildModel` two-step pattern above is the standard, widely-documented FoldX workflow across public tutorials; not drawn from a repo-local example since none is vendored.

### Compute pattern
- **Pattern:** P2 (CPU-parallel fan-out, in-job) — CPU-only, no GPU; each mutation (or replicate build) is independent and embarrassingly parallel, same shape as Rosetta `cartesian_ddg`.
- **GPU vendor portability:** n/a — CPU-only by design.
- **State model:** restart-required per mutation, checkpointable at the mutation-list granularity (same reasoning as `cartesian_ddg`).
- **Data locality:** self-contained.
- **Staging burden:** none beyond the licensed binary itself.
- **Container availability:** n/a / license-gated — a container could in principle bundle the binary, but redistribution is constrained by the same license that gates the binary itself; do not bake FoldX into a shared/public container image without confirming the license permits it.

### Deployment on DOE & ACCESS
CPU-only, so no Frontier/Aurora/Polaris GPU-portability question at all — the only blocker is licensing, not compute. **Licensing, stated plainly: FoldX is free only for "public funded academic and/or education and/or research institution[s]" registering for the Academic License; commercial use requires a separately negotiated paid license (contact `CRG_BusinessInnovation@crg.eu`), with only a 2-week fully-featured evaluation license available pre-purchase.** This is not "free software" in the sense that Rosetta (UW-CoMotion academic license, already gated per `rosetta.md`/`rosetta-ddg.md`) or the MIT-licensed ML tools in this toolkit are — it is a narrower, institution-registered academic grant with an explicit commercial carve-out, and redistribution/bundling terms should be checked before any container or shared-deployment plan is built around it. Whether a DOE-leadership or NSF ACCESS facility serving mixed academic/industry-affiliated allocations cleanly qualifies for the academic tier is a licensing question to resolve explicitly with CRG before depending on FoldX in production, not an assumption to make silently.

---

## Agentic surface
- **Native MCP:** no for all three (no MCP server found for ThermoMPNN, Stability Oracle, or FoldX in this search; the `zeinab-sheikhi/mcp-alphafold` community server referenced in `esmfold.md` was reported to cover "ESM-2/ESMC embeddings, mutation scoring" — not ThermoMPNN/Stability Oracle/FoldX specifically — so it does not extend coverage here).
- **Parameters worth exposing for autonomous variation:**

| Parameter | Tool | Type | Sane range | Trade-off |
|---|---|---|---|---|
| position list / full-scan toggle | ThermoMPNN, Stability Oracle | selector | single position → whole-protein scan | scan width is nearly free (one encoder pass) — default to full scan rather than pre-filtering positions |
| `numberOfRuns` | FoldX | int | 3–10 | more replicate builds → tighter ΔΔG estimate, linear CPU cost; FoldX's own docs recommend ≥5 for a stable mean |
| model checkpoint (structure-based vs. any sequence-noise-augmented variant) | ThermoMPNN | enum | per-release checkpoints | should match the noise regime the checkpoint was trained on, same caveat as MPNN's `structure_noise` parameter |
| score-agreement threshold across predictors | agent-level, not a tool flag | float | task-defined | see ensembling strategy below — not a native parameter of any one tool |

- **Parameters that must NOT be agent-varied:** the `RepairPDB` pre-step for FoldX must never be skipped to save time — running `BuildModel` on an un-repaired structure is a well-documented silent-quality-degradation footgun in the FoldX community (clashes/bad rotamers in the input propagate into both wild-type and mutant energies, partially cancelling but not reliably); FoldX's `numberOfRuns=1` should not be used for any result an agent will act on (single-run estimates are noisy and not representative of the tool's real accuracy).

## Failure modes & what the agent must check

### The antisymmetry problem (run this check — it is free)
ΔΔG(A→B) should equal −ΔΔG(B→A). This is a **zero-cost internal-consistency check an agent can run on any predictor for free** — score both directions and check the sum is near zero — and it is directly diagnostic of predictor trustworthiness, independent of any experimental ground truth.

- **ThermoMPNN is not explicitly constructed to be antisymmetric.** On Ssym/p53/myoglobin test sets, both forward and reverse mutation performance stay above Pearson r≈0.60, but the **forward-reverse correlation collapses specifically for the stabilizing-mutation subset** (reported R≈−0.27 against an ideal of −1.0 for a perfectly antisymmetric predictor) — i.e., precisely where an autonomous stabilization campaign is looking, ThermoMPNN's antisymmetry is weakest. This is the single most important number in this brief for gate design: **do not trust a raw ThermoMPNN "this mutation is stabilizing" call without also scoring the reverse mutation and checking the sum is near zero.**
- **Stability Oracle's Thermodynamic Permutation training augmentation is a direct attempt to address this** by training on both mutation directions rather than the naturally destabilizing-skewed data; no independently-verified quantitative antisymmetry-violation figure for Stability Oracle was found in this search (flag as needs-verification before relying on it as an improvement over ThermoMPNN on this specific axis).
- **Rosetta `cartesian_ddg` also imperfectly respects antisymmetry** (already noted in `rosetta-ddg.md`, motivating the Ssym+ benchmark's existence) — this is a field-wide problem, not a ThermoMPNN-specific weakness, and other published architectures explicitly engineered for exact antisymmetry (e.g., architecturally-constrained models achieving near-perfect direct/reverse bias under 0.05 kcal/mol) exist in the literature but are not among the three tools briefed here.
- **What the agent must check:** for any mutation an autonomous loop is about to act on (synthesize, commit compute to a physics confirmation, etc.), score both the forward and reverse mutation with the same predictor and require `|ΔΔG_fwd + ΔΔG_rev|` below a task-defined tolerance (e.g. 1 kcal/mol) before trusting the forward score at all. A mutation that fails this check should be down-weighted or routed to Rosetta confirmation regardless of how favorable its raw score looks.

### Train/test leakage — discount published accuracy
**Published accuracy numbers in this field are frequently inflated by data leakage and should not be taken as ground truth for out-of-distribution performance.** Two documented leakage modes: *inter-protein* leakage (near-duplicate/homologous proteins split across train/test) and *intra-protein* leakage (different mutations at the same position of the same protein split across train/test, letting a model memorize position-level context rather than learning mutation-level physics). Conventional n-fold cross-validation over point-mutation datasets is specifically flagged in the literature as prone to this, and "hidden reverse mutations" appearing in both training and evaluation splits is a named, concrete leakage vector directly relevant to the antisymmetry discussion above. Leave-one-protein-out (LOPO) evaluation is the recommended mitigation and is not universally used by every paper cited in this brief.

**Concrete implication:** ThermoMPNN's headline Spearman ρ≈0.73 on the Megascale/Tsuboyama test set is measured on data drawn from the same 28-protein experimental campaign its transfer-learning approach is built to exploit — treat that number as an **in-distribution ceiling, not a generalization estimate.** The more informative numbers for judging real-world generalization are the independent-benchmark figures (Ssym, S461/S669) reported above, all of which cluster in the r≈0.6–0.7 band across ThermoMPNN, Stability Oracle, FoldX, and Rosetta cartesian_ddg alike — meaning that **on genuinely held-out data, the ML predictors' accuracy advantage over physics-based Rosetta is much smaller than their in-distribution numbers suggest, even though their cost advantage is enormous (see below).** An autonomous agent should be actively suspicious of any single-number accuracy claim that doesn't state its train/test split methodology, and should prefer benchmarking a new predictor release on its own homology-reduced local holdout before trusting it as a gate.

### Which signals are safe as autonomous accept/reject gates vs. soft ranking only

| Signal | Gate or ranking-only? | Why |
|---|---|---|
| ThermoMPNN/Stability Oracle raw ΔΔG point estimate | **Ranking only.** | Leakage-inflated headline accuracy, imperfect antisymmetry, no uncertainty estimate attached to a single forward pass |
| Forward/reverse antisymmetry check (self-consistency, any predictor) | **Safe as a gate.** | Free, requires no ground truth, directly diagnostic — a large violation is informative regardless of which direction is "correct" |
| Stability Oracle stabilizing-mutation classification (74% precision / 48% recall on its own reported figures) | **Weak inclusion signal only, never an exclusion gate.** | High-ish precision means a positive call is worth shortlisting; low recall means a negative call cannot be trusted to exclude true positives — using it to reject candidates would discard roughly half the real stabilizing mutations |
| Rosetta `cartesian_ddg` replicate spread (not the point mean) | **Usable as a soft gate** (already established in `rosetta-ddg.md`) — tight-spread, moderate-magnitude predictions are the most trustworthy tier across this whole cluster | Physics-grounded, and the spread itself is a built-in uncertainty estimate the ML predictors lack |
| Final accept for any downstream commitment (expression, further costly compute, campaign pivot) | **Never on ML ΔΔG alone.** | No predictor in this cluster has demonstrated leakage-free accuracy strong enough to license an irreversible or expensive downstream action without physics or experimental confirmation |

## Cost per unit of work
- **ThermoMPNN / Stability Oracle (ML predictors):** a full site-saturation scan (all 19 substitutions × every position) of a ~100-residue protein completes in **~2 seconds on a single GPU**; a ~700-residue protein in **~8 seconds** (ThermoMPNN figures; Stability Oracle's per-mutation cost is architecturally similar — one structural-microenvironment forward pass per mutation, GPU-batchable, not independently re-benchmarked here). This is **effectively free per mutation** at any campaign-relevant scale: a saturation scan that would cost several thousand to tens of thousands of CPU-hours via `cartesian_ddg` (per `rosetta-ddg.md`'s own cost estimate) costs single-digit GPU-seconds via ThermoMPNN — on the order of a **10⁶–10⁷× speedup**, not merely "orders of magnitude" loosely stated.
- **FoldX:** CPU-only, no GPU needed; a single `BuildModel` mutation with `numberOfRuns=5` typically completes in low seconds to tens of seconds on one core (well-documented community figures, not independently benchmarked here) — far cheaper than `cartesian_ddg`'s 1–15 CPU-hours/mutation, but not free-per-mutation the way the ML predictors are, since each mutation still triggers its own relax/repack cycle rather than sharing one encoder pass across an entire scan.
- **Rosetta `cartesian_ddg` (for contrast, from `rosetta-ddg.md`):** ~1–15 CPU-hours/mutation, r≈0.63–0.66, MAE≈1.39 kcal/mol on independent benchmarks.
- **Checkpointable:** ThermoMPNN/Stability Oracle calls are sub-minute — per the taxonomy's P6 guidance for sub-second/sub-minute work, these should never be individually scheduled/checkpointed; batch an entire scan as one P1 call. FoldX is checkpointable at the mutation-list granularity, same as `cartesian_ddg`.

### Recommended strategy: cheap screen, expensive confirm
Given the cost gap above, the natural policy is a **two-stage funnel**: run ThermoMPNN (and, budget permitting, Stability Oracle in parallel as a cross-check — see ensembling note below) as a **full saturation scan across every candidate position on every backbone**, at near-zero marginal cost; apply the antisymmetry self-consistency gate to the resulting candidate list; then take only the **top shortlist** — order of **tens to low hundreds of mutations per campaign iteration**, not the full scan — forward to `cartesian_ddg` for physics-grounded confirmation before committing any mutation to expression or further costly compute. The cutover width should be sized against the CPU-hour budget actually available: at 1–15 CPU-hours/mutation, a 100-mutation shortlist already costs 100–1,500 CPU-hours, which is a meaningful fraction of most allocation-scale budgets — **the ML stage's job is not to find "the answer," it is to make the physics stage's width tractable.** Where ThermoMPNN and Stability Oracle disagree substantially on the same mutation (an ensembling signal available essentially for free, since both are cheap enough to run on the full scan), treat disagreement itself as a reason to prioritize that mutation for Rosetta confirmation rather than trusting either raw score — disagreement between two differently-trained, differently-architected models is a more informative uncertainty signal than either model's own (absent) confidence estimate.

## Verdict
**ThermoMPNN: Core.** It is the load-bearing cheap-screening tool for the stability/thermostabilization problem class — fast enough to make full saturation-mutagenesis scans routine, with independently-benchmarked accuracy (Ssym/S669-class, r≈0.6–0.7) in the same band as Rosetta cartesian_ddg despite being many orders of magnitude cheaper, and a documented (if imperfect) antisymmetry story that the agent can self-check for free. Its in-distribution Megascale number (ρ≈0.73) should be discounted per the leakage discussion above and never quoted as a generalization guarantee.

**Stability Oracle: Recommended.** Real, independently-trained-and-architected value as a second predictor for cheap ensembling/disagreement-detection against ThermoMPNN, with a training-time mitigation (Thermodynamic Permutations) directly aimed at the antisymmetry weakness ThermoMPNN has been shown to have — but its license is unconfirmed, its third-party adoption/hosting footprint is thinner than ThermoMPNN's, and its own antisymmetry-violation magnitude has not been independently quantified in this search. Verify license and pilot before treating it as equally load-bearing as ThermoMPNN.

**FoldX: Defer.** Scientifically comparable in accuracy to Rosetta cartesian_ddg (same Ssym-era r≈0.63 figure, per `rosetta-ddg.md`) at meaningfully lower CPU cost per mutation than `cartesian_ddg`, and CPU-only with no GPU-portability risk at all — but it is the one tool in this entire three-tool cluster with a real, explicit commercial/institutional license gate rather than an open-source or standard academic-research license, and that gate must be resolved with CRG before any deployment decision, not assumed away. If the license clears for this project's operating model, FoldX is worth promoting to Recommended as a second-opinion physics-adjacent check that is cheaper than `cartesian_ddg`; until then it stays out of the default pipeline.

## Sources
- ThermoMPNN: `github.com/Kuhlman-Lab/ThermoMPNN`, `github.com/Kuhlman-Lab/ThermoMPNN-D`; Dieckhaus, Leman & Kuhlman, *PNAS* 121(6) 2024 (PMC10861915, PMC10402116); third-party hosting docs (BioLM, Levitate Bio, Tamarind) for inference-speed and usage-pattern figures — WebSearch, not independently reproduced.
- Stability Oracle: `github.com/danny305/StabilityOracle`; Diaz, D.J. et al., *Nature Communications* 15, 6170 (2024) (also bioRxiv 2023.05.15.540857) — WebSearch, not independently reproduced.
- FoldX: `foldxsuite.crg.eu` (licensing pages: `/licensing-and-services`, `/evaluation-license-terms`, `/foldx4-academic-licence`); pyFoldX, *Bioinformatics* 38(8), 2022 — WebSearch, not independently reproduced.
- Antisymmetry figures (ThermoMPNN Ssym R≈−0.27 on stabilizing subset; general 0.26–0.50 kcal/mol systematic offsets; OmeDDG/GGL-PPI2 as counterexamples achieving near-perfect antisymmetry by architecture): WebSearch of comparative literature, including "Constraint-Aware Optimization for Robust Protein Stability Prediction" (arXiv 2606.08100) and OmeDDG (*J. Phys. Chem. B* 128(1), 2024) — not independently re-derived.
- Data-leakage discussion: WebSearch synthesis of multiple 2023–2024 sources on inter-/intra-protein leakage and LOPO evaluation in ΔΔG prediction benchmarking (PMC10062539, PLOS ONE 0283727, and related).
- `rosetta-ddg.md` (this directory) — cross-referenced for `cartesian_ddg` cost/accuracy figures (1–15 CPU-hr/mutation, r≈0.63–0.66, MAE≈1.39 kcal/mol) rather than re-deriving them.
- `proteinmpnn-ligandmpnn.md` (this directory) — cross-referenced for the ProteinMPNN-backbone GPU-portability reasoning applied by inference to ThermoMPNN.
