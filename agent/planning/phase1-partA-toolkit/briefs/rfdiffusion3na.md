# RFdiffusion3NA (RFD3NA)

**One-line identity.** The nucleic-acid-extended variant of RFdiffusion3: an all-atom diffusion model that can design multi-polymer assemblies (protein–DNA, protein–RNA, DNA/RNA-only, aptamers) under the same motif/hotspot/ligand constraint grammar as RFD3.

## Identity
- **Version / release examined:** `tools/foundry/pyproject.toml` — packaged as `models/rfd3na/src/rfd3na`, `[project.scripts] rfd3na = "rfd3na.cli:app"`, optional extra `rfd3na = ["pydantic>=2.8"]`. Checkpoint registered as `rfd3na-1190.ckpt` (default) in `src/foundry/inference_engines/checkpoint_registry.py`, with a preprint-figure checkpoint `rfd3na-890.ckpt` also referenced in `models/rfd3na/README.md`.
- **Provenance:** RosettaCommons / Institute for Protein Design. BSD license (shared `tools/foundry/LICENSE.md`). Refcode: `tools/foundry/models/rfd3na/`. Same preprint family as RFD3 (Butcher et al., bioRxiv 2025.09.18.676967 — the README links a `v3` version of the same bioRxiv ID for the NA extension).
- **Maturity:** active research. Younger and narrower-audience than RFD3 within the same repo; shares the majority of its codebase and infra with RFD3 (same `engine`, `attention.py` cuEquivariance try/except pattern, same config layering via `defaults: [base, _self_]`).

## Scientific role
Generative structure design (**generate** stage) extended to nucleic acids. Serves **de novo binder design** where the target or the binder is DNA/RNA (protein-NA interfaces, NA aptamers against small molecules — e.g. the shipped `AMP_aptamer`/`FMN_aptamer` examples), and by extension **small-molecule binding** when the designed polymer is an RNA/DNA aptamer rather than a protein pocket. Out of scope for **stability/thermostabilization** and only tangentially useful for **enzyme/catalytic design** (would require protein components in a multipolymer complex, which RFD3NA supports but does not specialize in). This is a narrower slice of the four in-scope problem classes than RFD3.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, via the `rfd3na` entrypoint. `models/rfd3na/src/rfd3na/cli.py` follows the identical Typer-wraps-Hydra pattern as RFD3 (`compose(config_name="inference", overrides=args)`), so invocation semantics and dotted-key overrides are the same.
- **Real argv, from `models/rfd3na/README.md`:**
  ```bash
  rfd3na design out_dir=logs/inference_outs/demo/0 \
    inputs=models/rfd3na/docs/examples/atom23_design.json \
    skip_existing=False dump_trajectories=True prevalidate_inputs=True \
    read_sequence_from_sequence_head=False
  ```
  Note the README explicitly recommends `read_sequence_from_sequence_head=False` as a global setting for RFD3NA (this differs from RFD3's default of `True` — see Parameters section).
- **Inputs:** same InputSpecification JSON/YAML grammar as RFD3, plus an `R`/`D` contig suffix for RNA/DNA chains. Per README: `"10-10,20-20R,30-30D"` generates a 10-residue protein chain, a 20-nt RNA chain, and a 30-nt DNA chain. `select_hbond_donor`/`select_hbond_acceptor` are used for base-pairing/aptamer conditioning (requires HBPLUS, same optional install as RFD3).
- **Outputs:** designed multi-polymer structures (PDB/CIF) + JSON metadata sidecar, same conventions as RFD3.
- **A concrete example**, taken verbatim from `tools/foundry/models/rfd3na/docs/examples/atom23_design.json`:
  ```json
  "AMP_aptamer": {
      "input": "../input_pdbs/AMP.pdb",
      "ligand": "AMP",
      "contig": "40-50R",
      "length": "40-50",
      "ori_jitter": 1,
      "select_buried": {"AMP": "ALL"},
      "select_hbond_acceptor": {"AMP": "N7,O4',O1P,O2P,O3P,N3,N1"},
      "select_hbond_donor": {"AMP": "N6,O3',O2'"}
  }
  ```
  This designs a 40–50-nt RNA aptamer around a small-molecule ligand (AMP) using hydrogen-bond donor/acceptor conditioning — a direct instance of the small-molecule-binding problem class via a nucleic-acid scaffold.

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job) — identical scheduling profile to RFD3; single-checkpoint, single/multi-GPU inference within the agent's own allocation, no MPI coupling for inference.
- **GPU vendor portability:** **CUDA+SYCL-XPU, proven; HIP unproven** — same evidence and same caveats as RFD3. `models/rfd3na/src/rfd3na/model/layers/attention.py` contains the identical `try: from cuequivariance_torch import ... / except: _CUEQ_AVAILABLE = False` pattern, so RFD3NA inherits RFD3's graceful CUDA-kernel fallback and shares the same `foundry`-level XPU accelerator/strategy/precision plugins (`src/foundry/utils/xpu/`). No AMD/HIP/ROCm reference anywhere in the refcode (same repo-wide grep as RFD3's brief: zero hits).
- **State model:** checkpointable at design granularity via `skip_existing` (same mechanism as RFD3).
- **Data locality:** self-contained per invocation; shared-FS recommended for multi-stage pipelines.
- **Staging burden:** model weights, one additional ~similar-sized checkpoint (`rfd3na_1190.ckpt`) separate from the RFD3 checkpoint — i.e., running both models doubles the weight-staging cost. Downloaded via `foundry install rfd3na`.
- **Container availability:** official — same `rosettacommons/foundry` image as RFD3 (the `base-models` install target in `foundry install` includes `rfd3na`), same NVIDIA-oriented (`--nv`) assumption, no published XPU/ROCm variant.

