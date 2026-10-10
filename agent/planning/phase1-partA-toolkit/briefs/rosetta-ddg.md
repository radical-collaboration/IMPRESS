# Rosetta ΔΔG protocols (cartesian_ddg, ddg_monomer, PROSS)

**One-line identity.** Rosetta's point-mutation stability-prediction protocols — `cartesian_ddg` (current, Cartesian-space, `talaris`→`ref2015`/`beta_nov16`-era) and `ddg_monomer` (legacy, torsion-space, `score12`/`talaris2013`-era) — plus PROSS, a phylogenetics-guided multi-mutation stabilization method built on top of Rosetta design but not present in this refcode.

## Identity
- **Version / release examined:** `cartesian_ddg` app: `source/src/apps/public/ddg/cartesian_ddg.cc` (519 lines), backing mover `source/src/protocols/ddg/CartesianddG.cc/.hh` (1177 lines, authors Brandon Frenz, Frank DiMaio, Hahnbeom Park). `ddg_monomer` app: `source/src/apps/public/ddg/ddg_monomer.cc` (602 lines, author Liz Kellogg). Both are apps within the `tools/rosetta` refcode examined above (same version context as `rosetta.md`: no static release tag, `git describe`-derived).
- **Provenance:** RosettaCommons. PROSS is a *separate* tool (Weizmann Institute, Goldenzweig/Fleishman labs, served at pross.weizmann.ac.il) that orchestrates Rosetta `FastDesign`/`FastRelax`-style calculations plus a phylogenetic PSSM filter; **it is not present anywhere in `tools/rosetta/` in this refcode** — no `pross` hits anywhere under `source/src` or the repo root. Everything said about PROSS below is from public literature/web search, not the refcode, and is marked as such.
- **Maturity:** `cartesian_ddg` — production, actively maintained, the currently-recommended ΔΔG protocol per RosettaCommons documentation. `ddg_monomer` — legacy/production-but-superseded; still present and functional but built around older score functions. PROSS — active research-grade webserver, not vendored here.

## Scientific role
Serves the **stability/thermostabilization** problem class directly — this is the load-bearing quantitative tool for that class in the whole toolkit. Pipeline stage: **score** (ΔΔG is a scalar prediction per mutation, not a structure generator), operating on an existing structure (from a PDB, a homology model, or an AlphaFold/RFdiffusion-adjacent structure prediction upstream of this toolkit).

- **cartesian_ddg**: for each requested point mutation, builds wild-type and mutant ensembles via Cartesian-space `FastRelax` restricted to a local neighborhood (a repack/min "cartesian sampler," `protocols::hybridization::CartesianSampler`, internally), then reports ΔΔG = mean(mutant scores) − mean(wild-type scores) over converged low-energy states.
- **ddg_monomer**: older protocol, uses `protocols::ddg::ddGMover` with torsion-space repack/minimize and the `score12`/`talaris2013`-era weight sets; retained mainly for reproducing older benchmark comparisons, not for new work.
- **PROSS** (not in refcode): combines a phylogenetic PSSM (restricting designable identities to evolutionarily observed substitutions) with Rosetta `FastDesign`-style multi-position simultaneous redesign, producing a small number (typically 5–10) of candidate variants each carrying >10 mutations simultaneously, rather than single-point ΔΔG scores. It targets **expression yield and thermostability jointly**, not ΔΔG per se.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI binary `cartesian_ddg`, e.g.:
  ```
  cartesian_ddg.<extras>.<os><compiler>release \
      -s input.pdb \
      -ddg:mut_file mutations.txt \
      -ddg:iterations 3 \
      -ddg:cartesian true \
      -ddg:bbnbrs 1 \
      -ddg:legacy false \
      -score:weights ref2015_cart \
      -fa_max_dis 9.0
  ```
  Legacy `ddg_monomer`:
  ```
  ddg_monomer.<extras>.<os><compiler>release \
      -in:file:s input.pdb -ddg::weight_file ddg.wts \
      -ddg::iterations 50 -ddg::dump_pdbs true \
      -resfile mutations.resfile
  ```
