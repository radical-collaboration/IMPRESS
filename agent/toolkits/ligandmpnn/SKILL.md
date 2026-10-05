# LigandMPNN Toolkit

## Purpose
Ligand-context-aware inverse folding: given a backbone (optionally with a bound ligand),
proposes a sequence and packs side chains around it. `ligandmpnn_design` is stage 2 of the
`small_molecule_binding` canonical sequence, run directly from a cloned `LigandMPNN`
checkout (not pip-installed) per `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`mpnn()` step. Do not confuse with `ProteinMPNN` (a separate repo/checkpoint set used by the
`protein_binding` pipeline, not part of this toolkit).

## Canonical sequences
Stage 2 of the wider chain (see `toolkits/rfd3/SKILL.md` for why this is a separate
toolkit rather than one monolithic one):

    rfd3_design -> ligandmpnn_design -> packmin -> fastrelax -> filter_shape -> boltz_predict

`ligandmpnn_design` consumes a `Backbone` and emits a `Complex` (a packed structure that
now carries a designed sequence plus the ligand context) - everything downstream in
PyRosetta operates on that packed structure, not on the raw backbone.

## Cost posture
Cheaper per-call than `rfd3_design` *in compute* (one forward pass plus side-chain packing,
not an iterative diffusion sampler), but not in wall clock, and the difference is the thing
to size a campaign against. Every backbone that reaches this stage should already have
cleared `rfd3_design`'s `has_secondary_structure` gate - designing sequence onto a
disordered backbone wastes the call.

**~280s of every invocation is `import torch` paging off Lustre, before any work starts.**
Measured on job 22669509: 276s elapsed to reach a `ModuleNotFoundError` in `run.py`'s
module-level imports, and ~360s wall for 9s of CPU repeating the full chain on a login node.
`walltime_s` is 1800 because of that, not because inference is slow. With `replicas: N` this
is N×280s of allocation spent on dynamic linking, which is worth knowing before sizing a run
rather than after.

## Pitfalls
- Requires `$MPNN_DIR` pointing at a cloned `LigandMPNN` checkout with its checkpoints
  present (`ligandmpnn_sc_v_32_002_16.pt`, `ligandmpnn_v_32_010_25.pt`) - it is cloned, not
  pip-installed, by `scripts/delta_env_setup.sh`.
- **Both checkpoints must be passed explicitly, as absolute paths, and the tool must run
  with `cwd=$MPNN_DIR`.** `run.py` defaults them to `./model_params/...`, resolved against
  the *current working directory* - which for a campaign is its own root, not the
  checkout. Left implicit, every single invocation fails on a missing checkpoint. The
  adapter does both; the original IMPRESS pipeline does too (explicit flags in
  `scripts/mpnn.sh`, plus a `scripts/mpnn_run.py` shim that chdir's into the checkout).
- **`run.py` is never invoked directly.** It cannot import under this venv's numpy, so the
  adapter writes `MPNN_SHIM` (`tools/ligandmpnn_agents.py`) into the task workdir and runs
  *that*, with `sys.executable` rather than a PATH-resolved `python`. The shim restores the
  numpy aliases LigandMPNN's bundled openfold still uses and hands off via `runpy` with
  `run_name="__main__"` - run.py does all its work under a `__main__` guard, so importing
  it any other way defines `main` and exits having done nothing, which looks exactly like a
  successful run that produced no output.
- **The numpy gap, and why it is not fixable by pinning.** The vendored openfold uses
  `np.int` (`openfold/np/residue_constants.py`) and `np.object` (`openfold/data/templates.py`),
  both removed in numpy 1.24; LigandMPNN pins numpy 1.23.5, and this venv carries 2.x because
  Boltz and the rest of the stack require it. `ml-collections` is the other half - nothing of
  ours imports it, but `openfold/config.py` does, so a venv without it fails at stage 2 before
  parsing an argument. It is installed by `delta_env_setup.sh` step 6. Job 22669509 found both,
  one after the other, from inside an allocation; `impress-a preflight` now runs the same shim
  with `--help` on a login node so the next one of these is free.
- Reported metrics are named `overall_confidence`/`ligand_confidence`, following
  LigandMPNN's own naming; do not rename them to a generic `seq_recovery` when comparing
  against ProteinMPNN-based work (a different tool, different metric semantics).
- `temperature` trades sequence diversity against confidence exactly like inverse-folding
  temperature elsewhere: push it high and `ligandmpnn_design` designs are less likely to
  clear `filter_shape` downstream.
- `fixed_residues` (a real flag, confirmed: `run.py --help`) is a space-separated string
  of residue indices, e.g. `"A16"` - held fixed during sequence design. Empty (the
  default) omits the flag entirely rather than passing an empty selection.
- `--number_of_batches` (what `num_seqs` maps to) is batches, not sequences directly -
  with `--batch_size` left at its default of `1`, one batch is one sequence, so
  `num_seqs` sequences come out. Confirmed against `run.py --help`; re-check before
  raising `num_seqs` past where this stops holding (i.e. before ever passing
  `--batch_size` explicitly).
