# Mock Toolkit

## Purpose
Deterministic stand-ins for the real design toolkit, for the laptop test tier. They model
the *shape* of the science - a self-consistency loop with real trade-offs, and a surrogate of
the six-stage small-molecule binding chain - not the science itself. **Every number these
tools report is a seeded random draw. They model no chemistry, and their outputs are not
evidence about any molecule.** Use them to exercise the manager, policies, composer,
validator and QC layer without an allocation. Do NOT use them to draw scientific conclusions.

**Three families live here**: the self-consistency loop, the six-stage small-molecule binding
surrogate, and -- since 2026-11-21 -- the six ASD twins that were `toolkits/mock_asd/`. The
merge is not tidying. That directory existed only because its twins lived in a sibling
checkout, and a directory named `mock_asd` staging specs that declare `toolkit: mock` is a
split that invites exactly one "fix": renaming the field to match the directory, which is the
dangerous direction (see the gate-6 note below). One directory, one name, nothing left to
reconcile.

All three families are `toolkit: mock` and that is load-bearing rather than tidy. Gate 6
(`compose/validate.py::_g6_delivery`) classifies a tool by `ToolSpec.toolkit == "mock"`
exactly, so a surrogate sitting in a toolkit of its own would be classified **real** and
admitted by a campaign declaring `tool_delivery: real` - a chain of random number generators
reporting its draws as science, which is the documented failure that gate exists to prevent.

## Canonical sequences
The self-consistency loop, which is the accept/reject gate of modern de novo design:

    mock_generate -> mock_design -> mock_fold -> mock_score

`mock_generate` proposes a backbone, `mock_design` proposes a sequence for it, `mock_fold`
predicts that sequence's structure, and `mock_score` measures agreement. The field-standard
gate is scRMSD < 2.0 A and TM-score >= 0.5; here `sc_rmsd` plays that role.

`mock_noodle` is a deliberately faulty generator: it completes successfully and reports a
confident `designability`, while producing a structure with essentially no secondary
structure. It exists so the QC layer can be tested at campaign scale.

The small-molecule binding surrogate, which mirrors the real chain stage for stage:

    mock_rfd3_design -> mock_mpnn_design -> mock_packmin -> mock_fastrelax ->
    mock_filter_shape -> mock_boltz_predict

Six tools standing in for `rfd3_design -> ligandmpnn_design -> packmin -> fastrelax ->
filter_shape -> boltz_predict`. Same stage count, same typed ports, same patterns, same
parameter names, same metric names, same QC gates - **including the acceptance thresholds**,
which are the real campaign's own (`complex_plddt >= 0.75`, `ligand_iptm >= 0.4`,
`shape_complementarity >= 0.55`, `interaction_energy <= -8.0`, `ss_fraction >= 0.5`, and
fastrelax's integrity bounds `total_score <= 0` and `fa_rep <= 500`). It exists so a person
can watch a campaign behave - more cycles or fewer, satisfied or run to the cycle bound, a
pattern promoted or held under the untrusted cost cap - without a GPU allocation. Driven by
`campaigns/mock-small-molecule-binding.yaml`; `campaigns/README.md` names the knobs.

The quality signal is passed hand to hand down the chain rather than read from the top -
`ss_fraction` becomes a confidence, the confidence becomes an energy, the energy becomes a
shape score, the shape score becomes a pLDDT - because `TaskRequest.inputs` carries a node's
IMMEDIATE dependencies and nothing further back. A stage reaching two hops for a number would
silently freeze it at its default and every knob upstream of it would stop mattering.

`mock_rfd3_design.difficulty` is the one parameter with no real counterpart: rfd3 has no such
flag. It is the surrogate's own dial, so a reader can make the campaign easy or impossible
without editing a threshold.

`mock_join` is the branching shape, and the only tool in any toolkit with two typed inputs:

    mock_generate ─┐
                   ├─> mock_join -> mock_score
    mock_design  ──┘

It takes a `Backbone` on one port and a `ProteinSequence` on the other, and its agent asserts
which arrived where. It exists because nothing else could express that shape, so nothing could
catch a dispatcher that keyed inputs positionally - a node with two typed inputs type-checks at
composition and mis-wires at runtime, silently, because a positional scan returns whichever
dependency comes first. Use it whenever a test needs a real branch rather than a chain.

The ASD design chain, stage for stage as the real one will be:

    mock_liganchor_propose -> mock_rfd3_steered_design -> mock_preorg_score ->
    mock_affdelta_score