- **Inputs:** a starting PDB structure and a mutation list. `cartesian_ddg`'s `-ddg:mut_file` format is documented in-code as "alternate specification for mutations ... File format described in fix_bb_monomer_ddg.cc above the read_in_mutations function" (`options_rosetta.py:5438`); functionally it is a `total N / <n_mutations> / <wt_aa><resnum><mut_aa>` block format, one block per point mutation (or combination) to evaluate. `-ddg:mut_only` / `-ddg:wt_only` restrict to just the mutant or just the wild-type baseline run.
- **Outputs:** `ddg_predictions.out` (per `Option('out', ..., default='ddg_predictions.out')`, `options_rosetta.py:5442`) — a text table of per-mutation ΔΔG values (kcal/mol-like Rosetta energy units) plus, if `dump_pdbs=true` (the default, `options_rosetta.py:5441`), the relaxed wild-type and mutant PDB structures for each converged state.
- **A concrete example (option group verified in `source/src/basic/options/options_rosetta.py:5390-5460`):** running with default `-ddg:iterations 3`, `-ddg:cartesian true`, `-ddg:bbnbrs 1`, `-ddg:n_converged 2`, `-ddg:score_cutoff 1.0` will iterate up to 3 wild-type/mutant cycles and declare convergence once 2 replicate models fall within 1.0 Rosetta-energy-unit of each other.

