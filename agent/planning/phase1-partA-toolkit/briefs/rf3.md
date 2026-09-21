# RF3 (RosettaFold3)

**One-line identity.** An all-atom biomolecular structure prediction network (AF3-class diffusion architecture, trained with explicit chirality features and atom-level geometric conditioning) built on the AtomWorks framework, distributed as a model within the RosettaCommons Foundry package.

## Identity
- **Version / release examined:** refcode at `<workspace>/impress-a-refcodes/tools/foundry/models/rf3`, package `rc-foundry` (dynamic version via setuptools-scm; installed dev snapshot `0.1.dev917+gcbbe4c6a6.d20251001`, per `src/rf3/_version.py`). Preprint: "Accelerating Biomolecular Modeling with AtomWorks and RF3" (bioRxiv 2025.08.14.670328, Aug 2025). Public GitHub release Sept 15 2025 (RosettaCommons blog).
- **Provenance:** RosettaCommons / Institute for Protein Design. Code and model weights released under a **permissive BSD license** (confirmed via RosettaCommons announcement and `pyproject.toml` classifier `License :: OSI Approved :: BSD License`). Refcode: `tools/foundry/models/rf3/` inside `tools/foundry/` (the parent monorepo also hosts RFD3 and ProteinMPNN/LigandMPNN).
- **Maturity:** active research, recently open-sourced. The RF3 README itself flags: *"We are currently finalizing some cleanup work on the inference API. Please expect the API (including input formats and confidence outputs) to stabilize in the upcoming weeks."* Treat the CLI surface as pre-stable.

## Scientific role
All-atom complex structure prediction (protein/DNA/RNA/ligand, arbitrary CCD/SMILES/SDF small molecules, covalent modifications, chirality-aware). Serves **all four** in-scope problem classes as the structural "filter" stage: stability (fold verification), de novo binder design (complex co-folding of binder+target), enzyme/catalytic design (ligand/cofactor placement, chirality of catalytic centers), and small-molecule binding (protein-ligand docking with fixed or free conformers). Pipeline stage: **predict**.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI via `[project.scripts]` entrypoint `rf3` (Typer app in `src/rf3/cli.py`), subcommand `fold` (alias `predict`). Internally a Hydra app — arguments are `key=value` overrides, not `--flag value`. Direct Python entry: `python models/rf3/src/rf3/inference.py inputs='tests/data/5vht_from_json.json'`.
- **Inputs:** CIF, PDB, or JSON. JSON schema is a list of `components` (each with `seq`/`smiles`/`ccd_code`/`path`), optional `msa_path` per protein chain, optional `bonds`, `template_selection`, `ground_truth_conformer_selection`, `cyclic_chains`. A directory of CIF/PDB/JSON files is also accepted and auto-distributed across GPUs.
- **Outputs:** land in `out_dir` (required to persist results — omitting it keeps outputs in memory only): `<name>_confidences.csv`, `<name>_ranking_scores.csv`, `<name>_model.cif` (top-ranked structure, `.cif.gz` when `annotate_b_factor_with_plddt=True`), `<name>_summary_confidences.json`, plus `seed-<n>_sample-<m>/` subfolders for the other ensemble members.
- **A concrete example** (from `docs/index.md` / README, uses repo-relative path):
```bash
rf3 fold inputs='/path/to/foundry/models/rf3/tests/data/5vht_from_json.json' out_dir='/path/to/your/output/directory'
```
MSA'd example (`docs/examples/3en2_from_json_with_msa.json`):
```bash
rf3 fold inputs='models/rf3/docs/examples/3en2_from_json_with_msa.json'
```

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job). Multi-input batches within one `rf3 fold` call distribute across GPUs in a multi-GPU allocation but remain in-job.
- **GPU vendor portability:** **CUDA + SYCL-XPU documented; HIP unproven.**
  - CUDA: primary path, with an optional CUDA-only accelerator kernel (`cuequivariance_torch`, gated by `foundry/pyproject.toml`'s `rf3` extra: `cuequivariance_ops_cu12`/`cuequivariance_torch>=0.6.1; sys_platform=='linux'`).
  - Intel XPU: **explicitly documented** in `tools/foundry/README.md`: `pip install torch --index-url https://download.pytorch.org/whl/xpu` then `pip install "rc-foundry[all]"`; a dedicated Hydra trainer config exists at `configs/trainer/xpu.yaml` (`accelerator: xpu`, `strategy: xpu_single`). This is real, first-party support — not inferred.
  - Apple Silicon MPS: also documented (community fork), with the `rf3` cuEquivariance extra auto-skipped on macOS.
  - AMD/HIP: **no documentation found.** However, `src/foundry/__init__.py` gates cuEquivariance behind `torch.cuda.is_available()` inside a `try/except ImportError` — if `cuequivariance_torch` (a CUDA-only compiled wheel) fails to import, `SHOULD_USE_CUEQUIVARIANCE` stays `False` and `src/rf3/model/layers/attention.py` falls back to a vanilla PyTorch attention path. Since the rest of the model is written in plain PyTorch/einops (no JAX, no other CUDA-only kernel calls found via `grep -rn cuequivariance|pytorch3d|e3nn|triton`), it is **plausible** RF3 runs on ROCm PyTorch via this fallback — but this is inference from code structure, not a verified deployment. Mark unproven for Frontier.
- **State model:** stateless per prediction call (no checkpoint/resume of a single fold; batches of independent inputs can simply be re-run for the remainder if interrupted).
- **Data locality:** shared-FS required for `out_dir`, input files, and MSA files; otherwise self-contained per prediction.
- **Staging burden:** model weights only — RF3 does not require local genetic sequence/structure databases (no built-in MSA search; see MSA question below). Checkpoint download example: `wget http://files.ipd.uw.edu/pub/rf3/rf3_foundry_01_24_latest_remapped.ckpt` (three interchangeable checkpoints offered: latest/preprint/benchmark). `foundry install base-models` fetches the "latest" RFD3+RF3+MPNN set into `~/.foundry/checkpoints`; exact checkpoint size was not found in refcode or docs (AF3-class diffusion models of this shape are typically low single-digit GB; unverified — confirm by inspecting the downloaded `.ckpt` before staging estimates are trusted).
- **Container availability:** official — Docker Hub image `rosettacommons/foundry`, with a `slim` tag for bring-your-own-weights deployments.

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA):** primary supported path; `pip install "rc-foundry[rf3]"` pulls the CUDA 12 cuEquivariance wheels directly. Straightforward.
- **Aurora (Intel PVC / SYCL-XPU):** first-party documented install path exists (`torch --index-url .../whl/xpu`). This is the strongest XPU story of the five tools in this cluster — worth prioritizing for an Aurora pilot. Caveat: the XPU trainer config (`configs/trainer/xpu.yaml`) lives under **training** configs; inference-time XPU behavior (device selection in `rf3.inference`) was not independently verified from the CLI path in this review — validate with the 5vht smoke test on an Aurora node before relying on it.
- **Frontier (AMD MI250X / HIP):** no ROCm instructions in README or pyproject. The cuEquivariance-optional code path suggests it *could* work under ROCm-built PyTorch, but this is unverified — treat as a build-and-test risk, not a known-good path.
- **All platforms:** module-vs-conda-vs-apptainer — `pip install` into a venv/conda env is the documented mechanism; the official container is the lower-risk path on leadership machines where user-space pip installs of CUDA-linked wheels are often awkward. No license gate blocks any of this (BSD).

