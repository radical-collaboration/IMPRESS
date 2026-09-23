# Boltz Toolkit

## Purpose
Protein+ligand co-folding confirmation via Boltz-2 (`boltz predict`), a pip package with
its own model-weight cache - no container required. `boltz_predict` is the final stage of
the `small_molecule_binding` canonical sequence: an independent structure-prediction check
on the sequence that survived RFD3 backbone generation, LigandMPNN design and PyRosetta
refinement. Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`boltz()` step (kept the name `boltz` in the old code "for compatibility" with an earlier
AF2 step it replaced - there is no AF2 tool in this toolkit).

## Canonical sequences
Final stage of the wider chain (see `toolkits/rfd3/SKILL.md` for why this spans four
toolkits rather than one):

    rfd3_design -> ligandmpnn_design -> packmin -> fastrelax -> filter_shape -> boltz_predict

`boltz_predict` takes the `filter_shape`-passed `Complex` structure, extracts its sequence
and ligand context, and re-predicts the complex from sequence alone - agreement between
this independent prediction and the physics-refined structure is the campaign's strongest
signal that a design is real, not an artifact of the Rosetta scoring function.

## Cost posture
GPU-bound but a single forward pass per `diffusion_samples` value - cheaper than
`rfd3_design`'s iterative sampling. `use_msa_server` adds network latency (P5-flavored
egress dependency even though this tool is declared P1); a login-node-unreachable MSA
server degrades to single-sequence mode rather than failing outright in the old pipeline,
and this agent inherits that same fallback behavior.

## Pitfalls
- Requires `$BOLTZ_CACHE` pre-warmed (a first `boltz predict` call auto-downloads model
  weights - there is no separate "download weights" subcommand); `scripts/delta_env_setup.sh`
  warms this on the login node so compute nodes, which lack internet access, find weights
  already present.
- `complex_plddt`/`ligand_iptm` gate thresholds (`min: 0.5`/`min: 0.4`) are conservative
  starting points, not calibrated against this project's own designs yet.
- Boltz-2 predicts independently of the Rosetta-refined coordinates it was handed; a low
  score here after `filter_shape` passed is a genuine disagreement worth investigating, not
  necessarily a Boltz-2 failure.
- `--no_kernels` is required, not optional, with the currently-pinned dependency
  versions: `cuequivariance_ops_torch`'s fused kernel needs
  `cublasGemmGroupedBatchedEx`, absent from the `nvidia-cublas-cu12` version
  `torch==2.5.1+cu121` pins and loads first (present only from `12.5.3.2+`) - the kernel
  import fails every time until that's reconciled (verified, reproduced with no GPU
  present, in old IMPRESS's `scripts/boltz.sh`). Don't drop this flag on a dependency
  bump without re-checking the installed torch/cuequivariance-ops-cu12 versions.
- `ligand_smiles` is a plain string, no atom-name mapping needed for it to reach Boltz
  correctly - the atom-mapping machinery this project's history mentions is about
  feeding a Boltz *output* back into RFD3's guided/partial-diffusion *input*, not about
  Boltz consuming a SMILES string.
