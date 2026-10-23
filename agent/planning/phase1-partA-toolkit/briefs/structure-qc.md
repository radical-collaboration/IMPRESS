# Structure QC: DSSP, FreeSASA, MolProbity

**One-line identity.** Three cheap, deterministic, non-ML structure-validation tools — secondary-structure assignment (DSSP), solvent-accessibility calculation (FreeSASA), and all-atom geometric validation (MolProbity) — that together form the first gate every generated structure should pass before any expensive tool touches it.

## Identity
- **Version / release examined:** DSSP 4.5 (stable release cited Jan 31 2026, repo `PDB-REDO/dssp`, doc at `dssp/doc/mkdssp.md`); FreeSASA 2.2.1 (PyPI, C library + Python module, repo `mittinatten/freesasa`); MolProbity — distributed both as a standalone Richardson-lab package (`rlabduke/MolProbity` on GitHub) and, in its currently-maintained form, as `phenix.molprobity` inside the open-source `cctbx_project`/Phenix stack (Java validation utilities rewritten into Python/CCTBX for maintainability).
- **Provenance:** DSSP — originally Kabsch & Sander (1983), maintained today by the PDB-REDO group (Radboud/Utrecht); license is permissive (Boost Software License 1.0 historically, now published as BSD-2-Clause per the current repo). FreeSASA — Simon Mitternacht, MIT license. MolProbity — Richardson lab, Duke University; distributed under a modified BSD-style license (see `LICENSE.html` on the MolProbity site — free use/redistribution with attribution and naming restrictions, not GPL). None of the three appear anywhere in `impress-a-refcodes/tools/`; this is a genuine external-toolkit gap the refcodes don't fill. Notably, `foundry`'s own RFdiffusion3 metrics code does **not** call DSSP — it uses Biotite's built-in `annotate_sse` (P-SEA algorithm) for secondary-structure statistics instead (`impress-a-refcodes/tools/foundry/models/rfd3/src/rfd3/metrics/metrics_utils.py:8,22-28`). That is a meaningfully different, faster, less rigorous algorithm (Cα-trace geometry only, no explicit H-bond pattern) — see the Failure-modes section for why DSSP should still be run as the authoritative check, not replaced by P-SEA.
- **Maturity:** all three production-grade, decades-old, field-standard. DSSP is the reference implementation cited by essentially every downstream tool that reports "% helix / % sheet." MolProbity is the validation tool the PDB itself uses at deposition.

## Scientific role
QC/gating utilities that apply to **every** problem class (stability, binder design, enzyme design, small-molecule binding) — they don't test function or affinity, they test whether a structure is physically sane at all. Pipeline stage: **analyze / score** (post-hoc check on an already-generated or already-predicted structure, never a generator itself).
- **DSSP**: assigns per-residue secondary structure (H/G/I helix types, E/B strand/bridge, T/S turn/bend, PPII, coil) plus per-residue solvent accessibility, from backbone H-bond geometry.
- **FreeSASA**: computes per-atom and per-residue solvent-accessible surface area (SASA), and relative SASA (RSA = ASA / MaxASA from Gly-X-Gly reference values) when NACCESS or ProtOr radii are used — the standard measure of residue burial.
- **MolProbity**: all-atom steric-clash detection (via `probe`), Ramachandran outlier detection (via `ramalyze`), and rotamer-outlier detection (via `rotalyze`), aggregated into a single MolProbity score.