## Agentic surface
- **Native MCP:** no. No RF3- or Foundry-specific MCP server found in search; general "AlphaFold MCP" servers found (see `alphafold.md`) do not cover RF3.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `n_recycles` | int | 3–10 | 10 | More recycles → better convergence, linear wall-clock cost |
| `diffusion_batch_size` | int | 1–25 | 5 | Number of structures sampled per Pairformer forward pass; more = better mode coverage at added diffusion-sampling cost |
| `num_steps` | int | 50–200 | 200 | Diffusion sampling steps; docs state "no deterioration in performance with 50 steps" but >2x speedup — good first lever for cheap autonomous exploration |
| `seed` | int | any | training seed (42) | Only way to get genuinely different folds from repeated same-input calls; expensive way to add diversity |
| `early_stopping_plddt_threshold` | float [0,1] | 0.3–0.6 | 0.5 | Aborts low-confidence predictions after 1 recycle to save 10-20x compute; trades a few false-negative aborts for large throughput gains on bulk screening |
| `template_selection` / `ground_truth_conformer_selection` | AtomSelection strings | n/a | none | Fixes known substructure (e.g., binding-site geometry); not "cost" so much as correctness — over-constraining defeats the point of prediction |

- **Parameters that must NOT be agent-varied:** `ckpt_path` mid-campaign without a matching re-baseline (different checkpoints — latest/preprint/benchmark — are stated to share an identical inference API but were trained to different cutoffs; silently swapping checkpoints mid-run invalidates comparability of confidence scores across a design campaign). `residue_renaming_dict` should be agent-set once per custom-ligand class, not varied per call — it uses brute-force find/replace and a mismatch risks catastrophically wrong predictions per the README's own warning.