`mock_liganchor_propose` is Model A: a ligand graph becomes the sampler's anchoring
instruction. The `AnchorSpec` it emits declares the **classifier-free-guidance** channel
(`active_donor`, `active_acceptor`, `ref_atomwise_rasa`) plus `unindex`-style motif placement.
What `rfd3_steered_design` then *renders* is the burial pair `select_buried` / `select_exposed`,
with the CFG trio opt-in and off by default -- a correction made on evidence in the real
renderer, whose own header carries the argument. Neither path emits `select_hotspots`: M0
measured that RFD3 resolves a ligand `select_hotspots` and then drops the annotation in
`build()`, so the model is conditioned on zeros while the run reports success (backlog items
26, 29).

`mock_rfd3_steered_design` runs the FK Tier-1 loop over seeded draws -- K particles, score,
resample, re-noise -- so the resampling arithmetic and the `n_resamples` metric are exercised
without a sampler. `mock_preorg_score` and `mock_affdelta_score` stand in for the two ROME
stream clients, and emit the model id and version the `surrogate_version_present` gate reads.

The ASD label chain, which is a second campaign rather than stages of the design chain,
because a measured value may not arrive from a task (CON-14):

    mock_md_label -> mock_abfe_label

**The two label twins check their root input, which is the one way a twin can be worse than
nothing.** `mock_md_label` refuses an empty `design_dir` exactly as the real adapter does,
because `compose/validate.py:79`-`:81` is a literal `pass` for an unsatisfied root input. A twin
that accepted it would make the mock chain pass where the real chain refuses - certifying a
campaign that cannot run, which is worse than having no twin at all.

**`mock_md_label` carries a surrogate dial and `mock_abfe_label` does not**, and the asymmetry
is deliberate. `instability` has no MD counterpart and exists so a reader can push
`rmsd_plateau_frac` under its integrity floor and watch a *pattern's trust* be demoted rather
than a design be failed - the label-side shape of decision 0013. ATM needs no invented knob,
because `n_lambda_windows` is a real parameter that already moves the verdict: drop it toward 8
and the overlap diagnostic fails. The honest lab condition is the mistake an operator actually
makes.

## Cost posture
`mock_generate` and `mock_fold` dominate GPU cost; `mock_score` dominates CPU cost.
Cheap-screen-then-confirm applies: raise `nstruct` on `mock_score` only for candidates that
already cleared the fold gate.

## Pitfalls
- `mock_noodle` will pass every check except `has_secondary_structure`. Trusting
  `designability` alone is exactly the silent-failure mode this toolkit exists to model.
- `mock_join` fails its own integrity gate when its inputs arrive on the wrong ports, which is
  deliberate: a mis-wire is the tool being handed the wrong thing, not a design falling short
  (decision 0013), so it must fail the node rather than report a plausible number.
- `mock_design.temperature` trades sequence recovery against diversity; pushing it high
  collapses `seq_recovery` and the fold stage follows it down.
- `mock_generate.checkpoint` is frozen: mixing checkpoints mid-campaign makes designs
  non-comparable.
- The surrogate chain's `cost_model` figures are thousandths of an hour and are **not
  measurements of anything** - the agents return in microseconds. They are sized so a laptop
  budget is never what stops the campaign, while staying non-zero so the ledger still counts.
  Do not read them as a prediction of what the real chain costs; the real specs carry those.
- `mock_rfd3_design.difficulty` above ~0.75 drives `ss_fraction` under the 0.3
  `has_secondary_structure` floor, which is an **integrity** failure: the node fails and the
  pattern's trust suffers. Between roughly 0.5 and 0.75 it only misses the 0.5 acceptance
  threshold, which fails the node and leaves trust alone (decision 0013). Reaching for the
  dial to "make the campaign fail" without noticing which kind of failure you bought is the
  mistake it exists to make visible.

**A twin's id carries the `mock_` prefix, and that is a correctness matter, not a label.** Tool
ids are one flat global namespace, and `_load_toolkit` raises `duplicate tool id` on a
collision - all-or-nothing, so the *other* toolkit registers nothing. A twin named for its real
tool would silently disable the whole real toolkit the day that tool lands, leaving one line in
`reg.errors` that nothing gates on. So: `mock_` on the **id**, `mock` in the **field**. The
prefix is the convention gate 6 declines to trust; the field is the fact it reads.

**A twin must populate every metric its real `ToolSpec` declares**, or a missing metric fails at
M2 on hardware instead of at M1 on a laptop - which is the one thing this toolkit is for.

**The ASD twins' `cost_model` figures are thousandths of a GPU-hour**, declared and non-zero,
sized so gate 5 and the untrusted-pattern cap stay out of the way while the ledger still has
something to count. The real ASD tools declare at >=2.25x their worst observed wall time, which
is a different number for a different purpose and is not derived from these.

**`analysis/validate_tasks.py` keys `real_toolkit` on the same exact `mock` string**, so a
provenance record from any twin here is marked not-real with no further wiring.