## Invocation & I/O contract
- **DSSP** — CLI: `mkdssp input.pdb output.dssp` (or `.mmcif` in/out; gzip-compressed input accepted). Since v4.0 the default output is annotated mmCIF (`_struct_conf` category) rather than the legacy `.dssp` text format. Python: `Bio.PDB.DSSP.DSSP(model, "input.pdb")` shells out to the `mkdssp` binary and returns a dict keyed by `(chain_id, residue_id)` → `(aa, ss, rel_asa, phi, psi, ...)`.
- **FreeSASA** — CLI: `freesasa structure.pdb --format=seq` (per-residue) or `--format=res`; Python: `import freesasa; s = freesasa.Structure("in.pdb"); r = freesasa.calc(s); r.residueAreas()` returns per-chain, per-residue `total`, `polar`, `apolar`, and (with `--radii=naccess`) `relativeTotal` RSA.
- **MolProbity** — CLI (Phenix build): `phenix.molprobity model.pdb` produces a text/HTML validation report; the underlying components can also be run standalone as `phenix.clashscore`, `phenix.ramalyze`, `phenix.rotalyze` for a la carte checks. Standalone Richardson-lab build ships `oneline-analysis` for a compact single-line-per-structure summary suited to batch scripting.
- **Inputs:** PDB or mmCIF coordinate files for all three.
- **Outputs:** DSSP → per-residue SS string + RSA table (mmCIF or legacy text); FreeSASA → per-atom/per-residue SASA table (stdout or `.rsa`-like text, or the Python `ResidueArea` objects); MolProbity → clashscore (clashes per 1000 atoms), % Ramachandran favored/outliers, % rotamer outliers, and a composite MolProbity score, as text/HTML/CSV.
- **A concrete example (from Biopython's own DSSP docs):** `p = PDBParser(); s = p.get_structure("1MOT", "1MOT.pdb"); model = s[0]; dssp = DSSP(model, "1MOT.pdb"); dssp[("A", 1)]` returns `(aa, secondary_structure, relative_asa, phi, psi, ...)` for residue A1.

## Compute pattern
- **Pattern:** **P6** (in-process / sub-second-to-low-seconds library call). All three operate on a single structure at a time with no GPU, no MPI, and runtimes from milliseconds (FreeSASA on a ~300-residue chain) to a few seconds (a full MolProbity report, which runs `probe` + `reduce` + `ramalyze` + `rotalyze` as a small pipeline). None should ever be submitted as a scheduled batch job — per taxonomy rule, scheduling overhead would exceed the work by orders of magnitude. Where hundreds/thousands of generated candidates need QC, that fan-out is **P2** at the campaign level (many independent P6 calls dispatched across CPU workers), not a change in the pattern of the tool itself.
- **GPU vendor portability:** CPU-only, n/a for all three — pure geometry/combinatorics, no accelerated kernels.
- **State model:** stateless (each call is a pure function of the input structure file).
- **Data locality:** self-contained (one structure file in, one report out; no shared-FS requirement beyond the input/output files themselves).
- **Staging burden:** none for DSSP/FreeSASA (no model weights, no database). MolProbity's reference distributions (the Top500/Top8000-derived Ramachandran and rotamer libraries) ship with the package itself (tens of MB), not a separate staged download.
- **Container availability:** community (DSSP and FreeSASA are packaged on conda-forge; MolProbity is distributed as part of the Phenix installer, which itself is a large — several-GB — self-contained bundle requiring a (free, academic) registration-gated download; no minimal official MolProbity-only container was found).

## Deployment on DOE & ACCESS
CPU-only and dependency-light, so there is no platform blocker on Frontier, Aurora, Polaris, or any ACCESS system — these are exactly the kind of tool that runs identically everywhere. Practical mechanics: DSSP and FreeSASA install cleanly via conda-forge on any login/compute node with outbound access, or can be baked into the agent's own container image (they have no license gate). MolProbity is the one with friction: the full Phenix bundle is a multi-GB download behind an academic registration form, which is a poor fit for on-the-fly staging inside a job — it should be pre-staged into the agent's container/module environment during initial toolkit setup, not fetched mid-campaign. The standalone (non-Phenix) MolProbity distribution is smaller and license-open but has historically been less actively maintained than the Phenix-integrated `phenix.molprobity`.

## Agentic surface
- **Native MCP:** no, for all three. No MCP server exposing DSSP, FreeSASA, or MolProbity as typed tools was found; use direct CLI/Python invocation from the agent's own tool layer.
- **Parameters worth exposing for autonomous variation:**

| parameter | type | sane range | default | trade-off |
|---|---|---|---|---|
| FreeSASA `--radii` | enum | `naccess`, `protor` | ProtOr | choice of atomic radii set changes absolute SASA slightly and determines whether RSA (relative SASA) is even computable — RSA needs a matching reference table |
| FreeSASA `algorithm`/`n-points` (Shrake-Rupley) or slices (Lee-Richards) | int | 100–5000 points / 20–100 slices | 100 pts / 20 slices | more points/slices = smoother, more accurate SASA at higher (still sub-second) cost — worth raising for a final QC pass vs. a cheap first-pass filter |
| DSSP output mode | flag | mmCIF vs. legacy `.dssp` text | mmCIF (v4+) | only affects downstream parser choice, not the science |
| MolProbity clashscore VDW overlap cutoff | float (Å) | fixed at 0.4 Å by convention | 0.4 Å | this is the field-standard definition of a "clash" (probe dot overlap ≥0.4 Å); changing it breaks comparability to every published clashscore percentile table — should not be varied |

- **Parameters that must NOT be agent-varied:** the MolProbity clash-overlap threshold (0.4 Å) and the Top500/Top8000 reference distributions it validates against — these define what "outlier" means; an agent silently loosening them to pass more designs defeats the purpose of the gate. Likewise, DSSP's H-bond energy cutoff for secondary-structure assignment is a fixed, validated constant from the original Kabsch-Sander algorithm and should not be exposed as a tunable.

## Failure modes & what the agent must check
- **Loud failure:** malformed/incomplete PDB (missing chain breaks, no CRYST1 record where required), non-standard residue names DSSP/MolProbity don't recognize, missing hydrogens for MolProbity's `probe`/`reduce` step (usually auto-added, but a structure with no backbone N/H can silently under-report clashes rather than error — see below).
- **Silent bad output — this is the point of running all three as a triplet:**
  - **A generated backbone with implausible or absent secondary structure** (all-coil, or a "helix" that DSSP assigns as a chain of isolated turns) is a strong signal of a degenerate/failed generation that RMSD-to-target or pLDDT alone will not catch. DSSP's SS string vs. the design's intended fold (e.g., "should be a 4-helix bundle") is a cheap, hard sanity check.
  - **Over-exposed hydrophobic core** (via FreeSASA RSA on hydrophobic residues) is a classic silent stability failure mode for de novo designs — a design can have excellent backbone geometry and score well on ProteinMPNN sequence recovery while still exposing a Leu/Ile/Val-rich patch that will drive aggregation or misfolding. RSA > ~25% on core-intended hydrophobic residues is the standard red flag.
  - **Physically impossible local geometry that a generative model's own internal metrics won't flag** — clashing side chains, Ramachandran outliers, and bad rotamers are exactly the class of error that diffusion/inverse-folding pipelines can produce even when their own loss-derived confidence metrics (pLDDT, designed-sequence log-likelihood) look fine, because those confidence scores are not geometric-validity checks. This is why MolProbity is a *different* signal from pLDDT/pAE, not a redundant one.
  - **Biotite's P-SEA secondary-structure assignment (used internally by RFdiffusion3's own metrics, see Identity) is not equivalent to DSSP** — P-SEA works from Cα geometry alone with no explicit backbone H-bond pattern, so it can disagree with DSSP on borderline helix/turn boundaries and 3₁₀-helix calls. Treat P-SEA-based self-reported metrics from a generator as a fast internal heuristic, not a substitute for an independent DSSP pass in the QC gate.

