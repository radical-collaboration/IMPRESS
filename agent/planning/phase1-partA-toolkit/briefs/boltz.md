# Boltz-2

**One-line identity.** An open-source, MIT-licensed AF3-class biomolecular co-folding model that jointly predicts complex structure *and* small-molecule binding affinity in one model.

## Identity
- **Version / release examined:** `pyproject.toml` → `name = "boltz"`, `version = "2.2.1"`, `requires-python = ">=3.10,<3.13"`. Refcode: `<workspace>/impress-a-refcodes/tools/boltz/`.
- **Provenance:** MIT Technology / Wohlwend, Corso, Passaro et al. (originally MIT CSAIL-affiliated, now Boltz/`jwohlwend/boltz` on GitHub). **MIT license**, code and weights, explicitly for both academic and commercial use (README: *"All the code and weights are provided under MIT license, making them freely available for both academic and commercial uses"*). Boltz-1 paper: doi 10.1101/2024.11.19.624167. Boltz-2 paper: doi 10.1101/2025.06.14.659707.
- **Maturity:** production-grade for a research tool — versioned PyPI releases, `[project.scripts] boltz = "boltz.main:cli"`, NVIDIA has packaged it as a NIM (`docs.nvidia.com/nim/bionemo/boltz2`), and it is widely used as a community structure/affinity predictor (e.g., ChimeraX has a native Boltz tool). Evaluation/training code for Boltz-2 specifically is marked "coming soon" in the README as of the examined snapshot.

## Scientific role
Joint structure + binding-affinity co-folder. Serves **all four** in-scope problem classes, but is the **only tool in this cluster with a native affinity head**, making it the primary small-molecule-binding filter: it predicts not just pose but a quantitative affinity estimate and a binder/decoy probability in the same call. Pipeline stage: **predict** (structure) + **score** (affinity), in one invocation.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, `[project.scripts] boltz = "boltz.main:cli"`. `boltz predict <INPUT_PATH> [OPTIONS]`.
- **Inputs:** a `.yaml` file (preferred) or `.fasta` (deprecated) describing `sequences` (protein/dna/rna/ligand entities, each with optional `msa`, `modifications`, `cyclic`), optional `constraints` (`bond`, `pocket`, `contact`), optional `templates` (CIF/PDB), optional `properties: [affinity: {binder: CHAIN_ID}]`. `INPUT_PATH` may also be a directory of YAML/FASTA files for batched processing.
- **Outputs:** under `out_dir/predictions/<input_name>/`: `<input>_model_<k>.cif` (or `.pdb`) structures ranked by confidence, `confidence_<input>_model_<k>.json` (`confidence_score`, `ptm`, `iptm`, `ligand_iptm`, `protein_iptm`, `complex_plddt`, `complex_iplddt`, `complex_pde`, `complex_ipde`, `chains_ptm`, `pair_chains_iptm`), `pae_*.npz`/`pde_*.npz`/`plddt_*.npz` (per-token matrices/vectors), and — if affinity was requested — `affinity_<input>.json` (`affinity_pred_value`, `affinity_probability_binary`, plus per-ensemble-member `_1`/`_2` variants).
- **A concrete example**, taken verbatim from `examples/affinity.yaml` in the refcode:
```yaml
version: 1
sequences:
  - protein:
      id: A
      sequence: MVTPEGNVSLVDESLLVGVTDEDRAVRSAHQFYERLIGLWAPAVMEAAHELGVFAALAEAPADSGELARRLDCDARAMRVLLDALYAYDVIDRIHDTNGFRYLLSAEARECLLPGTLFSLVGKFMHDINVAWPAWRNLAEVVRHGARDTSGAESPNGIAQEDYESLVGGINFWAPPIVTTLSRKLRASGRSGDATASVLDVGCGTGLYSQLLLREFPRWTATGLDVERIATLANAQALRLGVEERFATRAGDFWRGGWGTGYDLVLFANIFHLQTPASAVRLMRHAAACLAPDGLVAVVDQIVDADREPKTPQDRFALLFAASMTNTGGGDAYTFQEYEEWFTAAGLQRIETLDTPMHRILLARRATEPSAVPEGQASENLYFQ
  - ligand:
      id: B
      smiles: 'N[C@@H](Cc1ccc(O)cc1)C(=O)O'
properties:
  - affinity:
      binder: B
```
run as (with remote MSA, per README): `boltz predict input_path --use_msa_server`.

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job); secondary P5 when `--use_msa_server` is set (the MSA step becomes a network call to `https://api.colabfold.com` before the GPU stage — record the fallback: pre-computed local `.a3m`/CSV MSA input if egress is unavailable).
- **GPU vendor portability:** **CUDA-primary, CUDA-accelerated-kernel-optional, HIP/XPU unproven.** `pyproject.toml`'s `cuda` extra pulls `cuequivariance_ops_cu12`, `cuequivariance_ops_torch_cu12`, `cuequivariance_torch` (all CUDA-12-specific compiled wheels) — this is opt-in acceleration, not a hard requirement: the base `dependencies` list is plain `torch>=2.2`, and the README's troubleshooting section says explicitly *"When running on old NVIDIA GPUs, you may encounter an error related to the `cuequivariance` library. In this case, you should run the model with the `--no_kernels` flag, which will disable the use of the `cuequivariance` library... This may result in slightly lower performance, but it will allow you to run the model."* This confirms a CUDA-free fallback path exists by design (the same `--no_kernels` mechanism is the natural route to try on ROCm/XPU). No AMD/Intel port was found in search beyond a **community Tenstorrent fork** (`moritztng/tt-boltz`, cited in the README) — evidence that porting off-CUDA is feasible but has only been done for a third vendor, not AMD/Intel. NVIDIA's own Boltz-2 NIM documentation states NVIDIA-only tested configurations (A100/H100/L40S/B200/RTX6000 Ada). Treat Frontier/Aurora as **unproven, worth a `--no_kernels` smoke test**, not a known-good path.
- **State model:** stateless per prediction; `--override` forces recompute, and without it Boltz reuses cached `processed/` files and existing predictions in `out_dir` if present — a lightweight, filesystem-based checkpoint/skip mechanism.
- **Data locality:** shared-FS required for `out_dir`/`--cache`; MSA files (if precomputed) must be reachable; otherwise self-contained.
- **Staging burden:** model weights + CCD (chemical component dictionary), not sequence/structure databases. Default `--cache ~/.boltz` (override via `BOLTZ_CACHE`). Reported sizes: network weights ~3.3 GB, CCD (`ccd.pkl`) ~0.3 GB — a low, one-time download, dramatically smaller than AF2/AF3 genetic databases. No local MSA database staging is required at all if `--use_msa_server` is used (P5 path).
- **Container availability:** community (NVIDIA NIM container is official-from-NVIDIA but third-party relative to the Boltz project itself; ChimeraX ships a bundled Boltz tool). No first-party Apptainer/Singularity image confirmed in refcode.

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA):** primary supported path — `pip install boltz[cuda] -U`. Straightforward; matches the NVIDIA NIM's own tested hardware list (A100/H100/L40S/B200).
- **Aurora (Intel PVC):** no documented support. The `--no_kernels` fallback plus plain-PyTorch base dependencies make this a plausible-but-unverified port; would require a working Intel XPU PyTorch build (as RF3/Foundry has documented) and testing whether Boltz's other ops (RDKit, custom Triton/CUDA kernels if any beyond cuequivariance — not fully audited here) are portable. Flag as a research spike, not a deployment plan.
- **Frontier (AMD MI250X):** same situation as Aurora — `--no_kernels` should in principle sidestep the one confirmed CUDA-only dependency, but no evidence of anyone running Boltz on ROCm was found. Unverified.
- **Module/conda/apptainer:** `pip install` into a fresh venv is the documented and only first-party mechanism (`git clone` + `pip install -e .[cuda]` for daily-build access). No license gate.