## Deployment on DOE & ACCESS
Identical picture to RFD3 (same underlying infra, install path, and accelerator ladder):
- **Polaris / ACCESS (Delta, Bridges-2, Expanse — all CUDA):** works out of the box via the official container or `pip install "rc-foundry[rfd3na]"`.
- **Aurora (Intel XPU):** same documented pip-order caveat as RFD3 (`pip install torch --index-url .../whl/xpu` before `pip install "rc-foundry[all]"`, use `pip` not `uv`); no official container for XPU, build/module-based deployment required.
- **Frontier (AMD MI250X/HIP):** **not proven to run**, same reasoning as RFD3 — no HIP code path, no CI, no community report. Treat as an unverified R&D spike, not a deployment target, until someone runs it.

## Agentic surface
- **Native MCP:** no. Same repo-wide grep as RFD3 turned up zero `mcp`/`model context protocol` references anywhere in `tools/foundry`.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `contig` (with `R`/`D` suffixes) | `InputSelection` str | task-defined, e.g. `"40-50R"`, `"30-30D"` | required | Defines protein/RNA/DNA chain composition and length; the primary design-space lever, unique to this model over RFD3 |
| `select_hbond_donor` / `select_hbond_acceptor` | `InputSelection` dict | atom-name lists per residue/ligand | none | Central lever for aptamer/base-pairing design quality; requires HBPLUS installed |
| `diffusion_batch_size` / `n_batches` | int / int | same ranges as RFD3 | 8 / 1 | Same throughput-vs-memory trade-off as RFD3 |
| `inference_sampler.num_timesteps`, `step_scale`, `noise_scale`, `gamma_0` | int / float / float / float | same ranges as RFD3 | 200 / 1.5 / 1.003 / 0.6 | Same diversity-vs-designability trade-offs as RFD3 |
| `inference_sampler.cfg_features` (includes `bp_partners` in addition to RFD3's set) | list | subset of `[active_donor, active_acceptor, ref_atomwise_rasa, bp_partners]` | see `configs/inference_engine/rfdiffusion3na.yaml` | Adds base-pair-partner as a classifier-free-guidance zeroing feature, NA-specific |
| `read_sequence_from_sequence_head` | bool | — | `True` in shared config, but README recommends `False` for RFD3NA globally | **Caution:** unlike RFD3, upstream explicitly recommends overriding this default for RFD3NA runs — an agent template should set it, not leave it at the shared default |

- **Parameters that must NOT be agent-varied:**
  - Same list as RFD3 (`dialect`, `allow_realignment`, `ckpt_path`, `cleanup_guideposts`/`cleanup_virtual_atoms`) for the same reasons.
  - `BKBN`/`TIP` atom-selection shorthands — README states these "do not apply to nucleic acids... should specify corresponding atom names" — an agent must not reuse RFD3 protein shorthands verbatim for NA chains; silent misselection is possible if it does.

## Failure modes & what the agent must check
Same failure-mode categories as RFD3 (loud: missing checkpoint, invalid contig, OOM; silent: no-secondary-structure/garbage fold, understated `partial_t`), plus NA-specific ones:
- **Silent bad output specific to NA:** base-pairing/hydrogen-bond conditioning can be geometrically satisfied without producing a chemically sound duplex or aptamer pocket (analogous to the hotspot-conditioning risk in RFD3). Check post-hoc with a base-pair/H-bond geometry validator, not just successful exit.
- Reusing RFD3's `BKBN`/`TIP` atom shorthands on nucleic acid chains will silently select the wrong (or no) atoms rather than erroring — always verify atom-name selections against the polymer type.

## Cost per unit of work
No dedicated benchmark found for RFD3NA; given the shared architecture and near-identical config defaults (`diffusion_batch_size=8`, `num_timesteps=200`), assume the same order-of-magnitude cost as RFD3 (seconds–minutes per design on GPU, O(N²)-ish scaling with total token/atom count) until independently measured. Resource shape: 1 GPU, single node, checkpointable via `skip_existing`.

## Verdict
**Recommended.** RFD3NA earns inclusion because it extends "de novo binder design" and "small-molecule binding" into nucleic-acid space (protein-NA interfaces, NA aptamers) at essentially zero marginal infrastructure cost — it rides the same foundry install, checkpoint registry, Hydra CLI, and GPU-portability story as RFD3. It is not **Core** because it addresses a narrower slice of the four in-scope problem classes than RFD3 and is not needed for the majority of expected campaigns (protein binder/enzyme/small-molecule-pocket design). Include it as an available tool for when a campaign specifically calls for a nucleic-acid target or an aptamer-style small-molecule binder, but do not treat it as load-bearing for Phase 1 Part A's default toolchain.

## Sources
- `tools/foundry/pyproject.toml` (verified: `[project.scripts]`, `rfd3na` extra)
- `tools/foundry/models/rfd3na/README.md` (verified: install/run commands, checkpoint URLs, R/D contig syntax, `read_sequence_from_sequence_head=False` recommendation)
- `tools/foundry/models/rfd3na/docs/examples/atom23_design.json` (verified: real example JSON, `AMP_aptamer`/`FMN_aptamer`/`multipolymer` entries)
- `tools/foundry/models/rfd3na/configs/inference_engine/{base,rfdiffusion3na,dev}.yaml` (verified: default config values, `bp_partners` cfg feature)
- `tools/foundry/models/rfd3na/src/rfd3na/model/layers/attention.py` (verified: identical cuequivariance try/except pattern as RFD3)
- `tools/foundry/src/foundry/inference_engines/checkpoint_registry.py` (verified: `rfd3na` checkpoint entry)
- `tools/foundry/src/foundry/utils/xpu/` (verified: shared XPU support code, same as RFD3 brief)
- Repo-wide grep for `hip`/`rocm`/`amd` across `tools/foundry` (verified: zero hits)
