# Chai-1 / Chai-2

**One-line identity.** Chai-1 is an open-weights, Apache-2.0 AF3-class all-atom co-folder whose defining
feature is a strong no-MSA mode built on a traced ESM2-3B embedding track and a native
residue/atom-level restraint system (contacts, pockets, covalent bonds, glycans); Chai-2 is Chai
Discovery's closed-weights antibody-design successor, not present in any form in this refcode. Refcode:
`<workspace>/impress-a-refcodes/tools/chai-lab/`.

## Identity
- **Version / release examined:** `chai_lab/__init__.py` → `__version__ = "0.6.1"`. `git log` on the
  refcode checkout shows HEAD `66c38d1` ("relax requirement on numpy (#424)"), 20 commits past the
  `v0.6.1` tag (`git describe` → `v0.6.1-20-g66c38d1`) — i.e. this is a post-0.6.1, pre-next-release
  snapshot; the package's own `__version__` string has not been bumped past `0.6.1` at this commit.
  `pyproject.toml`: `name = "chai_lab"`, `requires-python = ">=3.10"`, `[project.scripts] chai-lab =
  "chai_lab.main:cli"`.
- **Provenance:** Chai Discovery. **License, verified directly:** the repo ships one file, `LICENSE`,
  which is the plain Apache License 2.0 (no separate weights license, no CLA, no gate file). The
  README's own "Licence" section states: *"Chai-1 is released under an Apache 2.0 License (both code
  and model weights), which means it can be used for both academic and commercial purposes, including
  for drug discovery."* Weight downloads (see Compute pattern) are unauthenticated plain HTTPS GETs
  from `chaiassets.com` — **no HuggingFace login, no API key, no click-through terms-of-use gate** in
  the download path itself. This **confirms** the prior brief's license claim, but **corrects** its
  hosting claim: weights are not HuggingFace-hosted; they are hosted on Chai Discovery's own CDN
  (`chaiassets.com`), fetched directly by `chai_lab/utils/paths.py:download_if_not_exists`.
- **Maturity:** production-grade research tool — PyPI releases (`pip install chai_lab==0.6.1`), CI
  (`mypy`, `ruff`, `pytest` workflows under `.github/workflows/`), a hosted web demo
  (`lab.chaidiscovery.com`), and an active devcontainer-based dev workflow. Chai-2 does not exist in
  this refcode in any form (no code, no weights, no config) — the only trace of it is a citation block
  in `README.md` for the Chai-2 technical report (bioRxiv doi 10.1101/2025.07.05.663018). This
  **confirms** the prior brief's characterization of Chai-2 as inaccessible for self-hosted deployment.

## Scientific role
All-atom co-folding (protein/DNA/RNA/ligand/glycan), directly comparable in scope to AF3/Boltz-2, and
usable across all four in-scope problem classes as a structural filter. Pipeline stage: **predict**
(structure) + **score** (confidence). Two things distinguish it from Boltz-2 (Core) rather than
duplicate it:
1. **No-MSA is the *default* mode, not a discouraged fallback.** `run_inference`'s default is
   `use_esm_embeddings=True`, `use_msa_server=False`, `msa_directory=None` — i.e. out of the box Chai-1
   folds from sequence alone via a traced ESM2-3B (`t36_3B_UR50D`) embedding track standing in for
   evolutionary signal, not from an empty/degraded MSA path. Boltz-2's `msa: empty` mode exists but its
   own README calls it "not recommended" and says it "reduces accuracy" — Chai-1's no-MSA path is
   architecturally the primary path, not a degraded corner case.