## Agentic surface
- **Native MCP:** no. Search turned up no Boltz-specific MCP server (community or official).
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `--recycling_steps` | int | 3–10 | 3 (10 matches AF3 defaults) | More recycles → modestly better accuracy, near-linear wall-clock cost |
| `--diffusion_samples` | int | 1–25 | 1 (25 matches AF3 defaults) | More independent structural samples → better mode coverage / more reliable top-ranked pick, roughly linear cost |
| `--sampling_steps` | int | 50–200 | 200 | Diffusion denoising steps; lower is faster with some quality loss |
| `--use_msa_server` | flag | on/off | off | Trades local MSA staging burden for P5 network dependency (viable given full egress per platform assumptions) |
| `--msa_pairing_strategy` | enum | `greedy`/`complete` | `greedy` | Affects multi-chain MSA pairing quality vs. depth for complexes |
| `--max_msa_seqs` / `--subsample_msa` / `--num_subsampled_msa` | int / flag / int | 256–8192 / on-off / 256–1024 | 8192 / False / 1024 | MSA depth vs. wall-clock and memory; subsampling is the direct lever for adaptive-cost campaigns |
| `--use_potentials` | flag | on/off | off | Inference-time physical-plausibility potentials; improves pose realism at extra sampling cost |
| `--diffusion_samples_affinity` / `--sampling_steps_affinity` | int | 1–5 / 50–200 | 5 / 200 | Same trade-off as structure sampling, but for the affinity head specifically |
| `--step_scale` | float | 1.0–2.0 | 1.5 (Boltz-2) | Lower = more sample diversity, higher = more consensus/confidence |