## Compute pattern
- **Pattern:** **P2** (CPU-parallel fan-out, in-job) — each mutation is an independent unit of work (its own wild-type+mutant relax cycles), and a mutation scan across many positions is embarrassingly parallel across cores/ranks, identical in kind to `nstruct` fan-out for FastRelax.
- **GPU vendor portability:** CPU-only, same evidence as `rosetta.md` (no CUDA/HIP/SYCL in `protocols/ddg/` or the relax machinery it calls).
- **State model:** restart-required per mutation (a killed cartesian_ddg mutation restarts from scratch), checkpointable at the mutation-list level (missing entries in `ddg_predictions.out` identify which mutations still need to run).
- **Data locality:** self-contained — one structure, one mutation list, one output file; no shared-FS requirement beyond the standard Rosetta `database/`.
- **Staging burden:** none beyond the standard Rosetta `database/` (no dedicated ΔΔG model weights — it's the same physics/statistics score function as the rest of Rosetta).
- **Container availability:** official (same `rosettacommons/rosetta` image as `rosetta.md`; `cartesian_ddg` and `ddg_monomer` are standard `apps/public` binaries built alongside `rosetta_scripts`).

## Deployment on DOE & ACCESS
Identical story to `rosetta.md`: CPU-only, no GPU blockers on any of Frontier/Aurora/Polaris/ACCESS, but build-required everywhere (no prebuilt binary target-matches leadership CPUs) and gated by the same UW-CoMotion license acceptance. Because `cartesian_ddg` runs as many small, independent, short single-node jobs (one per mutation, or one per mutation batch), it is a particularly good fit for the P2 fan-out model on any of these clusters — no MPI rank topology is needed even at large mutation-scan scale, unlike the P3 secondary pattern noted for bulk `nstruct` FastRelax ensembles.

## Agentic surface
- **Native MCP:** no (see `rosetta.md`'s community-MCP caveat — applies here too, undifferentiated by sub-protocol).
- **Parameters worth exposing for autonomous variation:**

| parameter | type | sane range | default | trade-off |
|---|---|---|---|---|
| `ddg:iterations` | int | 3–10 | 3 (per `options_rosetta.py:5441`, "specifies the number of iterations of refinement") | more iterations = tighter convergence estimate, linear cost increase |
| `ddg:bbnbrs` | int | 0–3 | 1 | how many sequence neighbors get backbone flexibility during relax; higher = more accurate for backbone-coupled mutations but slower and can overshoot for isolated surface mutations |
| `ddg:cartesian` | bool | — | `true` (in the app-level `Option('cartesian', 'Boolean', default='true', ...)`, `options_rosetta.py:5450`) | cartesian mode is what gives `cartesian_ddg` its accuracy edge over `ddg_monomer`; should not be turned off except to reproduce old benchmarks |
| `ddg:n_converged` / `ddg:score_cutoff` | int / real | 2–3 / 0.5–2.0 kcal | 2 / 1.0 | tighter convergence criteria (more replicates within a smaller window) cost more compute per mutation but reduce noise in the reported ΔΔG |
| `score:weights` | enum | `ref2015_cart`, `beta_nov16_cart` | `ref2015_cart` typical | must be a `_cart` variant when `cartesian=true` — mismatch silently degrades accuracy rather than erroring |
| mutation batch size (agent-level, not a Rosetta flag) | int | 1–1000s of mutations per scan | n/a | pure P2 fan-out width; bounded only by allocation size and campaign budget |

- **Parameters that must NOT be agent-varied:** `ddg:fd_mode` ("Preserving franks mode for testing directional neighborfinding" per its own description, `options_rosetta.py:5458`) — a debug/testing flag, not a production knob; `ddg:legacy` should be fixed per campaign (mixing `legacy=true`/`false` runs of the same mutation set produces non-comparable ΔΔG values since they invoke materially different code paths — the JSON-capable non-legacy `CartesianddG::run(pose)` path vs. the older iterative loop in `main()`); the `ref`/`METHOD_WEIGHTS` reference-energy line in the chosen `.wts` file (see `rosetta.md`) — never edit mid-campaign, it recalibrates every downstream ΔΔG number silently.

## Failure modes & what the agent must check
- **Loud failure:** malformed `-ddg:mut_file`, missing/mismatched residue numbering between the mutation file and the PDB (Rosetta will assert/exit rather than silently substitute), missing JSON support at compile time for the non-legacy path ("A JSON capable compiler is required to use this app," `cartesian_ddg.cc:~285`).
- **Silent bad output:**
  - **Non-convergence reported as a number anyway** — if the `ddg:n_converged`/`ddg:score_cutoff` criterion is never met within `ddg:iterations`, older code paths can still emit a ΔΔG value from whatever replicates completed; the agent must check the **spread across replicate models**, not just the mean, and treat wide-spread mutations as low-confidence rather than trusting the point estimate.
  - **Backbone-neighbor mismatch** — too-small `bbnbrs` for a mutation that actually requires backbone accommodation (e.g., proline introduction, glycine removal at a tight turn) produces an artificially large, physically implausible ΔΔG because the packer cannot relieve the strain it should be allowed to relieve; conversely too-large `bbnbrs` can "relax away" a real destabilization. The agent should flag proline/glycine mutations for a `bbnbrs` sensitivity check rather than trusting the default blindly.
  - **Score-function/weight mismatch** (torsion weights used with `cartesian=true` or vice versa) degrades accuracy without any error — always verify the `score:weights` value ends in `_cart` when cartesian mode is on.
  - **Sign/direction errors** — Rosetta ΔΔG is not perfectly anti-symmetric between forward and reverse mutations (literature Ssym+ benchmarking exists specifically because real predictors violate this); an agent using ΔΔG differences to rank candidate mutation *sets* should not assume forward-reverse consistency.
- PROSS-specific (from literature, not refcode): PROSS explicitly avoids the active site / functional residues by construction (a design-region mask), so the primary silent-failure risk for autonomous use is **omitting or mis-specifying that functional-residue mask**, which would let the protocol "stabilize" straight through a catalytic or binding residue.

## Cost per unit of work
- **1 point mutation via `cartesian_ddg`, default `iterations=3`, `bbnbrs=1`:** each iteration relaxes both a wild-type and a mutant local ensemble via Cartesian FastRelax restricted to the mutation neighborhood — roughly comparable to a handful of local (not full-protein) cartesian FastRelax passes. Literature figures for physically similar Rosetta cartesian ΔΔG protocols report on the order of **~1–15 CPU-hours per mutation** depending on protein size, neighborhood radius, and convergence settings (the wide range reflects that "Flex ddG"-family costs are reported anywhere from ~1 CPU-hour/mutation on modern hardware for SKEMPI-scale binding mutations up to ~15 CPU-hours/mutation for more thorough sampling) — treat this as an order-of-magnitude planning number, not a guarantee, and calibrate against your own hardware on a small pilot batch before budgeting a full scan.
- **A saturation mutagenesis scan** (all 19 substitutions at every position of a ~200-residue protein, ~3,800 mutations) is therefore on the order of several thousand to tens of thousands of CPU-hours — this is the single largest CPU-hour sink an autonomous stability campaign is likely to hit, and is exactly why P2 fan-out width (not protocol choice) is the primary cost lever.
- **ddg_monomer** (legacy, `iterations` default higher, commonly run at 50 in published protocols) is typically **more** expensive per mutation than `cartesian_ddg` for comparable accuracy, which is part of why `cartesian_ddg` superseded it.
- **Checkpointable:** yes, at the per-mutation granularity — a killed scan resumes by diffing the mutation list against completed entries in `ddg_predictions.out`.

### Accuracy expectations vs. experiment
From published benchmarking against calorimetric stability datasets (via WebSearch, not from the refcode):
- On the **Ssym** benchmark (684 single-point mutations with calorimetrically determined ΔΔG and crystal structures, designed to test forward/reverse anti-symmetry), Rosetta-family cartesian ΔΔG protocols achieve **Pearson r ≈ 0.63** against experiment, comparable to FoldX in the same study.
- Other reported figures for Rosetta cartesian ΔΔG protocols: **Pearson r ≈ 0.66, MAE ≈ 1.39 kcal/mol** against a held-out experimental set.
- Accuracy is **not uniform across the ΔΔG range** — cartesian_ddg is most reliable in the **−1 to +7 kcal/mol** window; strongly destabilizing mutations (very large positive ΔΔG) and stabilizing outliers are both harder to predict accurately, meaning the tool should be trusted more for ranking mutations within a moderate range than for extrapolating extreme effects.
- **Known systematic biases:** (a) forward/reverse anti-symmetry is imperfectly respected (a known Ssym+ finding across structure-based ΔΔG predictors generally, Rosetta included); (b) accuracy degrades for mutations requiring backbone rearrangement that the local `bbnbrs` neighborhood does not capture; (c) predictions are more reliable for point mutations on well-resolved, high-quality crystal structures than for homology models or predicted structures — an important caveat for an autonomous pipeline where the input structure may itself come from an upstream generative model rather than experimental determination.
- **PROSS** (from literature): community-wide experimental evaluation (ScienceDirect, "Community-Wide Experimental Evaluation of the PROSS Stability-Design Method") reports validated improved expression and/or stability across dozens of independently tested proteins; it is a **multi-mutation combinatorial** method, so it does not produce a single accuracy correlation coefficient comparable to per-point-mutation ΔΔG benchmarks — success is instead reported as fraction of designed variants showing measurable stability/expression improvement, which the source material describes as high enough that the method has seen broad voluntary community adoption, but exact aggregate success-rate percentages were not found in the sources surfaced by search and should be pulled from the primary PROSS papers (Goldenzweig et al. 2016; Weizmann PROSS 2 paper, Bioinformatics 2021) before being used as a specific number in downstream planning documents.

## Verdict
**Core.** `cartesian_ddg` is explicitly named as the load-bearing tool for the stability/thermostabilization problem class and there is no substitute in this toolkit — it is the only physics-grounded, single-point-mutation stability predictor available, with real (if imperfect, r≈0.6-0.7) correlation to experiment and a well-understood cost model that scales predictably with mutation-scan width. `ddg_monomer` is **Defer** — keep as a fallback/legacy-reproduction path only; it is superseded by `cartesian_ddg` for new work and should not be the default. **PROSS is Defer, not Reject**, pending refcode availability: it is scientifically well-validated and directly relevant (multi-mutation stabilization complementary to single-point ΔΔG ranking), but it is not vendored anywhere in `tools/rosetta/` in this refcode, so either (a) its underlying RosettaScripts XML protocol needs to be reconstructed from the public PROSS methodology and validated in-house, or (b) the team should treat the public PROSS webserver as an external P5 service dependency rather than something we run ourselves — that decision should be made explicitly rather than assumed, since it changes the compute-pattern classification entirely (P5 network service vs. P2 in-house Rosetta job).

## Sources
- `tools/rosetta/source/src/apps/public/ddg/cartesian_ddg.cc` (main(), lines ~260-300; JSON-required legacy branch)
- `tools/rosetta/source/src/protocols/ddg/CartesianddG.cc/.hh`
- `tools/rosetta/source/src/apps/public/ddg/ddg_monomer.cc` (author Liz Kellogg, header comment lines 1-13)
- `tools/rosetta/source/src/basic/options/options_rosetta.py:5390-5460` (`Option_Group('ddg', ...)` — every `ddg::*` flag, default, and description cited above)
- PROSS: not present in `tools/rosetta/` refcode (verified by `find . -iname "*pross*"` returning no hits) — all PROSS content is from WebSearch of public literature: "Community-Wide Experimental Evaluation of the PROSS Stability-Design Method" (ScienceDirect), "PROSS 2: a new server for the design of stable and highly expressed protein variants" (Bioinformatics 2021), Weizmann PROSS webserver (pross.weizmann.ac.il).
- ΔΔG accuracy figures (Ssym Pearson r≈0.63; general Pearson r≈0.66/MAE≈1.39 kcal/mol; accurate range −1 to +7 kcal/mol; Flex ddG cost ~1–15 CPU-hours/mutation): via WebSearch, sources include ScienceDirect "Accurate protein stability predictions from homology models," RosettaCommons docs (docs.rosettacommons.org/docs/latest/cartesian-ddG), and related SKEMPI/Ssym benchmarking papers — not independently re-derived, cited as reported by these secondary sources.
