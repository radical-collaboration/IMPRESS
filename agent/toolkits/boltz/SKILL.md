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
`rfd3_design`'s iterative sampling. `use_msa_server` is a P5-flavored egress dependency in
a tool declared P1, which is why it now **defaults to `false`**: it emits `msa: auto` and
passes `--use_msa_server`, and a compute node with no outbound network does not degrade
gracefully - it stalls until `walltime_s` kills the task. The claim previously made here,
that an unreachable MSA server falls back to single-sequence mode, was never verified and
should not be relied on. The original IMPRESS pipeline hardcodes `msa: empty` and offers no
flag at all. Turn it on only where the allocation is known to have egress.

### The affinity head
`boltz_predict` can also return Boltz-2's **affinity** prediction, off by default
(`predict_affinity`). Its weights (`boltz2_aff.ckpt`, 2.0 GB) are fetched by `boltz`'s own
cache warm-up whether or not anything asks for them, so the capability has always been present
and paid for; until episode J13 nothing requested it, and no archive of this project holds a
single affinity value. **Enabling it recovers nothing retrospectively** - the affinity pass
re-samples the complex the structure pass has just predicted, so it cannot be run over a
finished archive. Asking for it is a second model load and a second sampling pass, which is
why it is a parameter and not the default.

Two numbers come back. They are trained on different datasets with different supervisions and
they answer different questions:

| Metric | What it is | What it is for |
|---|---|---|
| `affinity_pred_value` | `log10(IC50)` with the IC50 in **micromolar**; smaller is tighter. **Not kcal/mol, not a ΔG.** | comparing modifications of a known binder (hit-to-lead) |
| `affinity_probability_binary` | P(binder), 0-1, dimensionless | separating binders from decoys (hit discovery) |

Both are declared in `metrics:` and deliberately **absent from the `metrics_reported`
integrity gate**: they exist only when the parameter is set, and a gate demanding them
unconditionally would fail every ordinary run. The unit is recorded in the spec's
`metric_units:` and travels into every `tasks` provenance line beside the value, because a
conversion nobody wrote down is how a residual gets fitted in one space and served in another.

Upstream supports **one** affinity ligand, single-residue, and refuses above 128 heavy atoms
with an accuracy warning above 56 (its training maximum). ALR's 30 is comfortably inside both.

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
- With `predict_affinity` on, Boltz scores affinity on **its own rank 0** - the best
  `confidence_score` - while this adapter carries forward the best `complex_plddt`. Those are
  different numbers, so with `diffusion_samples > 1` the affinity can describe a different
  co-fold than the pLDDT reported beside it. The adapter says which happened, in
  `affinity_on_reported_sample` (1 or 0); it does not silently re-rank, because that would
  change which design every existing campaign carries forward.
- `ligand_smiles` is a plain string, no atom-name mapping needed for it to reach Boltz
  correctly - the atom-mapping machinery this project's history mentions is about
  feeding a Boltz *output* back into RFD3's guided/partial-diffusion *input*, not about
  Boltz consuming a SMILES string.