- **Parameters that must NOT be agent-varied:** `msa: empty` (single-sequence mode) should not be silently substituted for a missing MSA — README explicitly says this "reduces accuracy" and is "not recommended"; an agent falling back to it must flag the resulting prediction as lower-trust, not treat it as equivalent. `--affinity_mw_correction` should be set deliberately per problem class (molecular-weight correction changes the affinity value's meaning) rather than toggled per-call. Ligand size for the affinity head is a hard architectural limit, not a tunable: **must be ≤128 heavy+H atoms** (RDKit `RemoveHs` count) and the docs recommend staying ≤56 atoms — the agent must reject/flag affinity requests above this rather than silently degrade.

## Failure modes & what the agent must check
- **Loud failure:** malformed YAML, ligand SMILES that fails RDKit parsing, affinity requested on a non-ligand chain (`binder` must be a single ligand chain) — raises errors.
- **Silent bad output (affinity on wrong target class):** the docs are explicit — *"Boltz only supports the computation of affinity of small molecules to protein targets, if ran with an RNA/DNA/co-factor target, the code will not crash but the output will be unreliable."* This is a documented silent-failure mode the agent must gate against by checking the `binder` chain's entity type before trusting `affinity_*.json`.
- **Silent bad output (oversized ligand):** affinity head was trained on ligands ≤56 heavy atoms; predictions on larger ligands (up to the 128-atom hard cap) will run without error but degrade in reliability — not flagged in the output JSON itself, so the agent must check ligand atom count independently.
- **Silent bad output (single-sequence mode):** `msa: empty` runs without error but at reduced accuracy — the agent should track which predictions used this mode and discount their confidence scores accordingly, since the JSON confidence fields do not self-report MSA depth.
- **Specific checks:** parse `confidence_<input>_model_<k>.json` for `confidence_score` (= 0.8·complex_plddt + 0.2·iptm, the documented ranking scalar), `ptm`/`iptm`/`ligand_iptm`/`protein_iptm` for structure trust, and — separately — `affinity_probability_binary` (binder-vs-decoy classification, use for accept/reject hit-discovery gating) vs. `affinity_pred_value` (log10 IC50 in µM, use only for *relative* ranking among already-called binders in hit-to-lead, never as an absolute reject threshold per the docs' own guidance: *"should only be used when comparing different active molecules, not inactives"*).

## Cost per unit of work
- **Unit of work:** one `boltz predict` call, one complex, defaults (`--recycling_steps 3 --diffusion_samples 1 --sampling_steps 200`).
- **Typical wall-clock:** not independently benchmarked here; the model is explicitly positioned (Boltz-2 paper/README) as approaching FEP accuracy "while running 1000x faster," implying single-digit-minute predictions on a modern GPU at default settings for typical complex sizes — treat as vendor-stated and verify empirically. AF3-matched settings (`--recycling_steps 10 --diffusion_samples 25`) are explicitly called out in the docs as "significantly longer."
- **Resource shape:** 1 GPU per `--devices 1` (default); `--max_parallel_samples` (default 5) controls how many of the `diffusion_samples` run concurrently on that GPU.
- **Checkpointable:** cache-based skip of already-completed predictions (no mid-prediction resume); `--override` forces full recompute.

## Verdict
**Core.** Boltz-2 is the single best-fit tool for the small-molecule-binding problem class in this cluster because it is the only one with a native, jointly-trained affinity head, it carries the most permissive license of the group (MIT, unrestricted commercial use, unlike AF3), and its staging burden is trivially small (~3.6 GB total vs. hundreds of GB to TB for AF2/AF3 local genetic databases) with a documented, first-party remote-MSA path (`--use_msa_server`) that fits this project's full-egress P5 model directly. Its chief open risk is GPU portability off CUDA: the `--no_kernels` fallback is real but AMD/Intel deployment is unverified and should be validated early rather than assumed.

## Sources
- `<workspace>/impress-a-refcodes/tools/boltz/pyproject.toml`
- `<workspace>/impress-a-refcodes/tools/boltz/README.md`
- `<workspace>/impress-a-refcodes/tools/boltz/docs/prediction.md`
- `<workspace>/impress-a-refcodes/tools/boltz/examples/affinity.yaml`, `pocket.yaml`, `prot_no_msa.yaml`, `prot_custom_msa.yaml`
- [Boltz-2 preprint](https://doi.org/10.1101/2025.06.14.659707), [Boltz-1 preprint](https://doi.org/10.1101/2024.11.19.624167)
- [NVIDIA NIM for Boltz2 support matrix](https://docs.nvidia.com/nim/bionemo/boltz2/1.2.0/support-matrix.html) — GPU support inferred as NVIDIA-only from this page; not verified against Boltz upstream directly.
- `tt-boltz` Tenstorrent fork (cited in Boltz README) as evidence a non-CUDA port is feasible in principle — not independently inspected.
- No MCP server found for Boltz (search performed; absence inferred, not exhaustively verified).
