# US-align (TM-align / TM-score)

**One-line identity.** Sequence-independent structural superposition and TM-score calculator that computes the field-standard **self-consistency check** — did my designed sequence, once folded, actually reproduce the backbone I asked for?

## Identity
- **Version / release examined:** no refcode present in `impress-a-refcodes/tools/` (confirmed absent from the tools directory listing). Sourced from upstream GitHub `pylelab/USalign`; most recent documented change at time of research: 2026-09-20 (bug fix in `-mm 1` with `-se` and `-outfmt 2`), with other recent fixes dated 2026-08-13/14 and 2026-03-28 — actively maintained.
- **Provenance:** Zhang Lab (originally) / now maintained at `pylelab/USalign` on GitHub, single-file C++ source (`USalign.cpp`). License: a permissive academic-use license ("permission to use, copy, modify, and distribute this program for any purpose, with or without fee," with attribution requirements) — not a standard OSI license string, but unrestrictive for research use; free precompiled binaries and a bioconda package (`bioconda::usalign`) also exist.
- **Maturity:** production. US-align is the actively-developed successor/superset of the classic TM-align and TM-score tools, unifying protein, RNA, and DNA structure alignment plus multi-chain complex alignment (MM-align lineage) into one binary.

## Scientific role
US-align/TM-align computes a **sequence-independent, length-normalized structural similarity score (TM-score)** and an optimal superposition (rotation + translation + RMSD) between two structures. This is not a design or prediction tool — it is the **comparison/analyze** stage tool that closes the loop on every other generative step in the toolkit.

**The self-consistency loop, and why this tool is load-bearing for it:**
1. RFdiffusion3 generates a backbone.
2. ProteinMPNN designs a sequence for that backbone.
3. A folding model (AlphaFold2/ColabFold, ESMFold, Boltz-2, Chai) predicts the structure the designed *sequence* actually folds into.
4. **US-align/TM-align computes RMSD and TM-score between the predicted structure and the original designed backbone.**

Step 4 is the accept/reject gate for the entire campaign: if the predicted structure doesn't match the design intent, the design is discarded regardless of how confident the folding model's own pLDDT was. Field-standard thresholds actually used in de novo design papers:

- **scRMSD < 2.0 Å** — the dominant self-consistency criterion in modern backbone-design literature (RFdiffusion and derivatives). A design is typically called "designable" if **at least one of ~8 MPNN-sequence/refold trials** achieves scRMSD < 2.0 Å against the original backbone. This is more stringent than TM-score-based scTM because RMSD is a local metric, sensitive to minor structural deviations that a global TM-score would average away.
- **TM-score ≥ 0.5** — the field-standard threshold for "same fold" in general structure-comparison literature (this is *not* usually the self-consistency gate itself, but the threshold used when asking "is this structure the same overall fold as a reference," e.g., novelty/precedent comparisons layered on top of a Foldseek hit, or scTM-style self-consistency scoring as an alternative/complement to scRMSD). TM-score > 0.5 corresponds to "the same fold in SCOP/CATH" with probability > 0.5; scores below ~0.17 correspond to structurally unrelated/random pairs.
- Multimer/complex self-consistency (binder design, enzyme active-site geometry) uses the same RMSD/TM-score logic but computed in **complex mode** (see below) so that interface geometry, not just per-chain fold, is being checked.

Applicable to all four in-scope problem classes: stability (does a stabilized variant retain the parent fold?), de novo binder design (does the designed binder backbone reproduce under refolding, and does the complex interface hold?), enzyme design (does the active-site geometry survive refolding?), small-molecule binding (does the pocket-bearing backbone hold?). Pipeline stage: **analyze**.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI only (binary `USalign`, plus the legacy-compatible `TMalign`/`TMscore` entrypoints built from the same source tree). Compilation: `make`, or directly `g++ -static -O3 -ffast-math -lm -o USalign USalign.cpp` (drop `-static` on macOS; compatible with g++ 4.8.5+, clang++ 12.0.5+, mingw-w64 9.3+).
  - Basic pairwise alignment: `./USalign structure1.pdb structure2.pdb`
  - Full option listing: `./USalign -h`
  - Multimer/complex mode: the `-mm` flag family controls complex alignment — `-mm 1` performs (as of recent bugfixes, now-symmetric) whole-complex alignment; `-mm 2`/`-mm 4` support `-full` for chain-level alignment detail; `-mm 6` handles large-complex chain-assignment refinement; `-mm 7` is a flexible-structure alignment mode with color-coded region output via `-o`.
  - Chain selection/mapping: `-chain1`, `-chain2`, `-chainmap`.
  - Sequence-guided superposition (skip re-alignment, use existing residue correspondence): `-byresi` (values 4-7).
  - Circular permutation alignment: `-cp`.
  - Visualization export: `-rasmol`, `-chimerax`.
