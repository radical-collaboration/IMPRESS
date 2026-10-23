# RFdiffusion3 (RFD3)

**One-line identity.** An all-atom diffusion model for de novo design of protein structure under arbitrary motif, hotspot, ligand, symmetry, and partial-diffusion constraints, shipped as one of foundry's four released models.

## Identity
- **Version / release examined:** `tools/foundry/pyproject.toml` — package `rc-foundry`, dynamic version via `hatch-vcs`; RFD3 is built as `models/rfd3/src/rfd3` and packaged with `[project.scripts] rfd3 = "rfd3.cli:app"`. Checkpoint registered as `rfd3_foundry_2025_12_01_remapped.ckpt` in `src/foundry/inference_engines/checkpoint_registry.py`.
- **Provenance:** RosettaCommons / Institute for Protein Design (Baker lab). BSD license (`tools/foundry/LICENSE.md`). Refcode: `tools/foundry/models/rfd3/`. Preprint: Butcher, Krishna, et al., "De novo Design of All-atom Biomolecular Interactions with RFdiffusion3," bioRxiv 2025.09.18.676967.
- **Maturity:** active research / early-production. Public weights + training code released together (Sept 2025); README explicitly documents an extensive, still-evolving `docs/input.md` spec and open GitHub issues referenced inline (e.g., issue #154 on `allow_realignment`).

## Scientific role
Generative structure design: the **generate** stage of the pipeline. Directly serves **de novo binder design** (protein-protein interfaces via hotspot conditioning), **enzyme/catalytic design** (active-site motif scaffolding, hydrogen-bond-donor/acceptor conditioning via optional HBPLUS integration), and **small-molecule binding** (ligand-conditioned pocket design). It is also usable for **stability/thermostabilization** indirectly via partial diffusion / redesign of an existing backbone (`partial_t` noise + refold), though that is not its primary trained objective. RFD3 is trained multi-task (per README): sequence-fixed/structure-free "prediction-type" tasks, MPNN-style inverse folding (fix backbone, diffuse sequence), and PLACER/ChemNet-style side-chain-only diffusion — so the same checkpoint covers several pipeline stages depending on which atoms/fields are fixed in the input spec.

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, via the `rfd3` entrypoint (`[project.scripts] rfd3 = "rfd3.cli:app"`, `tools/foundry/pyproject.toml`). `models/rfd3/src/rfd3/cli.py` is a thin Typer wrapper: it takes free-form `key=value` tokens, appends `inference_engine=rfdiffusion3` if not given, and calls Hydra's `compose(config_name="inference", overrides=args)` before invoking `rfd3.run_inference.run_inference(cfg)`. So every CLI flag is a dotted Hydra override path (e.g. `inference_sampler.num_timesteps=100`).
- **Real argv, from `models/rfd3/README.md`:**
  ```bash
  rfd3 design out_dir=logs/inference_outs/demo/0 inputs=models/rfd3/docs/examples/demo.json \
    skip_existing=False dump_trajectories=True prevalidate_inputs=True
  ```
  A minimal debug invocation from `models/rfd3/docs/input.md`:
  ```bash
  rfd3 design inputs=null specification.length=200
  ```
- **Inputs:** a JSON/YAML "InputSpecification" file (`inputs=`) — one or more named design configs, each with fields like `input` (PDB/CIF path), `contig` (motif/length mini-language, e.g. `"A1-80,10,/0,B5-12"`), `length`, `ligand` (CCD codes), `select_hotspots`, `select_fixed_atoms`, `partial_t`, `symmetry`. Full field table in `models/rfd3/docs/input.md`.
- **Outputs:** designed structures (PDB/CIF) plus a per-design JSON metadata sidecar (`dump_prediction_metadata_json`, `output_full_json`) written under `out_dir`; optional trajectory dumps (`dump_trajectories`).
- **A concrete example**, taken verbatim from `tools/foundry/models/rfd3/docs/examples/demo.json`:
  ```json
  "partial_diffusion": {
      "input": "../input_pdbs/7v11.pdb",
      "ligand": "OQO",
      "partial_t": 15.0,
      "contig": "A431",
      "unindex": "A572-573",
      "select_fixed_atoms": {"A431": "TIP", "A572": "BKBN", "A573": "BKBN"},
      "allow_ligand_on_existing_chain": true
  }
  ```

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job). A single `rfd3 design` invocation loads one checkpoint into one or more local GPUs and runs a diffusion rollout per design; it never leaves the allocation and is not MPI-coupled (Lightning Fabric `devices_per_node`/`num_nodes` exist for *training*, not for a single inference call).
- **GPU vendor portability:** **CUDA+SYCL-XPU, proven; HIP unproven.** Evidence:
  - CUDA: default path, `torch.cuda.is_available()` in `src/foundry/utils/ddp.py::set_accelerator_based_on_availability`.
  - Intel XPU: explicitly documented and code-supported. Top-level README (`tools/foundry/README.md`): *"For Intel XPU devices, install PyTorch with XPU support first... `pip install torch --index-url https://download.pytorch.org/whl/xpu`"*. Custom Lightning Fabric plugins exist at `tools/foundry/src/foundry/utils/xpu/{xpu_accelerator.py,single_xpu_strategy.py,xpu_precision.py}` (a `XPUAccelerator`, `SingleXPUStrategy`, `XPUMixedPrecision` with `torch.autocast(device_type="xpu", ...)`), and the same `set_accelerator_based_on_availability` ladder auto-selects `"xpu"` when `torch.xpu.is_available()`.
  - AMD/HIP: **no evidence found anywhere in the refcode** — no `hip`/`rocm`/`amd` string in the entire `tools/foundry` tree (grep across `.py/.md/.toml/.yaml`), no CI job, no community report surfaced in web search. RFD3's optional accelerated attention path (`models/rfd3/src/rfd3/model/layers/attention.py`) imports `cuequivariance_torch` inside a `try/except`, and gracefully falls back to a plain PyTorch attention implementation when unavailable — so RFD3 (unlike RF3, which hard-imports cuequivariance) has **no hard CUDA-only kernel dependency**, which is the main structural reason HIP is *plausible*. But ROCm-built PyTorch presents itself through the `torch.cuda` namespace, so the existing device ladder would likely mis-route to a "cuda" accelerator on Frontier without any HIP-specific code ever having been exercised. **Treat Frontier support as unproven, not "should work."**
