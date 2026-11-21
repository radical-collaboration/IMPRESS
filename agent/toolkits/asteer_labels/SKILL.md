# asteer_labels Toolkit

The two physics measurements this project's surrogates are trained against: `md_label` for the
preorganisation quantities Model B predicts, and `abfe_label` for the binding free energy Model C
predicts. They are the only tools in this project that produce **measured** values rather than
predicted ones, and that distinction is the whole reason the toolkit exists separately.

## Purpose

**A measured value cannot arrive from a task, so these cannot be stages of the design chain.**
`runtime/executor.py:428` states the invariant — a measured value "arrives through
`ingest_measurement`, **never from a task**, and carries `AUTHORITY_ASSAY` — which is what lets it
supersede" — and `_authority_of()` (`:438`) enforces it by deriving the authority band from the
toolkit: `AUTHORITY_PHYSICS if toolkit == "rosetta" else AUTHORITY_ML_PREDICTOR`. A label emitted
as a task output inside the design chain would be *another prediction*, superseding nothing, which
is the one thing these tools exist to do. Extending `_authority_of()` so a task could claim physics
authority was considered and rejected: it would let *any* task claim it.

So these two tools run in their **own campaigns**, and their results enter the design tree through
the control plane. Two campaigns, not one: `md_label` and `abfe_label` are dispatched at different
rates and ask the allocation for different resources (decision L1, impress-a plan item 36).

**They also cannot hang off a design tool's `post_process`.** That phase (`tools/agent.py:203`)
runs inside the same task, synchronously; its job is `gates.evaluate` plus metric extraction, and
it computes `cost_measured` from that task's own usage. A multi-GPU-hour MD run there would be
billed to whichever design tool it rode in on, would block that task's QC for hours, would wreck
item 21's accounting — and would still land at the wrong authority.

## Canonical sequences

Two chains, one tool each, because the two measurements are dispatched independently:

    md_label          # the preorganisation campaign
    abfe_label        # the free-energy campaign

They are **typed as a chain even though they run as two**, and that is not redundant:
`abfe_label` requires `structure: {type: Complex}`, which `md_label` produces as its second output
— the equilibrated holo frame, which is also the structure ATM should start from. So a design that
gets both measurements gets them in that order, and the type edge says so. The ABFE campaign
receives that structure as its root input.

`md_label` is a **root**: the complex arrives as a path *parameter* (`design_dir`), exactly as
`rfd3_design` takes `input_spec_path`. Nothing upstream checks that it arrived —
`compose/validate.py:79`–`:81` is a literal `pass` for an unsatisfied root input — so the agent
refuses at parameterize time instead. See Pitfalls.

## Cost posture

Declared at **2.25× the worst observed**, per item 21, which makes these the two most expensive
declarations in the project:

| Tool | Worst observed | Declared | Needs available, at the interlock's 10% cap |
|---|---|---|---|
| `md_label` | ~3.6 GPU-h | **8.1** | 81 GPU-h — **fits** a 96–192 per-round envelope |
| `abfe_label` | ~8 GPU-h | **18** | 180 GPU-h — does **not** fit |

That table is why the chain was split. `md_label` alone promotes the ordinary way: three
consecutive clean runs, no assertion. `abfe_label` alone still needs
`impress-a trust --assert --reason "<job id>"`, with the M2 stubbed run as its named evidence —
never by under-declaring, which is the other documented failure. A single two-stage chain declared
26.1 and would have needed 261 available, so *both* halves would have needed the assertion.

## Pitfalls

**The metric name and the property name differ on purpose, and the property name is the contract.**
`abfe_label` reports `dg_abfe` as its metric; the bridge ingests it as the property
**`dg_corrected`**, which is the name Model C's prediction carries and therefore the name
supersession matches on. A measurement ingested under a name nothing predicted is **accepted
silently**: `core/tree.py:91` finds nothing under that name, so the outranks check *and* the
supersession bookkeeping are both skipped, `:97` stores it and `:98` returns `True`. No error, no
log line, no `__superseded` key — and the first `__superseded` entry is M3's own success signal, so
a mismatched name suppresses the detector that would have reported the loss. The naming table in
the impress-a plan (item 36) is the contract; **never** ingest under `dg_lcb`, `sigma_dg` or
`sigma_preorg`, which describe a posterior rather than a molecule.

**A metric that cannot be read is omitted, never defaulted.** `rosetta/SKILL.md`'s
`interaction_energy` note is the precedent: `0.0` is a passing value for most bounds, so a
defaulted `dg_abfe` of 0.0 reads as a 0 kcal/mol binder rather than as a broken run. The
`metrics_reported` gate catches the omission; nothing catches the default.

**Convergence gates are `integrity`, not `acceptance`.** Per decision 0013 only integrity failures
demote a pattern in the trust ledger, and a measurement that did not converge is a broken
instrument rather than a weak design. Filing it as acceptance would count a tool failure against
the molecule — and would leave the pattern's trust untouched, so the next batch would run the same
broken instrument.

**`md_replicates` is not `replicas`.** The campaign's `replicas` is a cap on independent design
lineages (`runtime/executor.py:861`); `md_replicates` is the number of MD seeds behind one
measurement. Two fields one letter apart with different owners is how a label batch silently
becomes four times its budget.

**The ligand resname may be the literal `A:R`, not `ALR`.** Read it from the `.params` file, never
hardcode it and never "clean up" the colon — a verified workaround for RFD3 misresolving the bare
code, recorded in `IMPRESS/agent/toolkits/rfd3/SKILL.md`.

**Neither adapter is implemented yet, and both refuse rather than pretend.** The `entry:` classes
exist and raise with a message naming what is missing. That is deliberate: a label tool that
returned plausible numbers on a laptop would be the most expensive silent failure in this project,
because its output supersedes a prediction and is never recomputed.
