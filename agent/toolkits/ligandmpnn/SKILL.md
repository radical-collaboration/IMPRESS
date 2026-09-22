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
Cheaper per-call than `rfd3_design` (one forward pass plus side-chain packing, not an
iterative diffusion sampler), but every backbone that reaches this stage should already
have cleared `rfd3_design`'s `has_secondary_structure` gate - designing sequence onto a
disordered backbone wastes the call.

## Pitfalls
- Requires `$MPNN_DIR` pointing at a cloned `LigandMPNN` checkout with its checkpoints
  present (`ligandmpnn_sc_v_32_002_16.pt`, `ligandmpnn_v_32_010_25.pt`) - it is cloned, not
  pip-installed, by `scripts/delta_env_setup.sh`.
- Reported metrics are named `overall_confidence`/`ligand_confidence`, following
  LigandMPNN's own naming; do not rename them to a generic `seq_recovery` when comparing
  against ProteinMPNN-based work (a different tool, different metric semantics).
- `temperature` trades sequence diversity against confidence exactly like inverse-folding
  temperature elsewhere: push it high and `ligandmpnn_design` designs are less likely to
  clear `filter_shape` downstream.