- **State model:** checkpointable at design granularity — `skip_existing=True` (CLI default per `models/rfd3/configs/inference_engine/rfdiffusion3.yaml`) detects and skips output files that already exist, so a killed job resumes cheaply by re-running the same command.
- **Data locality:** self-contained per invocation (one input JSON + optional input PDB/CIF + ligand); output directory should be on shared/visible FS if downstream steps (MPNN, RF3 refold) run on other nodes.
- **Staging burden:** model weights, ~3 GB checkpoint (`rfd3_foundry_2025_12_01_remapped.ckpt`, downloaded via `foundry install rfd3` from `files.ipd.uw.edu`). Must be pre-staged to `~/.foundry/checkpoints` or `$FOUNDRY_CHECKPOINT_DIRS` before the agent's first iteration — full HTTPS egress exists on target compute nodes so this *could* happen inline, but a ~3 GB pull on first call wastes allocation time and should be a setup-phase step instead.
- **Container availability:** official — `rosettacommons/foundry` on Docker Hub, `latest` tag ships weights baked in (~18 GB per Docker Hub listing), `slim` tag omits them. The image and its documented Apptainer usage assume NVIDIA (`apptainer run --nv ...`); there is no published XPU or ROCm variant, so Aurora/Frontier deployment is build-required, not off-the-shelf.