2. **Fine-grained, atom-level restraint and glycan syntax.** `examples/restraints/README.md` documents
   a `.csv` restraint format (`contact` / `pocket` rows, keyed by `chainX`/`res_idxX`, with a residue
   *identity* cross-check against the input sequence) and `examples/covalent_bonds/README.md` documents
   an atom-level covalent-bond restraint syntax plus a compact in-FASTA grammar for branched glycans
   (e.g. `NAG(4-1 NAG(4-1 BMA(3-1 MAN)(6-1 MAN)))`). Boltz-2's brief documents an equivalent `bond` /
   `pocket` / `contact` constraint block in its YAML schema, so **the README's claim that Chai-1
   "uniquely" offers restraints is not defensible as written** (Boltz has comparable constraint types);
   what *is* still distinctive, verified from `examples/covalent_bonds/`, is Chai-1's dedicated
   in-FASTA branched-glycan grammar with automatic leaving-atom handling
   (`AllAtomStructureContext.drop_glycan_leaving_atoms_inplace`), which the Boltz brief does not
   document an equivalent for.

Chai-1 has **no native binding-affinity head** — unlike Boltz-2, it only ever emits structural
confidence (pTM/ipTM/pLDDT/PAE/PDE family), never a binder-vs-decoy or IC50 estimate. Chai-2 is
positioned for de novo antibody/binder design per its own technical-report citation but ships no code
here.

