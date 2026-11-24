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
  `partial_t`, `inference_sampler`) - RFD3 has no scaffold/guidance CLI override, so guided
  vs. unguided diffusion is selected entirely by WHICH file this points at, never by a flag.
  See `campaigns/data/alr/ALR_binder_design.json` for a real example. **The list is also in
  code**, as `rfd3_agents.SUPPORTED_SPEC_KEYS` beside `DISCARDED_SPEC_KEYS`, because a reader
  is not the layer that needs telling - the wrapper is, and it now refuses the discarded ones.
- **`select_hotspots` resolves and is then DROPPED, and the run reports success.** It is absent
  from the key list above on purpose. Measured on job `24155612` inside the Foundry container:
  `select_hotspots={"A:R": "S1,O5,O7,O8,S2,O6"}` resolves the ligand code and annotates all six
  atoms `is_atom_level_hotspot` on `atom_array_input` — and then
  `DesignInputSpecification.build()` drops the annotation entirely (it is not among the built
  array's categories), so `constants.py` supplies the zero default and
  `feats.is_atom_level_hotspot` reaches the network as **all zeros**. Two outcomes, and the second
  is the dangerous one: `infer_ori_strategy: "hotspots"` **asserts at build time**
  (`utils/inference.py:400`), because the strategy reads the annotation the build just dropped;
  with any other ori strategy the design **runs to completion, writes its outputs and exits 0**,
  having been conditioned on no hotspots at all. Nothing in the run says so. If you want
  atom-level conditioning, use `select_buried`/`select_exposed`, which are in the key list and are
  what `campaigns/data/alr/ALR_binder_design.json` uses.

  **The wrapper now refuses it rather than leaving this paragraph to do the work.** A Pitfall
  tells a reader; a refusal tells the run, and the run is what spends the allocation. RFD3 is a
  fixed binary in `foundry.sif` so the wrapper is the only layer that can act. Only the
  **ligand** form is refused - keyed by the entry's own declared `ligand` value - because only
  atom-level hotspots are dropped; a protein `select_hotspots` keyed by a chain reaches the
  model and still works.
- **The ligand is called `A:R` because `ALR` collides inside `foundry.sif`, and the colon is the
  workaround.** The `.params` file's `NAME`/`IO_STRING` record for a ligand may not match its
  bare 3-letter code: ALR's real value is the literal `A:R`, not `ALR`.

  **The mechanism, recorded here because this is the layer that needs it.** `foundry.sif`
  carries an **internal confound on the label `ALR` from an unrelated data source**, so RFD3
  running inside that container misresolves the bare `"ALR"` literal to something that is not
  this ligand. A name no such source can hold — one containing a colon — sidesteps the
  collision, and `A:R` is that name. It is **a deliberate, verified workaround for a container
  this project does not build**, not a style choice and not a typo.

  Two consequences, and both have already cost time:

  * **Always read the name from the `.params` file**, never hardcode it and never "clean up" a
    colon out of it. A normaliser that strips the colon restores the collision.
  * **The ligand therefore has two names, and both are real.** `A:R` is what the design chain's
    structures carry; `ALR` is what the MD parameterisation uses, because mol2 and tleap cannot
    carry a colon in a residue name. K1's artifact records both (`pdb_resname` and `resname`)
    for exactly this reason, and `asteer.features_impl.pocket_geom.resolve_pocket` gained an
    explicit `ligand_resname=` keyword because its colon-based inference could not express the
    second one at all.
