# Rosetta Toolkit

## Purpose
Physics-based structure refinement and scoring via PyRosetta, run as isolated
subprocesses (each tool spawns its own `python -m impress_a...rosetta_scripts...`-style
worker so `pyrosetta.init()` gets a clean interpreter per replica - PyRosetta's own init is
not safe to share across concurrent P2 fan-out). Three tools, adapted from
`IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s `packmin()`,
`fastrelax()` and `filter_shape()` steps: `packmin`, `fastrelax`, `filter_shape`.

## Canonical sequences
Stages 3-5 of the wider `small_molecule_binding` chain (see `toolkits/rfd3/SKILL.md` for
why this spans four toolkits rather than one):

    rfd3_design -> ligandmpnn_design -> packmin -> fastrelax -> filter_shape -> boltz_predict

Within this toolkit: `packmin` (side-chain packing + minimization in ligand context) ->
`fastrelax` (full relax + energy scoring) -> `filter_shape` (interface shape-complementarity
gate). Each passes its refined structure to the next; `filter_shape` is the last physics
gate before the structure is handed to Boltz-2 for independent co-folding confirmation.

## Cost posture
`fastrelax` dominates CPU cost in this toolkit (full relax protocol, `nstruct` scales it
linearly); `packmin` and `filter_shape` are comparatively cheap. Do not raise `nstruct` on
`fastrelax` for candidates that have not already cleared `packmin`'s `total_score` gate.

## Pitfalls
- Rosetta energies are lower-is-better and can be large negative numbers; the
  `total_score`-based QC gates here only enforce an upper bound (`max: 0.0`), not a lower
  one - a very negative score is not itself suspicious.
- `filter_shape`'s `shape_complementarity` gate threshold (`min: 0.55`) is a starting
  point copied from common interface-design practice, not calibrated against this
  project's own designs yet - expect to retune after the first live campaign.
- Each tool subprocess calls `pyrosetta.init()` independently; do not try to reuse a
  PyRosetta session across calls to save init time - that is what the old pipeline's
  packmin/fastrelax/filter_shape being separate scripts already encodes.
