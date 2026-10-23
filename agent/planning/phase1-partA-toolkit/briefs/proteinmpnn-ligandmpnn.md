# ProteinMPNN / LigandMPNN / SolubleMPNN (foundry `mpnn`)

**One-line identity.** A single re-implemented inverse-folding model family (ProteinMPNN, LigandMPNN, SolubleMPNN) that designs amino-acid sequences for a fixed backbone, optionally conditioned on ligands/DNA/RNA/ion context, sharing one foundry codebase and CLI.

## Identity
- **Version / release examined:** `tools/foundry/pyproject.toml` — packaged as `models/mpnn/src/mpnn`, `[project.scripts] mpnn = "mpnn.inference:main"`. Checkpoints registered in `src/foundry/inference_engines/checkpoint_registry.py`: `proteinmpnn` (`proteinmpnn_v_48_020.pt`), `ligandmpnn` (`ligandmpnn_v_32_010_25.pt`), `solublempnn` (`solublempnn_v_48_020.pt`), each hosted at `files.ipd.uw.edu/pub/ligandmpnn/`.
- **Provenance:** RosettaCommons / Institute for Protein Design, re-implementing the original Dauparas et al. models within the atomworks/foundry framework. BSD license. Refcode: `tools/foundry/models/mpnn/`. Original models: ProteinMPNN (Dauparas et al., *Science* 2022, doi 10.1126/science.add2187), LigandMPNN (Dauparas et al., *Nature Methods* 2025, doi 10.1038/s41592-025-02626-1), SolubleMPNN (*Nature* 2024, doi 10.1038/s41586-024-07601-y).
- **Maturity:** active research, explicitly **not yet validated for benchmarking**. `models/mpnn/README.md` carries two prominent warnings: *"Please use the old repositories... for model benchmarking/comparison until the API and public weights stabilize"* and a known bug where CLI passing of user annotations (temperature, designed residues) works but loading the same annotations from CIF/atom-array metadata does not.

## Scientific role
Inverse folding / sequence design — the **inverse-fold** stage, almost always run immediately downstream of a structure-generation step (RFD3, RFD3NA, or a native/experimental backbone). Serves all four in-scope problem classes indirectly: any generated backbone (binder, enzyme scaffold, small-molecule pocket, or stabilized fold) needs a sequence assigned before it can be scored or synthesized. LigandMPNN specifically is the variant that conditions on ligand/DNA/RNA/ion context, making it the natural pairing for RFD3's small-molecule and enzyme-design outputs; SolubleMPNN biases toward soluble sequences (useful as a stability-adjacent filter).

