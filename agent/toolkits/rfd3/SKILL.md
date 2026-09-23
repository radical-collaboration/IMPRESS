# RFD3 Toolkit

## Purpose
Backbone generation via RFdiffusion3 (RFD3), run inside the `foundry` Apptainer/Singularity
container on a GPU the campaign already holds. `rfd3_design` is the first stage of the
`small_molecule_binding` canonical sequence: it proposes candidate binder backbones around
a target ligand before any sequence is designed. Adapted from
`IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s `rfd3()` step.

## Canonical sequences
`rfd3_design` is stage 1 of the wider small-molecule-binding chain, which spans four
toolkits (see the toolkit-per-dependency layout note below):

    rfd3_design -> ligandmpnn_design -> packmin -> fastrelax -> filter_shape -> boltz_predict

`rfd3_design` alone: proposes `num_designs` candidate backbones for the given contig/ligand
spec. Nothing downstream can run without at least one passing backbone.

This toolkit is deliberately split from `ligandmpnn`/`rosetta`/`boltz` even though they
form one pipeline: `Registry.load()` is all-or-nothing per toolkit directory, so an RFD3
container problem must not also take down LigandMPNN, PyRosetta or Boltz-2.

## Cost posture
`rfd3_design` is the most GPU-time-expensive stage per design (container cold start plus
diffusion sampling). Raise `num_designs` only when downstream QC is passing consistently -
a batch of backbones that all fail `has_secondary_structure` wastes the GPU-hours of every
later stage that would have consumed them.

## Pitfalls
- `has_secondary_structure` here is evaluated from phi/psi Ramachandran regions
  (`impress_a.tools._pdbtools.secondary_structure_fraction`), **not** DSSP/STRIDE - it is
  an approximation chosen so this toolkit loads and validates without the `mkdssp` binary.
  Treat a borderline pass/fail near the threshold with suspicion; re-check with real DSSP
  before trusting it for a paper-quality result.
- `rfd3_design` requires `$FOUNDRY_SIF_PATH` to point at an extracted or built foundry
  sandbox (see `scripts/delta_env_setup.sh` / `pull_foundry.sh` in the original IMPRESS
  examples) - it is not installed by `pip install -e ".[dev]"`.
- The real `rfd3` CLI (verified against the installed `rfd3.cli:design`) is a Typer app
  with `allow_extra_args=True, ignore_unknown_options=True` that forwards every arg as a
  Hydra config override - `key=value`, never `--flag`. `--config`/`--out` are not real
  flags and would fail Hydra's override parsing immediately; the real invocation is
  `rfd3 design out_dir=... inputs=... skip_existing=False dump_trajectories=True
  prevalidate_inputs=True diffusion_batch_size=... inference_sampler.num_timesteps=...
  [seed=...]` (confirmed identical in `foundry/run_rfd.slurm` and old IMPRESS's
  `scripts/rfd3.sh`).
- `input_spec_path` points at a real `DesignInputSpecification` JSON (`input`, `contig`,
  `unindex`, `length`, `ligand`, `select_fixed_atoms`, `select_buried`, `select_exposed`,
  `partial_t`) - RFD3 has no scaffold/guidance CLI override, so guided vs. unguided
  diffusion is selected entirely by WHICH file this points at, never by a flag. See
  `campaigns/data/alr/ALR_binder_design.json` for a real example.
- The `.params` file's `NAME`/`IO_STRING` record for a ligand may not match its bare
  3-letter code: ALR's real value is the literal `A:R`, not `ALR` (a deliberate,
  verified workaround for RFD3 misresolving the bare `"ALR"` literal). Always read this
  from the `.params` file, never hardcode or "clean up" a colon out of it.