## Deployment on DOE & ACCESS
- **Polaris (A100/CUDA) and ACCESS Delta/Bridges-2/Expanse (CUDA):** straightforward — official container via Apptainer with `--nv`, or `pip install "rc-foundry[rfd3]"` in a conda/venv environment. No license gates; checkpoint pulled once from `files.ipd.uw.edu` over HTTPS.
- **Aurora (Intel PVC/SYCL-XPU):** real, code-backed support path exists, but must be **built from source/pip, not the official container** (no XPU Docker image published). Install order matters: `pip install torch --index-url https://download.pytorch.org/whl/xpu` **then** `pip install "rc-foundry[all]"`, and README specifically warns to use `pip` not `uv` for this step (`uv` re-resolves and can silently replace the XPU torch build with a standard PyPI wheel). Module-based or Apptainer-with-custom-XPU-base deployment, not `--nv`.
- **Frontier (AMD MI250X/HIP):** **not proven to run.** No HIP/ROCm code path, no CI coverage, no vendor documentation, no community report found. If pursued, would require a from-scratch build against a ROCm PyTorch wheel and empirical verification that the plain-PyTorch attention fallback (used automatically when `cuequivariance_torch` import fails) and every other op in the network (einsum via `opt_einsum`, jaxtyping-checked tensor ops) execute correctly under ROCm. Budget this as an R&D spike, not a deployment task.

## Agentic surface
- **Native MCP:** no. Grepped `tools/foundry` for `mcp`/`model context protocol`/`modelcontextprotocol` (all file types) — zero hits outside this project's own brief template. No MCP server, module, or upstream doc exists for foundry or RFD3.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `contig` / `length` | `InputSelection` str / `"min-max"` | task-defined, e.g. `"50-200"` | required | Defines the design space itself; widening range trades specificity for diversity; runtime scales O(N²) in residue count |
| `diffusion_batch_size` | int | 1–~32 (GPU-memory bound) | 8 | Designs per batch vs. peak GPU memory |
| `n_batches` | int | 1–many | 1 | Total designs = `diffusion_batch_size × n_batches`; linear cost |
| `inference_sampler.num_timesteps` | int | ~50–200 | 200 | Denoising steps; fewer = faster, may reduce quality |
| `inference_sampler.step_scale` | float | 1.0–1.5 | 1.5 | Higher → less diverse, more designable |
| `inference_sampler.noise_scale` | float | ~0.5–1.5 (no hard-documented bound) | 1.003 | Lower → less diversity |
| `inference_sampler.gamma_0` | float | 0.0 (ODE) – 1.0 | 0.6 | Lower → more designable, less diverse |
| `inference_sampler.use_classifier_free_guidance` + `cfg_scale` | bool + float | scale 1.0–3.0 | `False` / 1.5 | Steers toward a feature condition (e.g. buried donor/acceptor) at cost of diversity |
| `partial_t` | float | 5.0–15.0 (doc-recommended) | n/a (unset = full diffusion) | Amount of noise added for partial diffusion; controls how much of the input structure is preserved vs. redesigned |
| `low_memory_mode` | bool | — | `False` | Trades runtime for reduced peak GPU memory on large systems |
| `select_hotspots` / `select_fixed_atoms` | `InputSelection` | task-defined | none | Defines binder/motif targeting; central autonomous-search lever for PPI and enzyme tasks |

- **Parameters that must NOT be agent-varied:**
  - `read_sequence_from_sequence_head` — training-derived setting; docs state plainly "it is not recommended to change this setting."
  - `dialect` — switches between new (2) and legacy (1) input-parsing semantics; changes how every other field is interpreted, so varying it silently changes correctness rather than tuning quality.
  - `allow_realignment` — per upstream GitHub issue #154 (quoted in `docs/input.md`), leaving this `False` avoids "weird interactions with motif scaffolding"; not a quality knob.
  - `ckpt_path` — model identity; should be pinned by deployment config, not varied per design call.
  - `cleanup_guideposts` / `cleanup_virtual_atoms` — debug-only toggles; disabling changes output atom counts/structure in ways downstream parsers may not expect.

