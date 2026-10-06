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
`fastrelax` for candidates that have not already cleared `packmin`'s gate.

**Measured on job 22684607** (one lineage, NVMe): packmin **15.9s**, fastrelax **25.9s**,
filter_shape **10.2s**, each including a fresh PyRosetta start. The cost models were
literature guesses 45-69x those figures, which is not harmless - gate 5 and the untrusted-
pattern cap refuse graphs against them, and on job 22675512 the inflated gpu-side estimates
summed past the cap and got `boltz_predict` truncated off the chain. They are corrected now;
`boltz_predict` is the one tool in this campaign with no measured figure.

Every call pays a fresh PyRosetta start, because a session cannot be reused (below). On
NVMe that is seconds. On HDD-backed storage it was **533.8s** - `import pyrosetta` alone
demand-pages a 598 MB `rosetta.so` - which is why `packmin` could not finish starting inside
its 300s budget on job 22675512 and why `$WORK_DIR` must be on `/work/nvme`. The walltimes
were never the defect; the storage was.

## Pitfalls
- Rosetta energies are lower-is-better and can be large negative numbers; the
  `total_score`-based QC gates here only enforce an upper bound, not a lower one - a very
  negative score is not itself suspicious.
- **The two `total_score` bounds are not the same kind of thing.** `fastrelax` gates at
  `max: 0.0`, which is upstream's `fastrelax_max_total_score` and a real quality threshold:
  a relaxed pose that cannot reach a negative score has not relaxed. `packmin` gates at
  `max: 1000.0`, which is only a sanity bound on an exploded structure. packmin is
  pack+min with no constraints - it prepares a pose for relaxation, and expecting it to
  score negative is expecting it to be fastrelax. It carried `max: 0.0` until job 22684607
  measured +145.3 from a healthy run whose fastrelax then reached -322.6; as written that
  gate would have failed essentially every packmin output, and a gate that always fires
  carries no information. 1000.0 is one observation wide and wants recalibrating.
- `filter_shape`'s `shape_complementarity` gate threshold (`min: 0.55`) is a starting
  point copied from common interface-design practice, not calibrated against this
  project's own designs yet - expect to retune after the first live campaign.
- Each tool subprocess calls `pyrosetta.init()` independently; do not try to reuse a
  PyRosetta session across calls to save init time - that is what the old pipeline's
  packmin/fastrelax/filter_shape being separate scripts already encodes.
- `ligand_params_path` (all three tools) is required whenever the input structure
  contains a non-standard ligand HETATM residue - without `-extra_res_fa <path>`,
  `pose_from_pdb()` will most likely raise on the unrecognized residue rather than
  silently mis-score it. Confirmed: old IMPRESS's `packmin.py`/`fastrelax.py`/
  `filter_shape.py` all pass this unconditionally (the latter also adds
  `-ignore_unrecognized_res -ignore_zero_occupancy`, which these agents mirror).