## Cost per unit of work
- **DSSP:** milliseconds to low-hundreds-of-milliseconds per structure (single-pass geometric calculation over backbone atoms), on a single CPU core.
- **FreeSASA:** milliseconds per structure for default point/slice density; still sub-second even at high accuracy settings for typical single-domain proteins (hundreds of residues).
- **MolProbity (full `phenix.molprobity` report):** roughly 1–10 seconds per structure on a single core for typical single-chain proteins (dominated by the `probe` all-atom dot-surface clash search and `reduce` hydrogen placement), scaling up for larger multi-chain complexes.
- **Checkpointable:** n/a — each call is atomic and fast enough that restart cost is negligible; no checkpoint mechanism needed or provided.
- At campaign scale (QC'ing thousands of generated candidates), total cost is dominated by fan-out width, not per-structure cost: a few thousand structures at a few seconds each is a few CPU-hours, trivially parallel (P2) across any allocation's idle cores.

## Verdict
**Core.** All three are cheap enough (P6, sub-10-second) that there is no principled reason for an autonomous agent to skip them on any generated structure before spending GPU-hours or Rosetta CPU-hours on it — they are the "does this design even make physical sense" gate the cluster's framing calls for. DSSP and FreeSASA metrics are also safe to use as **hard autonomous accept/reject gates** on the specific, well-characterized failure modes above (e.g., reject if RSA of core hydrophobics exceeds a threshold, reject if the intended SS element is entirely absent) precisely because they are deterministic, non-learned, and field-standard. MolProbity's individual sub-scores (clashscore, %Rama-favored, %rotamer-outliers) are similarly trustworthy as hard gates when compared against the published goal-level thresholds (clashscore near 0, >98% Ramachandran favored, <0.2% Ramachandran outliers, <1% poor rotamers) — these are the same thresholds crystallographers use to accept a model, and a generated structure that fails them by a wide margin is not a borderline case. The composite MolProbity score (a resolution-normalized log-combination) is more of a **soft ranking signal** for comparing candidates than a bright-line gate, since its "expected at this resolution" calibration was built for experimental structures, not generated ones.

## Sources
- `impress-a-refcodes/tools/foundry/models/rfd3/src/rfd3/metrics/metrics_utils.py:8,22-28` (Biotite `annotate_sse`/P-SEA usage, verified in refcode)
- [DSSP (algorithm) — Wikipedia](https://en.wikipedia.org/wiki/DSSP_(algorithm))
- [dssp/doc/mkdssp.md · PDB-REDO/dssp](https://github.com/PDB-REDO/dssp/blob/trunk/doc/mkdssp.md)
- [DSSP 4: FAIR annotation of protein secondary structure (bioRxiv)](https://www.biorxiv.org/content/10.1101/2025.04.11.648460.full.pdf)
- [FreeSASA GitHub](https://github.com/mittinatten/freesasa), [FreeSASA docs](https://freesasa.github.io/), [freesasa PyPI](https://pypi.org/project/freesasa/)
- [Relative accessible surface area — Wikipedia](https://en.wikipedia.org/wiki/Relative_accessible_surface_area)
- [MolProbity: all-atom contacts and structure validation (NAR 2007)](https://academic.oup.com/nar/article/35/suppl_2/W375/2920742)
- [MolProbity: all-atom structure validation for macromolecular crystallography (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2803126/)
- [Phenix MolProbity tool reference](https://www.phenix-online.org/documentation/reference/molprobity_tool.html)
- [MolProbity License](https://genomics-lab.fleming.gr/fleming/tools/molprobity/molprobity/LICENSE.html)
- [How to Validate a Protein Structure: Ramachandran Plots and MolProbity Scores Explained](https://stemskillslab.com/how-to-validate-a-protein-structure/) (goal-level thresholds; corroborated by the NAR/PMC primary sources above — inferred consensus figure, not a single canonical citation)
- Bio.PDB.DSSP Biopython docs (invocation example): https://biopython.org/docs/dev/api/Bio.PDB.DSSP.html
