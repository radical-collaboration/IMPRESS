# The control arm ran at half the width, and under a different interlock

**Status:** diagnosed, **unfixed** · **Evidence:** job array 23680876 (arms 23680888 / 23680907 /
23681055 / 23680876), experiment `arms-smoke-20261109a` · **Items:** G13, and the A10
annotation it forces

## The problem, and the evidence

The four-arm smoke of 2026-11-09 was the first in which every arm completed and ran at least
three cycles. Packaging it for analysis turned up a confound that invalidates any comparison
against the control arm in that run.

**Model D composes 2 lineages per cycle; arms A, B and C compose 4.** Re-derived from each
arm's `provenance/graphs.jsonl` rather than from any summary:

| arm | runs | lineages | graph nodes/run | DesignNodes | pattern signature |
|---|---|---|---|---|---|
| A | 3 | 4 | 24 | 12 | `78e730c67750a361` |
| B | 6 | 4 | 24 | 24 | `78e730c67750a361` |
| C | 5 | 4 | 24 | 20 | `78e730c67750a361` |
| **D** | 6 | **2** | **12** | 12 | **`f8bcefed63c493ae`** |

Every arm declared the same campaign. `campaigns/delta-small-molecule-arms-smoke.yaml` says
`replicas: 4`, and the `campaign ...: model=... replicas=4` line appears in arms A, B and D.
It is absent from arm C only because that line is written by `run_campaign` and `serve_campaign`
does not write it - a small reporting gap of its own, and the reason arm C's declared width has
to be read from the spec rather than from its log.

**And the width decided the admission regime.** Trust was asserted per arm at widths 1 and 4 -
which is exactly what `plans/arms-preregistration.md` §10 step 2 prescribes - so each ledger
under `_trust_arms/arms-smoke-20261109a/<arm>/` holds `f5b21d82924fbcd0` and
`78e730c67750a361` and nothing else. D's width-2 signature is neither:

    arm   signature ran      in its own ledger?   trusted per run
    A     78e730c67750a361   yes                  T T T
    B     78e730c67750a361   yes                  T T T T T T
    C     78e730c67750a361   yes                  T T T T T
    D     f8bcefed63c493ae   NO                   U U U T T T

D's r0001-r0003 carry
`scrutiny: {trusted: false, cost_cap_fraction: 0.1, force_dry_run: true, mark_suspect: true}`
and it earned trust the ordinary way at r0004, after three consecutive clean runs.

So **the control arm spent half its campaign at half the width of the arms it is the control
for, under a different admission regime.** Cost per design, yield per cycle, node counts and
anything else measured per cycle are all measuring that as well as the model. The campaign log
of each arm is individually unremarkable, which is why this survived three previous smokes.

## Root cause

`ThresholdPlanner.__init__` takes `base_replicas: int = 2`
(`src/impress_a/policy/planners/explicit.py:79`), used at `explicit.py:127`:

    width = max(1, lineages or self.base_replicas)

**Nothing ever overrides it.** `_plan_d` (`src/impress_a/policy/registry.py:147-154`) returns
`ThresholdPlanner(stages=o.stages)`, and `ReasonerOptions` carries no replicas field at all. So
model D's width is a hardcoded 2 that appears in no configuration file and in no log line.

The campaign's declared `replicas` cannot correct it, because it is a **ceiling and not a
target** - `src/impress_a/runtime/executor.py:763-765`:

    replicas = intent.replicas
    if self.spec.replicas:
        replicas = min(replicas, self.spec.replicas)

The model-driven arms propose 4 and are clamped to 4; the deterministic arm proposes 2 and is
clamped to 2. `replicas: 4` in the spec is therefore a number only the arms with a model in them
ever reach, and a reader of that file has no way to know it.

This is section E's category wearing different clothes - configuration that exists and does
something only sometimes - and it is the same shape as G11's `target_front`, which was declared
in two places and read by nothing.

## Why replica multiplicity is in the signature at all

`Graph.pattern_signature` (`src/impress_a/compose/graph.py:56-65`) is documented as

> Identity for the interlock: SHAPE ONLY - tool ids plus typed edges.

and it builds

    parts = sorted(
        f"{n.tool}<-{','.join(sorted(self.nodes[d].tool for d in n.deps))}"
        for n in self.nodes.values()
    )

That is a sorted list **per node**, not a set. Four lineages contribute four identical
`rfd3_design<-` entries where two contribute two, so the joined string differs and the hash
differs. Multiplicity is in the identity, but it arrives as a side effect of repeated entries
rather than as something the docstring claims or a reader would predict from it. A10 already
measured the consequence (`f5b21d82…` at width 1, `f8bcefed…` at 2, `78e730c6…` at 4) and
leaves "whether multiplicity belongs in the signature" as an open ruling. Whatever that ruling
is, the docstring is currently wrong about what the signature covers, and that is part of why
this was surprising.