## Failure modes & what the agent must check
- **Loud failure:** missing/unfound checkpoint (assertion in `foundry/inference_engines/base.py::BaseInferenceEngine.__init__`), malformed contig/InputSelection strings (caught by `prevalidate_inputs=True`, recommended to always set this), CUDA/XPU OOM on large systems (O(N²) memory growth — mitigate with `low_memory_mode=True` or smaller `diffusion_batch_size`).
- **Silent bad output:** (1) over-aggressive `gamma_0`/`step_scale`/too-few `num_timesteps` can converge to a structure with little or no secondary structure — check with a post-hoc secondary-structure fraction or a self-consistency refold (RF3/AF-family) and pLDDT/designability filter, not by inspecting the diffusion log. (2) `partial_t` set too low silently returns a near-copy of the input rather than a meaningfully redesigned structure — check backbone RMSD to input. (3) Hotspot/motif conditioning can be geometrically satisfied but chemically nonsensical (e.g., a "binder" that doesn't actually contact the hotspot residues) — check interface contact/distance post-hoc, don't trust that hotspot conditioning succeeded just because the run exited cleanly.

## Cost per unit of work
One design (`diffusion_batch_size=8`, `n_batches=1`, `num_timesteps=200`) on a ~150–250-residue system: seconds to low minutes per design on a single modern NVIDIA GPU (README/tutorial: "reduce runtime from minutes to seconds per design" on GPU vs. "tens of minutes per example" on CPU); scales O(N²) with residue count (documented scaling claim, tutorial docs). Resource shape: 1 GPU, single node, no MPI. Checkpointable via `skip_existing=True` at the individual-design-file granularity. Assumption: numbers are from upstream tutorial prose, not independently benchmarked here — treat as order-of-magnitude only.

## Verdict
**Core.** RFD3 is the flagship all-atom generative engine underpinning three of the four in-scope problem classes directly (binder design, enzyme/catalytic motif design, small-molecule/ligand-conditioned pocket design) and is usable for the fourth (stabilization) via partial diffusion. Its I/O contract, Hydra-override CLI, and parameter surface are unusually well-documented for an autonomous agent to drive safely, and its graceful cuEquivariance fallback makes portability outside CUDA more plausible than for RF3. The chief open risk is Frontier: no evidence supports HIP execution today, so any Frontier deployment plan must budget for a genuine verification spike, not assume portability from the Aurora precedent.

## Sources
- `tools/foundry/pyproject.toml` (verified: `[project.scripts]`, `rfd3` extra, `rf3` extra with `cuequivariance_ops_cu12`)
- `tools/foundry/models/rfd3/README.md` (verified: install/run commands, examples table)
- `tools/foundry/models/rfd3/docs/input.md` (verified: CLI arguments, InputSpecification fields, all `inference_sampler.*` defaults)
- `tools/foundry/models/rfd3/docs/examples/demo.json` (verified: real example JSON)
- `tools/foundry/models/rfd3/configs/inference_engine/{base,rfdiffusion3,dev}.yaml` (verified: default config values)
- `tools/foundry/models/rfd3/src/rfd3/cli.py` (verified: Hydra-override CLI mechanism)
- `tools/foundry/models/rfd3/src/rfd3/model/layers/attention.py` (verified: try/except cuequivariance fallback)
- `tools/foundry/src/foundry/utils/xpu/{__init__.py,xpu_accelerator.py,single_xpu_strategy.py,xpu_precision.py}` (verified: Intel XPU support code)
- `tools/foundry/src/foundry/utils/ddp.py` (verified: `set_accelerator_based_on_availability` device ladder)
- `tools/foundry/src/foundry/inference_engines/checkpoint_registry.py`, `src/foundry/inference_engines/base.py` (verified: checkpoint registry/resolution)
- `tools/foundry/README.md` (verified: XPU install instructions, Docker image pointer)
- Butcher et al., "De novo Design of All-atom Biomolecular Interactions with RFdiffusion3," bioRxiv 2025.09.18.676967 (upstream paper; not independently re-verified beyond citation block in README)
- Docker Hub `rosettacommons/foundry` listing (fetched via WebFetch: image size ~18 GB with weights, `slim` tag, `--nv` Apptainer usage, no ARM support; GPU-vendor scope not explicitly stated on the page — inferred CUDA-only from `--nv` and absence of any ROCm/XPU mention)
- Installation tutorial `https://rosettacommons.github.io/foundry/models/rfd3/tutorials/RFdiffusion3_installation_tutorial.html` (fetched via WebFetch: hardware requirements, ~3 GB checkpoint, ~3 GB GPU memory recommendation, O(N²) scaling claim — **inferred/upstream-stated, not independently benchmarked**)
