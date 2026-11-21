# mock_asd Toolkit

Surrogate twins for this project's own tools — Model A's anchor emitter, the steered
generator, the two ROME-stream clients and the two physics labels — so the whole chain runs
on a laptop at M1, with no GPU, no Dragon, no LLM and no allocation.

**Every number these tools report is a seeded draw. They model no chemistry, and their
outputs are not evidence about any molecule.** They exist to exercise the interfaces: the
artifact types, the metric names, the chain positions and the QC gates. Do not read a result
from this toolkit as a result about a binder.

## Purpose

This toolkit is the reason item 11 (the M1 integration test) can be *entered* in phase I
rather than run once at the end of it. The convention it establishes is one line:

> **No tool in this project is implemented before its twin exists.**

The twin is the interface. Writing it first fixes the `ArtifactType` a tool emits, the
metrics its `ToolSpec` declares and its position in the chain, while the real implementation
is still being written — so the M1 gate stands up early and becomes the regression test the
remaining episodes are built against, instead of a post-mortem run at the end.

## Canonical sequences

The design chain, stage for stage as the real one will be:

    mock_liganchor_propose -> mock_rfd3_steered_design -> mock_preorg_score ->
    mock_affdelta_score

`mock_liganchor_propose` is Model A: a ligand graph becomes the sampler's anchoring instruction,
emitted on the **classifier-free-guidance channel** (`active_donor`, `active_acceptor`,
`ref_atomwise_rasa`) plus `unindex`-style motif placement. Not `select_hotspots` — M0 measured
that RFD3 resolves a ligand `select_hotspots` and then drops the annotation in `build()`, so
the model is conditioned on zeros while the run reports success (backlog items 26, 29).

The labels chain, which is a second campaign rather than stages of the design chain, because
a measured value may not arrive from a task (CON-14):

    mock_md_label -> mock_abfe_label

Three twins are in this toolkit today: `mock_liganchor_propose`, `mock_md_label` and
`mock_abfe_label`. `mock_rfd3_steered_design` arrives with EI.9 and the two scoring clients
with EI.10, each alongside the tool it stands in for. Each remaining twin arrives with its
own tool's episode, which is what the convention above means in practice.

**The two label twins check their root input, which is the one way a twin can be worse than
nothing.** `mock_md_label` refuses an empty `design_dir` exactly as the real adapter does, because
`compose/validate.py:79`–`:81` is a literal `pass` for an unsatisfied root input. A twin that
accepted it would make the mock chain pass where the real chain refuses — certifying a campaign
that cannot run, which is worse than having no twin at all.

**`mock_md_label` carries a surrogate dial and `mock_abfe_label` does not**, and the asymmetry is
deliberate. `instability` has no MD counterpart and exists so a reader can push
`rmsd_plateau_frac` under its integrity floor and watch a *pattern's trust* be demoted rather than
a design be failed — the label-side shape of decision 0013. ATM needs no invented knob, because
`n_lambda_windows` is a real parameter that already moves the verdict: drop it toward 8 and the
overlap diagnostic fails. The honest lab condition is the mistake an operator actually makes.

## Cost posture

Thousandths of a GPU-hour per invocation, declared and non-zero. The agents return in
microseconds, so these are not measurements of anything; they are small enough that gate 5
and the untrusted-pattern cap stay out of the way, and non-zero so the budget ledger still
has something to count. The real tools declare at ≥2.25× their worst observed wall time
(item 21), which is a different number for a different purpose and is not derived from these.

## Pitfalls

**Every spec here declares `toolkit: mock`, and that is load-bearing rather than untidy.**
Gate 6 (`compose/validate.py::_g6_delivery`) classifies a tool as mock by
`ToolSpec.toolkit == "mock"` **exactly**, never by the toolkit directory's name and never by a
`mock_` id prefix — its own docstring says a prefix is a convention while the declared toolkit
is a fact. A twin declaring `toolkit: mock_asd` would therefore be classified **real** and
*admitted* by a campaign declaring `tool_delivery: real`: a chain of seeded draws reported as
science, which is the documented failure gate 6 exists to prevent. The directory is named
`mock_asd` so this project's twins are findable and separate from IMPRESS's own `mock`
toolkit; the **field** says `mock` because that is what the gate reads.

Two consequences of that split, both deliberate:

* This SKILL.md is keyed by the directory name (`mock_asd`), so a campaign enables it as
  `mock_asd` while its tools are classified as `mock`. Upstream's referential-integrity check
  used to compare `ToolSpec.toolkit` against the directory name, which made it miss this
  toolkit entirely *and* charge IMPRESS's own `mock/SKILL.md` with our six tools — jointly
  unsatisfiable with gate 6, and six permanent lines in `reg.errors`. **Fixed in IMPRESS
  `3ad5412`** (EI.28, item 32): it iterates the specs each directory actually staged, so this
  toolkit is now checked against this file. `tests/test_gate6_pair.py` keeps its own version
  of the check, because it names the missing tool rather than appending a line.
* `analysis/validate_tasks.py` keys `real_toolkit` on the same exact string, so a provenance
  record from a twin is correctly marked not-real without any further wiring.

**A twin's id carries the `mock_` prefix, and that is a correctness matter, not a label.**
Tool ids are one flat global namespace, and `_load_toolkit` raises `duplicate tool id` on a
collision — all-or-nothing, so the *other* toolkit registers nothing. A twin named for its real
tool would silently disable the whole real toolkit the day that tool lands, leaving one line in
`reg.errors` that nothing gates on. So: `mock_` on the **id**, `mock` in the **field**. The
prefix is the convention gate 6 declines to trust; the field is the fact it reads.

**A twin must populate every metric its real `ToolSpec` declares**, or a missing metric fails
at M2 on hardware instead of at M1 on a laptop — which is the one thing this toolkit is for.
