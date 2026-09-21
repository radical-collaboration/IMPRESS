# Mock Toolkit

## Purpose
Deterministic stand-ins for the real design toolkit, for the laptop test tier. They model
the *shape* of the science - a self-consistency loop with real trade-offs - not the science
itself. Use them to exercise the manager, policies, composer, validator and QC layer
without an allocation. Do NOT use them to draw scientific conclusions.

## Canonical sequences
The self-consistency loop, which is the accept/reject gate of modern de novo design:

    mock_generate -> mock_design -> mock_fold -> mock_score

`mock_generate` proposes a backbone, `mock_design` proposes a sequence for it, `mock_fold`
predicts that sequence's structure, and `mock_score` measures agreement. The field-standard
gate is scRMSD < 2.0 A and TM-score >= 0.5; here `sc_rmsd` plays that role.

`mock_noodle` is a deliberately faulty generator: it completes successfully and reports a
confident `designability`, while producing a structure with essentially no secondary
structure. It exists so the QC layer can be tested at campaign scale.

## Cost posture
`mock_generate` and `mock_fold` dominate GPU cost; `mock_score` dominates CPU cost.
Cheap-screen-then-confirm applies: raise `nstruct` on `mock_score` only for candidates that
already cleared the fold gate.

## Pitfalls
- `mock_noodle` will pass every check except `has_secondary_structure`. Trusting
  `designability` alone is exactly the silent-failure mode this toolkit exists to model.
- `mock_design.temperature` trades sequence recovery against diversity; pushing it high
  collapses `seq_recovery` and the fold stage follows it down.
- `mock_generate.checkpoint` is frozen: mixing checkpoints mid-campaign makes designs
  non-comparable.