## Failure modes & what the agent must check
- **Loud failure:** malformed JSON/CIF input, missing MSA file path, non-existent checkpoint path — raises exceptions, non-zero exit.
- **Silent bad output (early stopping):** with default `early_stopping_plddt_threshold=0.5`, a low-confidence input produces **no structure file at all** — only a `.score` file with `early_stopped=True`. An agent that blindly globs for `*_model.cif` will see "no output" and must distinguish this from a crash by checking the `.score`/`confidences.csv` for the `early_stopped` flag.
- **Silent bad output (chirality/geometry):** RF3's own metrics suite (`src/rf3/metrics/chiral.py`, tests `test_chiral.py`, `test_chiral_metrics.py`) exists because chirality inversion is a known failure mode of atom-level diffusion models generally — this is precisely the class of error RF3 claims to reduce (88% correct chiral centers vs. 84% AF3, 76% Boltz-2 per the preprint) but does not eliminate. The agent should treat per-ligand chirality checks (via RDKit on the output CIF/SDF, comparing to input SMILES stereodescriptors) as a mandatory post-hoc gate for any ligand-containing prediction, not just trust pLDDT.
- **Silent bad output (spurious clash/interface):** `src/rf3/metrics/clashing_chains.py` computes a clash metric used internally; an agent should check this field rather than assume a high pTM/ipTM implies a physically valid interface (same class of failure documented for AF3's ipTM — see `alphafold.md`).
- **Specific check:** parse `<name>_summary_confidences.json` for `ptm`, `iptm` (overall and per-interface-type: protein-protein, protein-ligand, ligand-ligand, per `src/rf3/metrics/predicted_error.py`), and cross-reference against `early_stopped` before accepting any structure as a design-loop input.

## Cost per unit of work
- **Unit of work:** one `rf3 fold` call, one complex, default settings (10 recycles, 5 diffusion samples, 200 diffusion steps).
- **Typical wall-clock:** not benchmarked in refcode; qualitatively, AF3-class diffusion models on a single A100/MI250-class GPU are in the **1–10 minute range per target** at these defaults for moderate-sized complexes (few hundred residues + ligand), with `num_steps=50` giving >2x speedup and `early_stopping_plddt_threshold` giving 10-20x speedup on bulk low-confidence screening (both claims from the RF3 README, not independently timed here — treat as vendor-stated, verify empirically before budgeting a campaign).
- **Resource shape:** 1 GPU per prediction; batch mode auto-distributes across GPUs in a multi-GPU job but each prediction is single-GPU.
- **Checkpointable:** no (per-prediction, not per-recycle); `skip_existing` flag lets a batch resume by skipping already-completed outputs in `out_dir`, which is the practical restart mechanism for large batches.

## Verdict
**Core.** RF3 is the strongest open-weights AF3-class co-folder available to this project: permissive BSD license (no access gate, unlike AF3), native ligand/covalent/chirality handling directly relevant to enzyme and small-molecule problem classes, and — uniquely among this cluster — a first-party, documented Intel XPU install path that materially de-risks Aurora. Its main liabilities are an explicitly pre-stable inference API (the README's own warning) and unverified AMD/HIP support. Recommend pinning a specific commit/checkpoint before relying on it in a production loop, and validating the XPU and (if attempted) ROCm paths with the 5vht smoke test before Aurora/Frontier deployment.

## Sources
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/README.md`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/docs/index.md`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/src/rf3/cli.py`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/src/rf3/_version.py`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/src/rf3/model/layers/attention.py`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/src/rf3/metrics/predicted_error.py`
- `<workspace>/impress-a-refcodes/tools/foundry/models/rf3/configs/trainer/xpu.yaml`, `cpu.yaml`, `rf3.yaml`
- `<workspace>/impress-a-refcodes/tools/foundry/README.md`
- `<workspace>/impress-a-refcodes/tools/foundry/pyproject.toml`
- `<workspace>/impress-a-refcodes/tools/foundry/src/foundry/__init__.py`
- Preprint: [Accelerating Biomolecular Modeling with AtomWorks and RF3](https://doi.org/10.1101/2025.08.14.670328) — DockQ/chirality benchmark numbers (RF3 vs AF3/Boltz-2/Chai-1) inferred from search summary, not independently re-derived from the PDF; verify against the paper directly before citing in the summary report.
- [RosettaCommons announcement, Sept 2025](https://rosettacommons.org/2025/09/15/atomworks-rf3-in-foundry-now-open-source-on-github/) — BSD license confirmation.
- No MCP server found for RF3/Foundry (search performed; inferred absence, not exhaustively verified against every registry).