- **Inputs:** PDB or PDB-like coordinate files (protein, RNA, or DNA structures); no sequence file needed — alignment is purely structural (though `-seq` can force TM-score superposition via sequence alignment instead of structure-based DP).
- **Outputs:** TM-score (normalized by query length, target length, or their average, depending on flag), RMSD over the aligned region, a rotation matrix + translation vector, and (optionally) a superposed PDB file for visualization. `-outfmt` controls machine-parseable vs. human-readable output.
- **A concrete example** (from upstream documentation, not a local refcode — flagged as web-sourced):
  ```
  ./USalign model_predicted.pdb model_design.pdb -mm 1 -outfmt 2
  ```
  for a two-structure complex self-consistency comparison with parseable tabular output.

## Compute pattern
- **Pattern:** P6 (in-process library call) primary, but scheduled as P2 (CPU-parallel fan-out) when run as a standalone batch of pairwise comparisons across a design campaign. Per taxonomy rule 1 (classify by dominant cost): a single US-align invocation is sub-second to low-seconds for typical single-domain proteins — cheap enough that the execution layer should **never** schedule one comparison as its own task (P6 discipline per the taxonomy's own rationale: "scheduling overhead would exceed the work"). A batch of thousands of self-consistency checks across a generation run, however, is naturally P2 fan-out (embarrassingly parallel over independent pairs).
- **GPU vendor portability:** n/a — CPU-only, no GPU code path exists or is claimed anywhere in upstream documentation. Runs identically on every target platform for exactly that reason (no vendor lock-in risk).
- **State model:** stateless (single invocation, no checkpoint needed given sub-second-to-seconds runtime).
- **Data locality:** self-contained (single-file binary, operates on local PDB files, no database dependency).
- **Staging burden:** none.
- **Container availability:** n/a in practice — the tool is a single statically-compilable C++ file; no official container is necessary or was found, and building it inside any existing Apptainer image (e.g., alongside PyRosetta or a folding-model container) is trivial (one `g++` invocation).

## Deployment on DOE & ACCESS
Zero platform risk. Because it is CPU-only, self-contained, and compiles with a single `g++`/`make` call with no external dependencies, US-align runs identically on Frontier, Aurora, Polaris, and all three ACCESS systems. The only "deployment" decision is whether to build it once and bake it into every container that also runs a folding model (recommended — since it is always invoked immediately after a folding prediction in the self-consistency loop, colocating the binary avoids an extra container pull mid-pipeline) or install it as a lightweight module/conda package (`bioconda::usalign`). No license gate blocks any of this.

## Agentic surface
- **Native MCP:** no. No MCP server for US-align/TM-align/TM-score was found. Given the tool's trivial CLI surface and P6 in-process-call nature, an MCP wrapper is unnecessary overhead — the execution layer should call the binary directly and parse its output, not route it through a tool-server round trip.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `-mm` | enum {0,1,2,4,5,6,7} | — | 0 (monomer) | Selects monomer vs. complex/multimer alignment mode; must be set to a complex mode for binder/enzyme-complex self-consistency checks |
| TM-score normalization target | choice (query/target/average length) | — | tool-specific default | Determines what "TM-score" means for a given comparison — an agent must be consistent about which length it normalizes by across a campaign, or scores are not comparable run-to-run |
| `-cp` | bool | 0/1 | 0 | Enables circular-permutation-aware alignment; only relevant for specific scaffold-topology design cases, not a general default |
| `-byresi` | enum {4,5,6,7} | — | off | Skips re-alignment and superposes by existing residue numbering — useful when comparing a design to its own refold (residue correspondence is already known and trusted), risky if residue numbering has silently drifted between the two files |

- **Parameters that must NOT be agent-varied:** the accept/reject **threshold itself** (scRMSD < 2.0 Å, TM-score ≥ 0.5) should be a pinned campaign-level policy constant, not something the agent tunes per-design to make a marginal result pass — that is the definition of gate-gaming and silently invalidates the self-consistency metric's purpose. The normalization mode (which length TM-score is divided by) must stay fixed within a campaign for the same reason.

## Failure modes & what the agent must check
- **Loud failure:** non-zero exit or empty output on malformed/empty PDB input, or on multimer mode when chain count/composition genuinely can't be reconciled between the two structures (though see the bug-fix history below — some of these were previously *silent* asymmetry bugs, now fixed).
- **Silent bad output:** the most consequential documented case: an **asymmetric alignment bug in `-mm 1`** where oligomer alignment output depended on input file order — i.e., `USalign A.pdb B.pdb -mm 1` and `USalign B.pdb A.pdb -mm 1` could silently disagree, which is exactly the kind of bug that corrupts a self-consistency comparison without throwing any error. This was patched in the 2026-03-28 and 2026-08-13/14 updates and again 2026-09-20 (per upstream changelog) — the agent's toolchain must pin a US-align build at or after these fixes, and the coverage matrix should record which build/commit is deployed. More generally: a TM-score computed with mismatched normalization (query-length vs. target-length vs. average) between two runs will look like a valid score while being non-comparable — always log which normalization mode was used alongside the number.
- **Post-hoc check:** for any complex/multimer self-consistency check, run the comparison in both argument orders once during pipeline validation (not per-design, just once when standing up the deployment) to confirm the installed build doesn't exhibit the pre-fix asymmetry; log the RMSD, TM-score, *and* normalization mode together so a downstream reviewer (human or agent) can audit the accept/reject decision.

## Cost per unit of work
- Single pairwise structural alignment (typical 100-400 residue monomer): sub-second to a few seconds on one CPU core. Complex/multimer mode (`-mm`) costs more (larger search space over chain permutations/mappings) but is still seconds-scale for typical binder-sized complexes (a few hundred to low-thousand residues total).
- A full self-consistency batch (e.g., 8 MPNN sequences × 1 refold each × 1 US-align comparison per design, across hundreds of designs per campaign iteration) is thousands of sub-second calls — this is the textbook P6-vs-P2 boundary case from the taxonomy: each call is P6-cheap, but the aggregate batch should be scheduled as P2 fan-out (e.g., one job array or one multi-core batch script iterating the comparisons), never as thousands of individually-scheduled tasks.
- Not checkpointable in any meaningful sense (runtime is too short for checkpointing to matter); restart cost on failure is trivial (rerun the single comparison).

## Verdict
**Core.** This is the tool that makes the self-consistency loop — the single most important accept/reject mechanism in modern de novo protein design — actually computable. Every other generative or predictive tool in this toolkit (RFdiffusion3, ProteinMPNN, AlphaFold2/ColabFold, ESMFold, Boltz-2, Chai) produces an artifact that this tool then judges against the design intent. It is cheap, portable across every target platform with zero GPU-vendor risk, and has no viable substitute for TM-score computation at this speed and reliability. The one operational caveat, not a reason to downgrade the verdict: pin a post-2026-08 build to avoid the documented `-mm 1` asymmetry bug, and bake the accept/reject thresholds (scRMSD < 2.0 Å; TM-score ≥ 0.5 for "same fold") into campaign-level policy rather than leaving them agent-tunable.

## Sources
- No refcode present (verified absence via `ls <workspace>/impress-a-refcodes/tools/`)
- US-align GitHub: https://github.com/pylelab/USalign (fetched directly; compile instructions, `-mm` flag family, license text, and changelog dates quoted/paraphrased from this source)
- Zhang Lab US-align page: https://zhanggroup.org/US-align/
- TM-score background / 0.5-threshold-for-same-fold: Zhang & Skolnick, TM-score description at https://zhanggroup.org/TM-score/ ; Xu & Zhang, "How significant is a protein structure similarity with TM-score = 0.5?" (referenced via search results, not independently re-read — flagged as inferred)
- Original TM-align paper: Zhang & Skolnick, "TM-align: a protein structure alignment algorithm based on the TM-score," Nucleic Acids Research 2005, https://academic.oup.com/nar/article/33/7/2302/2401364
- scRMSD < 2.0 Å self-consistency threshold, "8 sequences, at least 1 passing" convention: MotifBench (arXiv:2502.12479, https://arxiv.org/html/2502.12479v2) and general RFdiffusion/ProteinMPNN self-consistency literature (web-searched summary, not independently re-derived from the primary RFdiffusion paper — flagged as inferred and recommended for spot-check against the RFdiffusion3 brief if one exists in this toolkit)
- bioconda package: https://anaconda.org/bioconda/usalign