## Invocation & I/O contract
- **How a unit of work is invoked:** both CLI and Python API, confirmed from `chai_lab/main.py` and
  `chai_lab/chai1.py`.
  - **Entrypoint:** `[project.scripts] chai-lab = "chai_lab.main:cli"` (`pyproject.toml`). `cli()` in
    `chai_lab/main.py` registers three Typer subcommands: `fold` (wraps `chai_lab.chai1.run_inference`
    directly — every keyword argument of `run_inference` becomes a CLI flag), `a3m-to-pqt` (wraps
    `merge_a3m_in_directory`, converts `a3m` MSAs to Chai's `.aligned.pqt` format), and `citation`.
  - **Verbatim CLI, from `README.md`:**
    ```shell
    chai-lab fold input.fasta output_folder
    chai-lab fold --use-msa-server --use-templates-server input.fasta output_folder
    chai-lab fold --use-msa-server --msa-server-url "https://api.internalcolabserver.com" input.fasta output_folder
    ```
  - **Python API**, `chai_lab.chai1.run_inference(fasta_file: Path, *, output_dir: Path,
    use_esm_embeddings=True, use_msa_server=False, msa_server_url="https://api.colabfold.com",
    msa_directory=None, constraint_path=None, use_templates_server=False, template_hits_path=None,
    recycle_msa_subsample=0, num_trunk_recycles=3, num_diffn_timesteps=200, num_diffn_samples=5,
    num_trunk_samples=1, seed=None, device=None, low_memory=True,
    fasta_names_as_cif_chains=False) -> StructureCandidates` (`chai_lab/chai1.py:497-524`). A lower-level
    `run_folding_on_context` is also exposed for users who build an `AllAtomFeatureContext` by hand.
- **Inputs:** a FASTA-like file where each record is one of `protein|`, `ligand|` (SMILES), `rna|`,
  `dna|`, or `glycan|` (branched-glycan grammar above); an optional `.csv` restraints file
  (`--constraint-path`); MSAs either as a directory of `.aligned.pqt` files (`--msa-directory`) or
  fetched live via `--use-msa-server`; optional templates via `--use-templates-server` or a local `m8`
  hits file (`--template-hits-path`) plus CIFs in `$CHAI_TEMPLATE_CIF_FOLDER`.
- **Outputs**, verified from `chai_lab/chai1.py:958-1059` (`run_folding_on_context`'s write loop), land
  in `output_dir` (which **must be empty or non-existent** — `run_inference` asserts
  `not any(output_dir.iterdir())` and raises otherwise):
  - `pred.model_idx_{0..num_diffn_samples-1}.cif` — one structure per diffusion sample (all sharing the
    same trunk when `num_trunk_samples=1`, the default), or under `trunk_{i}/pred.model_idx_{j}.cif`
    when `num_trunk_samples>1`. Per-atom pLDDT (0–100 scale) is written into the CIF B-factor column.
  - `scores.model_idx_{idx}.npz` — one file per sample, fields exactly as returned by
    `chai_lab.ranking.rank.get_scores` (`chai_lab/ranking/rank.py:115-125`): `aggregate_score`, `ptm`
    (complex pTM), `iptm` (interface pTM), `per_chain_ptm`, `per_chain_pair_iptm`,
    `has_inter_chain_clashes`, `chain_chain_clashes`.
  - `msa_depth.pdf` — MSA coverage plot, written only if an MSA was actually used.
  - **Full PAE/PDE/pLDDT matrices are *not* written to disk by the CLI.** They exist only as tensors on
    the in-memory `StructureCandidates` object (`pae`, `pde`, `plddt` fields, shape
    `[candidate, n_tokens, n_tokens]` / `[candidate, n_tokens]`) returned by `run_inference` — a
    caller that needs the full per-token PAE matrix, not just the scalar `ptm`/`iptm`/scores.npz, must
    go through the **Python API**, not the bare CLI, and persist those tensors itself. This corrects the
    prior brief's vague "optional per-residue pLDDT and PAE matrices" claim with the actual field names
    and the actual (CLI-vs-API) availability split.
  - **Formula, verified from `chai_lab/ranking/rank.py:99-103`:** `aggregate_score = 0.2 * complex_ptm +
    0.8 * interface_ptm - 100 * has_inter_chain_clashes` — structurally different from Boltz-2's
    `0.8*complex_plddt + 0.2*iptm` and worth flagging: pLDDT plays **no role** in Chai-1's own ranking
    scalar, and any inter-chain clash subtracts 100, so `aggregate_score` is not bounded to `[0,1]`.
- **A concrete example**, taken verbatim from `examples/predict_structure.py`:
  ```python
  candidates = run_inference(
      fasta_file=fasta_path,
      output_dir=output_dir,
      num_trunk_recycles=3,
      num_diffn_timesteps=200,
      seed=42,
      device="cuda:0",
      use_esm_embeddings=True,
  )
  agg_scores = [rd.aggregate_score.item() for rd in candidates.ranking_data]
  scores = np.load(output_dir.joinpath("scores.model_idx_2.npz"))
  ```

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job); secondary P5 when `--use-msa-server` and/or
  `--use-templates-server` are set — the MSA step calls `https://api.colabfold.com` directly
  (`chai_lab/data/dataset/msas/colabfold.py:41`, default `host_url="https://api.colabfold.com"`, code
  comment: *"N.B. this function ... is copied from https://github.com/sokrypton/ColabFold"*). **This
  confirms, from Chai-1's own source rather than by analogy, that Chai-1 and Boltz-2 share the exact
  same ColabFold/MMseqs2 server as their default remote-MSA dependency** — the shared single point of
  failure the Part A review flagged is real and specific, not a guess.
- **GPU vendor portability — the highest-value correction in this brief.**
  - **Proven from `requirements.in` and repo-wide grep:** the dependency manifest contains **no**
    `flash-attn`, **no** `triton`, **no** `cuequivariance*`, **no** ROCm/HIP/XPU package of any kind. A
    repo-wide `grep -rniE 'flash|triton|cuequivariance|rocm|\bhip\b|xpu'` across every `.py`, `.toml`,
    `.in`, `.txt` and `Dockerfile*` returns **zero real hits** (the one match, a `[HIP]` in a residue
    modification example string in `chai_lab/data/parsing/structure/sequence.py`, is an incidental
    3-letter chemical-component code, not the AMD HIP platform). **The prior brief's central
    speculation — a probable flash-attn-class CUDA-only dependency — is not supported by the
    repository and should be retracted.** The only compute dependency is `torch>=2.3.1` (comment in
    `requirements.in`: *"2.2 is broken, latest-patch versions 2.3.1 - 2.7.1 are confirmed to work
    correctly"*) — a plain, vendor-neutral PyTorch pin.
  - **Also proven:** the model is shipped not as Python `nn.Module` source with custom CUDA kernels,
    but as six separately-downloaded **TorchScript-exported** components loaded via `torch.jit.load`
    (`feature_embedding.pt`, `bond_loss_input_proj.pt`, `token_embedder.pt`, `trunk.pt`,
    `diffusion_module.pt`, `confidence_head.pt` — `chai_lab/chai1.py:679-897`), plus a separately traced
    ESM2 checkpoint whose filename is itself evidence of the attention implementation:
    `traced_sdpa_esm2_t36_3B_UR50D_fp16.pt` (`chai_lab/data/dataset/embeddings/esm.py:21`) — "sdpa"
    indicates PyTorch's native `scaled_dot_product_attention`, not a custom/flash CUDA kernel. This is
    a positive portability signal PyTorch SDPA has backend dispatch for CUDA, ROCm and (partially) other
    accelerators, unlike a hand-written CUDA extension.
  - **Also proven, and a real constraint working the other way:** `chai_lab/chai1.py` calls
    `torch.cuda.empty_cache()` **unconditionally** three times (lines 607, 780, 888), regardless of the
    `device` argument, and both `run_inference` (line 535) and `run_folding_on_context` (line 604)
    hard-code the fallback device to `torch.device("cuda:0")` when `device=None`. On a ROCm-built
    PyTorch, `torch.cuda.*` is transparently remapped to HIP by PyTorch itself, so these calls would
    likely still work under `device="cuda:0"` semantics on AMD — but this is **PyTorch's own ROCm
    compatibility layer being relied on implicitly, not anything chai-lab does explicitly, and it is
    untested in this repo** (no ROCm CI, no AMD mention anywhere). On Intel XPU, PyTorch exposes a
    separate `torch.xpu` namespace with no such `torch.cuda` aliasing, so these three hard-coded calls
    would need to be patched before an Aurora port could even be attempted, independent of whether the
    underlying ops are portable.
  - **README states outright, and this is a direct requirement claim, not an inference:** *"This Python
    package requires Linux, Python 3.10 or later, and a GPU with CUDA and bfloat16 support. We
    recommend using an A100 80GB or H100 80GB or L40S 48GB chip, but A10 and A30 will work for smaller
    complexes."* bfloat16-capable hardware means Ampere-class (compute capability ≥8.0) or newer —
    this maps cleanly onto Polaris/Delta/Bridges-2/Expanse (A100/H100) and excludes nothing there.
  - **Net, evidence-based assessment:** CUDA is the only *proven* path (stated by the README, exercised
    by every example, and the only vendor with a hardcoded default). ROCm is **plausible but unproven**
    — no flash-attn-class blocker exists, but three hardcoded `torch.cuda` calls make it untested rather
    than free. XPU/SYCL is **the least likely of the three** because those same three call sites have no
    PyTorch-provided compatibility shim on Intel. This reverses the prior brief's "least-portable tool
    in this cluster" framing on the CUDA-only-dependency point specifically, while confirming its
    caution about Frontier/Aurora as unverified.
- **State model:** stateless per prediction call. Unlike Boltz-2 (which skips already-completed
  predictions found in `out_dir`), Chai-1 has **no cache/skip mechanism** — `run_inference` asserts the
  output directory is empty and raises `AssertionError` otherwise, so a retried job must be pointed at a
  fresh directory or have the old one cleared first; there is no partial-resume path.
- **Data locality:** shared-FS required for `$CHAI_DOWNLOADS_DIR` (weights cache) and `output_dir`; MSA
  directory if precomputed `.aligned.pqt` files are used.
- **Staging burden:** model weights, no sequence/structure database. Verified download mechanism —
  `chai_lab/utils/paths.py:download_if_not_exists` performs an unauthenticated `requests.get` (with a
  file-lock guard) against `https://chaiassets.com/chai1-inference-depencencies/...` for each of: the
  six `.pt` trunk/diffusion/confidence components (`COMPONENT_URL` template), `conformers_v1.apkl`, and
  the ESM2-3B `traced_sdpa_esm2_t36_3B_UR50D_fp16.pt` checkpoint. Default landing directory is
  `<chai_lab install>/downloads`, overridable via the `CHAI_DOWNLOADS_DIR` env var (documented in
  README). **No exact total size is stated anywhere in the repo** — do not treat any figure as sourced;
  a defensible order-of-magnitude estimate is that the fp16 ESM2-3B checkpoint alone is roughly
  `3e9 params × 2 bytes ≈ 6 GB`, plus the six trunk/diffusion/confidence components, so total staging is
  plausibly in the same single-digit-to-low-double-digit-GB range as Boltz-2's ~3.6 GB, likely somewhat
  larger because of the bundled 3B-parameter PLM — **measure before budgeting, this is an estimate, not
  a fact from the repo.** Critically, **there is no `chai-lab download-weights`-style subcommand**;
  staging happens lazily, component-by-component, on first use of `chai-lab fold` — on an HPC compute
  node without egress, the first job will fail mid-run trying to reach `chaiassets.com` unless the cache
  has already been pre-populated (e.g. run once with `CHAI_DOWNLOADS_DIR` pointed at shared storage from
  a node that does have egress, then reuse that path).
- **Container availability:** community only. `Dockerfile.chailab` in the refcode builds an
  Ubuntu-22.04 + CUDA-softlinked devcontainer image for Chai's own development workflow (it symlinks
  `libcuda.so.1` → `libcuda.so`, confirming the dev image assumes an NVIDIA host runtime) — this is a
  **devcontainer for contributing to chai-lab**, not a published, versioned inference image. No official
  Apptainer/Singularity image is present in the refcode or referenced from the README.

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA, A100/H100):** the only platform class with direct, repo-stated support —
  matches the README's own recommended hardware list. `pip install chai_lab==0.6.1` (or
  `pip install git+https://github.com/chaidiscovery/chai-lab.git` for the daily build) with a plain
  `torch>=2.3.1,<=2.7.1`-range install is the documented mechanism; no `[cuda]` extra is needed (unlike
  Boltz) since there is no CUDA-specific compiled-kernel package to opt into or out of.
