# The control arm ran at half the width, and under a different interlock

**Status:** **fixed in code**, unrun on hardware · **Evidence:** job array 23680876 (arms 23680888 / 23680907 /
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

## The ruling: breadth is held fixed, and the campaign declares it

Recorded because it is a decision and not a bug fix. **Every arm composes the campaign's
declared `replicas`, and what varies between the arms is the reasoning track and its cost.**
The reason: the comparison exists to observe differences that follow from the reasoning, and
from what the reasoning costs. An arm drawing 3 lineages where another draws 4 is targeting a
smaller ensemble and spending differently per cycle, and the endpoint - distinct T2 designs per
billed node-hour - cannot separate that from reasoning quality. A shared fixed breadth
constrains the systems to target an ensemble of similar size, which is the only footing on
which the per-design numbers mean anything.

**Model A's explore/exploit lineage numbers are an inherited artifact, not architecture.**
`PROFILES` (`policy/planners/agentic.py:64`) carries explore 3 / exploit 2, converted from
`FourNodePolicy`'s shipped numbers and marked "unchanged". Model A's purpose is to project
LLM-based reasoning onto a research-cycle-like structure; the particular breadth numbers it
inherited are not a rigorous part of that, so the declared width overrides them. **A's quality
and diversity fractions are untouched** - those are the strategy, and they stay model
behaviour.

## The fix, and why it was not one wire

The write-up's first draft said this was one wire into `_plan_d`. It was not, and a test that
compared the arms *to each other* is what showed it: **all four planners built
`ThresholdPlanner(stages=stages)` and inherited `base_replicas = 2`**, so the declared width
reached none of them. Three separate routes to the same confound:

1. **D and C's mechanics** took the hardcoded 2 and nothing else. This is the one the smoke
   measured.
2. **A and B override with numbers of their own** - A from `PROFILES`, B from its oracle's
   `replicas` reply. They reached 4 on the smoke only because a live Beam model asked for 4
   every cycle. **A degraded turn would have silently halved that arm's width**, changed its
   pattern signature, dropped it into the untrusted interlock, and been attributed to the
   model. Confirmed by probe: with no live client, A and B compose **3**.
3. **A directive that names no width composed ONE lineage.**
   `ExternalPlanner._to_stage` read `directive.get("replicas") or 1`, so arm C's width was
   whatever its caller happened to say. Beam named 4 every cycle on the smoke, so this never
   bit; it would have the moment a caller went quiet about breadth.

What changed:

- `ReasonerOptions.replicas`, fed from `spec.replicas` in `cli._options_for` and from
  `CampaignObservation.replicas` in `cli._role_pair`, so a remotely driven arm gets it too.
- Every planner that owns a `ThresholdPlanner` takes `base_replicas` and forwards it:
  `_plan_a`, `_plan_b`, `_plan_c`, `_plan_d`.
- **A and B treat a declared width as authoritative** over their own number
  (`self.declared_width`), and keep their own when the campaign declares none.
- `ExternalPlanner` passes `lineages=None` rather than 1 when the directive is silent, so the
  mechanics apply the declared width.
- `CampaignObservation.replicas` carries it across the control plane.

`CampaignSpec.replicas` remains a ceiling in the executor - it can clamp a graph down but
cannot add lineages, so the planners are where the width has to be composed. 0 everywhere still
means "the planner's own default", so no campaign that declares no width moves.

**Cost.** Arm D goes from 0.34 to ~0.68 gpu-h per run, matching the other three: ~4.08 gpu-h
over six cycles against the 6.0 budget, and the width-4 signature is asserted, so the untrusted
cap does not bind.

## Trust: assert every composable width

`impress-a trust --assert` defaulted to the campaign's declared width alone. It now defaults to
**every width from 1 to the declared one**, because a width nobody asserted runs under forced
dry-run and a 10% cost cap, and the arm that falls through is whichever one happens to compose
something narrower. On the smoke spec that is now four signatures rather than two:

    f5b21d82924fbcd0  replicas=1
    f8bcefed63c493ae  replicas=2     <- the one arm D fell through
    fa8f3389d6805246  replicas=3     <- the one model A's explore profile would have hit
    78e730c67750a361  replicas=4

Width 3 appearing in that list is the latent hazard in route 2 made concrete: nothing had ever
asserted the width a degraded model-A arm would compose. Asserting the range costs one composed
graph per width and no allocation.

## What this does not settle

- **Whether multiplicity belongs in the signature.** A10's open ruling, untouched here. If it
  were removed, one assertion would cover every width and this class of confound would become
  impossible - at the cost of letting trust earned at width 1 license width 4, which is the
  reason it is in there.
- **The GPU-pinning half of A10**, which is a separate problem with a separate fix.
- **What the declared width should BE.** The ruling above says the arms must agree and that the
  campaign declares it; it does not say 4 is the right number. That is a question about ensemble
  size and allocation, and `replicas: 4` is inherited from the smoke spec rather than argued for.
- **Model A's remaining breadth seam.** `PROFILES` still carries explore 3 / exploit 2, now
  unreachable whenever a campaign declares a width. The numbers are left in place rather than
  deleted because they are also the quality and diversity fractions' home, and because a
  campaign that declares no width still uses them. A reader should not take their presence as
  evidence that model A varies its breadth under this experiment: it does not.

## Draft Amendment 2 to the pre-registration - NOT APPLIED

`plans/arms-preregistration.md` is **not edited by this change**. Its own header rules that an
amendment is legitimate only "before the first arm had run", that afterwards "it voids the
comparison", and `impress-a compare` enforces that mechanically through `prereg_sha` - which all
four smoke manifests record as `c710f017…`. The smoke is a pre-production step (§11 is *smoke*
abort criteria, §12 is go/no-go *for production*), so the amendment below is legitimate before
the production arms are submitted and not before. Apply it then, in the same step as the
submission, or not at all.

> **Amendment 2, <date>, before any production arm has run.** The arms did not all compose the
> campaign's declared replica width. Every planner inherited `ThresholdPlanner`'s
> `base_replicas = 2` and `CampaignSpec.replicas` is only a ceiling, so on the smoke of
> 2026-11-09 (array 23680876) arms A, B and C composed 4 lineages per cycle - because a live
> model asked for 4 - and model D composed 2. Replica multiplicity is part of the pattern
> signature, so D's shape was not among the two this document's §10 step 2 told the operator to
> assert, and D ran three of its six cycles under the untrusted interlock while the other three
> ran trusted throughout.
>
> **Ruling, now implemented (backlog G13): breadth is held fixed across the arms and the
> campaign declares it.** The comparison exists to observe differences that follow from the
> reasoning track and from what that reasoning costs; an arm targeting a smaller ensemble
> spends differently per cycle for a reason the endpoint cannot separate from reasoning
> quality, so every arm targets an ensemble of similar size. Model A's inherited explore-3 /
> exploit-2 breadth is overridden by the declared width; its quality and diversity fractions
> are untouched. **§5's description of model A should no longer imply that it varies its
> breadth.** This amendment touches four places:
>
> - **§10 step 2.** `--replicas 1 --replicas 4` presumes the arms agree on width. The command
>   now defaults to every width from 1 to the declared one, and the step should drop its
>   explicit `--replicas` flags and instead verify that each arm's *ran* signature appears in
>   its own ledger - not merely that two asserted shapes do.
> - **§11.** "A width-4 run producing fewer than 4 `DesignNode`s" has no vocabulary for an arm
>   that composes 2: a D run is a run of a width-4 *campaign* but not a width-4 *graph*, so the
>   criterion was silent where it should have aborted. Replace it with: any arm whose composed
>   lineage count differs from the campaign's declared `replicas`, or from any other arm's.
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