## The fix, specified and deliberately not applied

**Wire the declared width to model D's planner.** Give `ReasonerOptions` a replicas field fed
from `spec.replicas` where the other spec-derived options are filled
(`src/impress_a/cli/__init__.py:166-194`, beside `max_cycles` and `target_front`), and have `_plan_d` pass it as `base_replicas`.
Then D proposes the declared width, `executor.py:765`'s `min` clamps it to the same number, and
nothing else changes: a campaign declaring no `replicas` keeps `base_replicas`'s default of 2,
and the other three arms are already proposing the declared width themselves.

**Why this rather than asserting trust at width 2 as well.** Covering width 2 in the assertion
would remove the *trust* half of the confound and leave the *width* half untouched - D would
still produce half as many lineages per cycle as the arms it is compared against, and node
counts would still not be comparable. The assertion list is a workaround; the wire is the fix.
Both are available and only one of them makes the arms comparable.

**Cost of the fix.** Arm D goes from 0.34 to about 0.68 gpu-h per run, matching A, B and C.
Six cycles is then ~4.08 gpu-h against the campaign's 6.0 budget, and the width-4 signature is
already asserted in every arm's ledger, so the untrusted cost cap does not bind and D would run
trusted from r0001 like the others.

**The test that should exist, and does not.** One that builds a Stage from each model's planner
against a spec declaring `replicas: 4` and asserts every arm's composed graph carries four
lineages. Confirm it fails for D before the fix - the project's standard, and the one that
caught the first draft of the G9 test passing against the bug it was written for. The suite has
never compared the arms' composed widths **to each other**; every existing test checks one arm
in isolation, where a width of 2 is not wrong, merely different.

## What this does not settle

- **Whether multiplicity belongs in the signature.** A10's open ruling, untouched here. If it
  were removed, one assertion would cover every width and this class of confound would become
  impossible - at the cost of letting trust earned at width 1 license width 4, which is the
  reason it is in there.
- **The GPU-pinning half of A10**, which is a separate problem with a separate fix.
- **Whether arm D's 2 lineages or the models' 4 is the better experiment.** This document says
  only that they must be the same number, and that the campaign spec should be what says which.

## Draft Amendment 2 to the pre-registration - NOT APPLIED

`plans/arms-preregistration.md` is **not edited by this change**. Its own header rules that an
amendment is legitimate only "before the first arm had run", that afterwards "it voids the
comparison", and `impress-a compare` enforces that mechanically through `prereg_sha` - which all
four smoke manifests record as `c710f017…`. The smoke is a pre-production step (§11 is *smoke*
abort criteria, §12 is go/no-go *for production*), so the amendment below is legitimate before
the production arms are submitted and not before. Apply it then, in the same step as the
submission, or not at all.

> **Amendment 2, <date>, before any production arm has run.** The arms do not all compose the
> campaign's declared replica width: model D's planner carries a hardcoded `base_replicas = 2`
> and `CampaignSpec.replicas` is only a ceiling, so on the smoke of 2026-11-09 (array 23680876)
> arms A, B and C composed 4 lineages per cycle and D composed 2. Replica multiplicity is part
> of the pattern signature, so D's shape was not among the two this document's §10 step 2 tells
> the operator to assert, and D ran three of its six cycles under the untrusted interlock while
> the other three arms ran trusted throughout. This amendment touches three places:
>
> - **§10 step 2.** `--replicas 1 --replicas 4` presumes the arms agree on width. It must
>   either name every width any arm composes, or - preferably - the arms must be made to compose
>   one width (backlog G13), and this step must then verify that each arm's *ran* signature
>   appears in its own ledger, not merely that two asserted shapes do.
> - **§11.** "A width-4 run producing fewer than 4 `DesignNode`s" has no vocabulary for an arm
>   that composes 2 on purpose: a D run is a run of a width-4 *campaign* but not a width-4
>   *graph*, so the criterion is silent where it should abort. Replace it with: any arm whose
>   composed lineage count differs from the campaign's declared `replicas`, or from any other
>   arm's.
> - **§12.** "Admissions-under-scrutiny recorded per arm" tolerated exactly the thing that broke
>   comparability. Recording is not enough: a *difference between arms* in whether admissions
>   were under scrutiny is a confound, and should be a no-go on its own.
>
> The hypothesis, the tiers, the endpoint, the distinctness rule, the decision rule and every
> threshold are untouched.

## Also on the record

`exports/arms-smoke-20261109a.tar.gz` - the analysis bundle for this run - carries this finding
as caveat 2 of its `README.md`, with the same tables. That archive is **not** rebuilt for this
document, because re-packaging would change its published sha256 for a documentation edit.