- **Frontier (AMD MI250X):** unverified, not blocked by a flash-attn/triton/cuequivariance dependency
  (there is none), but blocked in practice today by three hardcoded `torch.cuda.empty_cache()` calls and
  a `torch.device("cuda:0")` default that rely on PyTorch's ROCm `torch.cuda`-aliasing behaving
  identically to real CUDA for this code path — untested by Chai Discovery, no community ROCm report
  found in the refcode. Treat as a research spike (try a ROCm-built PyTorch 2.3–2.7 wheel, verify the
  three hardcoded calls don't error), not a known-good path.
- **Aurora (Intel PVC / SYCL-XPU):** the least defensible target of the three. The same hardcoded
  `torch.cuda` calls have no direct Intel `torch.xpu` equivalent, so a port requires source patches to
  chai-lab itself (or an Intel CUDA-compatibility shim), not just an alternate PyTorch build. No
  evidence of any XPU attempt anywhere in the repo.
- **Chai-2:** not self-hostable on any DOE/ACCESS platform — no code or weights exist in this refcode or
  anywhere public; per its own technical-report citation it is a commercial antibody-design product, out
  of scope for on-cluster deployment regardless of GPU vendor.

## Agentic surface
- **Native MCP:** no. No Chai-specific MCP server is referenced anywhere in the refcode; none of the
  general-purpose structure-prediction MCP servers used elsewhere in this project cover Chai
  specifically.
- **Parameters worth exposing for autonomous variation** (all defaults/ranges read directly from
  `run_inference`'s signature, `chai_lab/chai1.py:497-524`, and the hard architectural caps in
  `chai_lab/data/dataset/all_atom_feature_context.py:20-21`):

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `use_esm_embeddings` / `use_msa_server` / `msa_directory` | flags | any one combination | `use_esm_embeddings=True`, others off | Embeddings-only (default) is fast and self-contained; `use_msa_server` trades staging-free operation for a P5 network dependency on `api.colabfold.com` and generally improves accuracy per README |
| `num_diffn_samples` | int | 1–~10 (unbounded by code, cost-bounded in practice) | 5 | Structural ensemble diversity vs. linear GPU-time cost; matches README's stated default behavior ("generates five sample predictions") |
| `num_trunk_recycles` | int | 1–10 (AF3-family convention) | 3 | More recycling passes → marginally better accuracy, near-linear cost |
| `num_diffn_timesteps` | int | 50–200-ish | 200 | Diffusion denoising steps; fewer steps trade accuracy for speed |
| `num_trunk_samples` | int | 1–small integer | 1 | Independent trunk (not just diffusion) resampling; multiplies cost directly, writes to `trunk_{i}/` subdirectories |
| `recycle_msa_subsample` | int | 0 (off) or small integer | 0 | Subsamples the MSA differently each recycle for diversity, when an MSA is present |
| `low_memory` | bool | on/off | `True` | Keeps intermediate embedding/token-embedder tensors on CPU between component calls (`return_on_cpu=low_memory`, `chai_lab/chai1.py:683,709,723`), trading extra host↔device transfer time for materially lower peak GPU memory — the lever to flip first on GPU-OOM |
| `--use-templates-server` / `--template-hits-path` | flag / path | on/off | off | Adds RCSB-sourced structural templates; another P5 dependency when server mode is used |

- **Hard architectural caps — must NOT be agent-varied, they are not tunables:** the model is exported
  as TorchScript graphs at fixed padded token counts `AVAILABLE_MODEL_SIZES = [256, 384, 512, 768, 1024,
  1536, 2048]` (`chai_lab/data/collate/utils.py:13`) with atom count derived as `23 * n_tokens`; an
  input exceeding **2048 tokens total** raises `UnsupportedInputError` (`raise_if_too_many_tokens`,
  `chai_lab/chai1.py:255-260`) rather than degrading — this is a hard ceiling, not a knob. Likewise
  `MAX_NUM_TEMPLATES = 4` and `MAX_MSA_DEPTH = 16_384` (`chai_lab/data/dataset/all_atom_feature_context.py:20-21`)
  raise loud errors if exceeded. The restraints file's `confidence` and `min_distance_angstrom` columns
  are **documented in `examples/restraints/README.md` as currently unused by the model** ("included in
  this format for future-proofing") — an agent must not treat these as real levers; setting a low
  `confidence` on a restraint silently does nothing.

## Failure modes & what the agent must check
- **Loud failure (all confirmed from source):** input token count > 2048 → `UnsupportedInputError`
  (`chai_lab/chai1.py:255-260`); template count > 4 or MSA depth > 16,384 → `UnsupportedInputError`
  (same file, lines 262-278); restraint residue/index mismatch against the actual sequence → explicit
  error (README: *"the code internally checks that the given residue at the given index matches the
  input sequence, and will throw an error if they do not match"*); non-empty `output_dir` on a fresh
  `run_inference` call → `AssertionError` (no partial-resume, unlike Boltz's cache-and-skip behavior).
- **Silent bad output — misleading `aggregate_score` for monomers.** `aggregate_score = 0.2*complex_ptm
  + 0.8*interface_ptm - 100*has_inter_chain_clashes` (`chai_lab/ranking/rank.py`). For a single-chain
  input, `interface_ptm` is computed against an empty "other chains" key set
  (`chai_lab/ranking/ptm.py:91-115`) and evaluates to 0, not NaN or a flagged sentinel — so a
  **monomer's best possible `aggregate_score` is capped near 0.2**, not the multimer-scale ~1.0, purely
  as an artifact of the formula's 0.8 weight on interface pTM. An agent that ranks or thresholds
  `aggregate_score` across a mixed batch of monomer and multimer jobs without normalizing for chain
  count will silently and systematically discard good monomer predictions. **Check:** branch the
  accept/reject logic on chain count — for monomers, use `ptm` (complex pTM) directly, not
  `aggregate_score`.
- **Silent bad output — ranking scalar ignores pLDDT entirely.** Unlike Boltz-2's `confidence_score`
  (`0.8*complex_plddt + 0.2*iptm`), Chai-1's `aggregate_score` has no pLDDT term at all. A structure with
  excellent global pTM/ipTM but locally disordered regions (poor per-residue pLDDT) will not be
  penalized by `aggregate_score`. **Check:** the agent's gate should independently threshold the
  per-atom pLDDT written into the CIF B-factor column (or the `plddt` tensor from the Python API), not
  rely on `aggregate_score` alone — the same general principle documented for every other AF3-class
  co-folder in this cluster.
- **Silent bad output — unbounded/negative `aggregate_score` on clashing structures.** The `-100 *
  has_inter_chain_clashes` term means a clashing prediction can score far below 0, not just "low" —
  an agent must not assume `aggregate_score ∈ [0, 1]` when writing threshold logic; check
  `has_inter_chain_clashes`/`chain_chain_clashes` from `scores.model_idx_*.npz` directly rather than
  inferring clash status from a low aggregate score.
- **Padding-bucket cost cliff, not exactly a failure but a budgeting trap:** because inference runs at
  one of the seven fixed `AVAILABLE_MODEL_SIZES` token buckets, a 260-token input and a 380-token input
  cost the same (both pad to 384), while crossing a bucket boundary (e.g. 385 tokens) triggers a step
  jump to the 512 bucket. An agent doing adaptive batch-size/cost estimation should key off the bucket,
  not the raw token count.

## Cost per unit of work
- **Unit of work:** one `chai-lab fold` call on one complex, defaults (`num_trunk_recycles=3,
  num_diffn_timesteps=200, num_diffn_samples=5, num_trunk_samples=1`) — i.e. one trunk forward pass plus
  five independent diffusion-sample structures and confidence-head evaluations.
  - **Not benchmarked in this repo** — no wall-clock numbers, profiling output, or `pytest`-based timing
    exist in the refcode. Do not carry forward the prior brief's "single-digit-minutes" estimate as
    sourced; it remains an architectural analogy to Boltz/RF3/AF3 (comparable trunk+diffusion design),
    not a Chai-1-specific measurement. Measure empirically before any budget-aware policy depends on it.
- **Resource shape:** 1 GPU per call (`device` defaults to `cuda:0`; no built-in multi-GPU sharding
  observed in `chai_lab/chai1.py`). `low_memory=True` (default) reduces peak VRAM at the cost of extra
  CPU↔GPU transfers; `--num-diffn-samples` and `--num-trunk-samples` both multiply cost roughly linearly
  since each sample is a full diffusion/confidence pass.
- **Checkpointable:** no. Confirmed above under Compute pattern/State model — output directory must be
  empty at the start of a run, and there is no resume mechanism; a preempted job must restart the full
  `chai-lab fold` call into a clean directory.

## Verdict
**Recommended** — upgraded from the prior **Defer**, whose stated reversal condition (a direct repo
read) has now been satisfied. Chai-1 is not promoted all the way to **Core** because it does not carry
its own weight class the way Boltz-2 does (no affinity head — Boltz-2 remains the only tool in this
cluster with a jointly-trained binding-affinity output, and stays Core for that reason) and because its
GPU-portability story, while no longer plausibly "CUDA-only by dependency," is still **unverified**
off-CUDA in practice (three hardcoded `torch.cuda` calls, no ROCm/XPU test evidence anywhere in the
repo). What justifies carrying both Chai-1 and Boltz-2 rather than picking one: Chai-1's no-MSA mode is
its *primary*, not fallback, execution path (a real architectural difference from Boltz's
explicitly-discouraged `msa: empty`), and its atom-level restraint/glycan grammar gives the agent a
finer control surface for covalently-modified and glycosylated targets than Boltz's brief documents.
Concretely: use Boltz-2 as the default small-molecule-binding filter (it alone predicts affinity); use
Chai-1 where MSA generation is unavailable/undesirable and accuracy matters more than ESMFold alone
provides, or where covalent/glycan restraint specification is needed. The corrected, source-grounded
reason this isn't Core outright is that (a) no wall-clock, memory, or off-CUDA evidence exists in the
repo to size it against a budget, and (b) the lack of a resume/skip mechanism (unlike Boltz) makes it a
worse citizen under walltime-constrained scheduling until that gap is either accepted or worked around.
**Chai-2 remains Reject**, confirmed rather than merely carried forward: this refcode contains zero
Chai-2 code, config, or weights — only a citation to its technical report — consistent with it being a
closed, partnership-only product with no self-hostable path on any DOE/ACCESS platform.

## Sources
All claims below are **verified directly against the refcode** unless explicitly marked web-sourced.
- `<workspace>/impress-a-refcodes/tools/chai-lab/pyproject.toml`
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/__init__.py` (version string)
- `<workspace>/impress-a-refcodes/tools/chai-lab/README.md`
- `<workspace>/impress-a-refcodes/tools/chai-lab/LICENSE`
- `<workspace>/impress-a-refcodes/tools/chai-lab/requirements.in`, `requirements.dev`
- `<workspace>/impress-a-refcodes/tools/chai-lab/Dockerfile.chailab`
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/main.py` (CLI registration)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/chai1.py` (`run_inference`,
  `run_folding_on_context`, `StructureCandidates`, device handling, token/template/MSA caps, output
  writing — lines cited inline above)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/ranking/rank.py`,
  `chai_lab/ranking/ptm.py`, `chai_lab/ranking/plddt.py`, `chai_lab/ranking/clashes.py` (score field
  names and the `aggregate_score` formula)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/utils/paths.py` (weight download
  mechanism and URLs)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/data/dataset/embeddings/esm.py`
  (ESM2-3B traced checkpoint, URL, device handling)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/data/dataset/msas/colabfold.py`
  (ColabFold/MMseqs2 server call, default `host_url`, attribution comment)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/data/collate/utils.py`
  (`AVAILABLE_MODEL_SIZES` fixed padding buckets)
- `<workspace>/impress-a-refcodes/tools/chai-lab/chai_lab/data/dataset/all_atom_feature_context.py`
  (`MAX_MSA_DEPTH`, `MAX_NUM_TEMPLATES`)
- `<workspace>/impress-a-refcodes/tools/chai-lab/examples/predict_structure.py`,
  `examples/msas/predict_with_msas.py`, `examples/msas/README.md`, `examples/restraints/README.md`,
  `examples/restraints/contact.restraints`, `examples/restraints/pocket.restraints`,
  `examples/covalent_bonds/README.md`, `examples/covalent_bonds/predict_covalent_ligand.py`
- `git log` / `git describe` output against the refcode checkout (commit `66c38d1`, tag `v0.6.1-20-g66c38d1`)
- Web-sourced, not re-verified in this pass: Chai-1 technical report
  (https://www.biorxiv.org/content/10.1101/2024.10.10.615955), Chai-2 technical report
  (bioRxiv doi 10.1101/2025.07.05.663018, cited in `README.md`'s citation block but not otherwise
  present in the refcode) — used only for background framing, not for any claim in Compute pattern,
  Deployment, or Failure modes above.
- Compared throughout against `<workspace>/impress-a/docs/phase1-partA-toolkit/briefs/boltz.md`
  for peer-consistency (constraint schema, MSA-server flag pattern, confidence-score formula, cache/skip
  behavior).
- No MCP server found for Chai (absence inferred from refcode contents, not exhaustively re-searched on
  the web in this pass).