## Invocation & I/O contract
- **How a unit of work is invoked:** CLI, via the `mpnn` entrypoint (`[project.scripts] mpnn = "mpnn.inference:main"`). `models/mpnn/src/mpnn/inference.py::main()` parses CLI flags (`build_arg_parser()`), converts them to a JSON config (`cli_to_json()`), constructs an `MPNNInferenceEngine`, and calls `engine.run(input_dicts=config["inputs"], atom_arrays=None)`. Programmatic use is `from mpnn.inference_engines.mpnn import MPNNInferenceEngine`.
- **Real argv shape**, reconstructed from the argparse definitions in `models/mpnn/src/mpnn/utils/inference.py` (`build_arg_parser`) — every flag below is a verified CLI argument, not invented:
  ```bash
  mpnn --structure_path input.pdb --model_type ligand_mpnn \
    --checkpoint_path ~/.foundry/checkpoints/ligandmpnn_v_32_010_25.pt \
    --is_legacy_weights True --out_directory out/ \
    --temperature 0.2 --batch_size 8 --number_of_batches 4 \
    --fixed_residues "A35,B40,C52" --bias '{"ALA": -1.0, "GLY": 0.5}' \
    --omit '["ALA","GLY","UNK"]'
  ```
  A pre-built JSON config can also be supplied directly: `mpnn --config_json path/to/config.json` (other CLI flags are then parsed but ignored, per `--config_json`'s help text).
- **Inputs:** a structure file (`--structure_path`, PDB or CIF) or a JSON of per-input dicts; design-scope selectors (`--fixed_residues`/`--designed_residues`/`--fixed_chains`/`--designed_chains`, mutually exclusive); bias/omission dicts (global or per-residue); symmetry groups (`--symmetry_residues` or `--homo_oligomer_chains`, mutually exclusive).
- **Outputs:** FASTA (`--write_fasta`, default `True`) and/or designed CIF structures (`--write_structures`, default `True`) under `--out_directory`.
- **A concrete example** (weight-selection convention), from `models/mpnn/README.md`:
  ```bash
  wget https://files.ipd.uw.edu/pub/ligandmpnn/ligandmpnn_v_32_010_25.pt
  ```
  with the documented pairing `model_type: "ligand_mpnn"`, `is_legacy_weights: True` for original-repo weights. (README notes CLI/JSON-based inference docs are still "coming soon," so the worked end-to-end example lives in `examples/all.ipynb` rather than a finished markdown walkthrough.)

## Compute pattern
- **Pattern:** P1 (GPU-node-local, in-job) as the dominant/typical deployment. MPNN is lightweight enough to run meaningfully on CPU too (the original LigandMPNN paper reports ~250× speedup over Rosetta-based CPU design/packing, implying CPU-viable throughput), but per the taxonomy's classification rule ("classify by dominant cost, not by capability") and foundry's own device-priority ladder defaulting to GPU when present, P1 is the correct primary classification.
- **GPU vendor portability:** **CUDA+SYCL-XPU, proven; HIP unproven — and the most plausible HIP candidate of the three foundry models.** `models/mpnn/src/mpnn/inference_engines/mpnn.py` (`MPNNInferenceEngine.__init__`) has its own explicit device ladder: `torch.cuda.is_available()` → `torch.xpu.is_available()` → `torch.backends.mps.is_available()` → `cpu`. Grep confirms **zero references to `cuequivariance` anywhere under `models/mpnn/`** — MPNN has no optional accelerated-kernel dependency at all (unlike RFD3/RFD3NA's try/except cuEquivariance path, and unlike RF3's hard dependency). This means MPNN's compute graph is pure PyTorch ops throughout, which is the best structural precondition for HIP portability of any model in this cluster — but it remains **unverified**: no HIP/ROCm string appears anywhere in `tools/foundry`, and no CI or community report was found confirming an actual run on AMD hardware.
- **State model:** stateless per invocation — each CLI call loads the checkpoint, designs `batch_size × number_of_batches` sequences, and exits; no resumability mechanism analogous to RFD3's `skip_existing` was found in `mpnn/inference.py` or `utils/inference.py`.
- **Data locality:** self-contained per invocation (one structure file in, FASTA/CIF out).
- **Staging burden:** model weights, small — ProteinMPNN/LigandMPNN/SolubleMPNN checkpoints are tens of MB each (classic MPNN weight files, not the multi-GB diffusion checkpoints); negligible staging cost relative to RFD3/RFD3NA.
- **Container availability:** official — same `rosettacommons/foundry` image and `foundry install base-models` target as RFD3 (installs `proteinmpnn` + `ligandmpnn` by default; `solublempnn` needs an explicit `foundry install solublempnn`).

## Deployment on DOE & ACCESS
- **Polaris / ACCESS (CUDA):** straightforward, official container or `pip install "rc-foundry[mpnn]"`.
- **Aurora (Intel XPU):** same documented, code-backed path as RFD3 — `pip install torch --index-url .../whl/xpu` then `pip install "rc-foundry[all]"` via `pip` not `uv`. MPNN's own device ladder (above) picks up XPU automatically once torch reports it available.
- **Frontier (AMD MI250X/HIP):** not proven, but MPNN is the best-positioned of the three models to eventually work here given the total absence of custom CUDA kernels — if the project wants to spend a verification spike on any one foundry model for Frontier, MPNN is the cheapest one to try (small weights, no cuEquivariance entanglement, pure PyTorch).
- Given the low compute cost per design (see below), MPNN is also realistic to run **CPU-only** as a stopgap on any platform where GPU portability is blocked, at a real but bounded throughput penalty.

## Agentic surface
- **Native MCP:** no. Same repo-wide grep as the other foundry briefs — zero `mcp`/`model context protocol` references in `tools/foundry`.
- **Parameters worth exposing for autonomous variation:**

| Parameter | Type | Sane range | Default | Trade-off |
|---|---|---|---|---|
| `temperature` | float | 0.05–0.5 typical (no hard-coded bound in argparse) | 0.1 | Higher → more sequence diversity, lower average confidence/recovery |
| `temperature_per_residue` | dict | per-residue overrides of above | none | Fine-grained diversity control, e.g. more exploration at an interface, less at a catalytic residue |
| `number_of_batches` × `batch_size` | int × int | 1–many × 1–~64 (GPU-memory bound) | 1 × 1 | Total sequences designed = product; linear cost |
| `fixed_residues` / `designed_residues` / `fixed_chains` / `designed_chains` | str (mutually exclusive group) | task-defined | none (design everything) | Defines design scope; central autonomous-search lever |
| `bias` / `bias_per_residue` | dict | amino-acid → logit bias, roughly -3 to +3 | none | Steers composition (e.g. down-weight Cys); per-residue overrides global |
| `omit` / `omit_per_residue` | list / dict | AA codes | `["UNK"]` | Hard-excludes residue types from sampling |
| `pair_bias` / `pair_bias_per_residue_pair` | dict | AA-pair → logit bias | none | Encodes co-design preferences between neighboring positions |
| `structure_noise` | float | 0.0–0.3 Å typical (matches training noise levels used for the weight variants, e.g. `_020`, `_002`, `_010`, `_030`) | 0.0 | Regularizes against backbone-coordinate overfitting; should roughly match the noise level baked into the chosen checkpoint variant |
| `symmetry_residues` / `homo_oligomer_chains` | list (mutually exclusive) | task-defined | none | Enforces symmetric sequence assignment across chains/positions |
| `model_type` | str, `choices=["protein_mpnn","ligand_mpnn"]` | — | required | Chooses whether ligand/NA context is used; not really a "tuning" knob but the primary mode switch |

- **Parameters that must NOT be agent-varied:**
  - `is_legacy_weights` — this must match the checkpoint being loaded (README: *"when using weights from the original ProteinMPNN/LigandMPNN/SolubleMPNN repositories, please ensure to set `is_legacy_weights` to `True`"*); mismatching it against the actual checkpoint is a correctness bug, not a design choice.
  - `decode_type` / `causality_pattern` — training/inference-mode internals (`auto_regressive` is documented as "the default for inference"); switching to `teacher_forcing` or `unconditional` changes what the model is doing, not how well it does it, and would silently produce meaningless design output if used for inference sampling.
  - `checkpoint_path` / `model_type` pairing — must stay consistent (e.g. don't point `model_type=protein_mpnn` at a `ligand_mpnn` checkpoint); no validation beyond what `_validate_model_config` checks was confirmed to catch every mismatch.

## Failure modes & what the agent must check
- **Loud failure:** unknown/missing checkpoint path, invalid mutually-exclusive CLI combination (e.g. both `--fixed_residues` and `--designed_chains`) rejected by argparse's `add_mutually_exclusive_group`, malformed JSON in `--bias`/`--omit`/`--pair_bias` string args.
- **Silent bad output:** (1) the known CIF/atom-array annotation-loading bug (README-documented) means user settings like temperature or designed-residue selection can silently fail to apply when supplied via structure-file annotations rather than CLI/JSON — **always pass sampling parameters via CLI/JSON, not via CIF annotations**, per the README's own workaround guidance. (2) `is_legacy_weights` mismatch against the actual checkpoint format will not necessarily error, but will silently degrade sequence quality — verify checkpoint filename matches the expected legacy/re-trained convention before trusting output. (3) As with any inverse-folding output, low sequence-recovery or implausible amino-acid composition (e.g. Cys/Trp overrepresentation) should be checked post-hoc against expected composition statistics — the model is capable of producing chemically well-formed but poor-quality sequences without any error signal.

## Cost per unit of work
Order-of-magnitude only (no in-repo benchmark found; original-model published figures apply approximately to the re-implementation): roughly 1–2 seconds per 100 residues per sequence on GPU (web-search-sourced estimate for the original ProteinMPNN), and reported ~250× faster than Rosetta-based CPU sequence design/packing for the LigandMPNN paper's comparison. A `batch_size=8, number_of_batches=1` call (8 sequences for one backbone) should complete in low single-digit seconds on any of the target GPUs. Resource shape: 1 GPU (or CPU, viable at reduced but still usable throughput), single node, stateless (no checkpointing needed given the short per-call runtime).

## Verdict
**Core.** MPNN is the load-bearing inverse-folding step for every backbone-generation output in this toolkit — RFD3/RFD3NA produce structures, but every downstream scoring/filtering/synthesis step needs a sequence, and MPNN (specifically LigandMPNN for the small-molecule/enzyme problem classes) is that step. Its API-instability warnings are real and should be tracked, but they concern benchmarking parity with the original repos, not basic functional correctness — the CLI, JSON config path, and parameter surface are concrete and well-specified enough for an autonomous agent to drive today. Its lack of any custom CUDA kernel also makes it the single best foundry model to prioritize for a genuine Frontier/HIP portability test, since a positive result there would be the first real evidence point for AMD viability across the whole cluster.

## Sources
- `tools/foundry/pyproject.toml` (verified: `[project.scripts] mpnn = "mpnn.inference:main"`)
- `tools/foundry/models/mpnn/README.md` (verified: benchmarking warning, weight/model_type/is_legacy_weights pairing table, checkpoint URLs, known CIF-annotation bug)
- `tools/foundry/models/mpnn/src/mpnn/inference.py` (verified: CLI entrypoint wiring, `MPNNInferenceEngine` construction)
- `tools/foundry/models/mpnn/src/mpnn/utils/inference.py` (verified: full `build_arg_parser()` argument list, `MPNN_GLOBAL_INFERENCE_DEFAULTS`, `MPNN_PER_INPUT_INFERENCE_DEFAULTS`)
- `tools/foundry/models/mpnn/src/mpnn/inference_engines/mpnn.py` (verified: device-selection ladder including XPU, `_validate_model_config`)
- `tools/foundry/src/foundry/inference_engines/checkpoint_registry.py` (verified: `proteinmpnn`/`ligandmpnn`/`solublempnn` registry entries)
- Repo-wide grep for `cuequivariance` under `models/mpnn/` (verified: zero hits) and for `hip`/`rocm`/`amd` under `tools/foundry` (verified: zero hits)
- Dauparas et al., *Science* 2022 (10.1126/science.add2187); Dauparas et al., *Nature Methods* 2025 (10.1038/s41592-025-02626-1) — cited in README, not independently re-verified
- Web search for runtime figures (ProteinMPNN ~1–2 s/100 residues on GPU; LigandMPNN ~250× faster than Rosetta on CPU) — **inferred from secondary sources, not independently benchmarked in this brief**
