# IMPRESS-A — the API and the campaign loop

**Format:** three acts, four running orders — the full path runs 43.1 min of speech, and **D · for
users** is a 23.5-minute path that keeps the experiential slides and drops the protocols ·
**Audience:** the lab, plus anyone who has to write against this (a policy author, a toolkit
author, something driving a campaign from outside the allocation) — and, on order D, anyone who
only has to *run* it.

**This is not the comparison deck.** `../build_deck.js` is the argument against the reference
IMPRESS pipeline and it stays as it is; it carries its own `run.json` and its own derivation. This deck answers a
different question: *what are the surfaces, and what does the loop do between them?* Where the two
overlap (dispatch seam, gates), this one cites and does not re-argue.

**Derived against `examples/agentic-small-molecule-binding` @ `bf32d1d`.** `agent/` has not changed since `c163fe2`; the branch has, which is
where the live evidence on slides 24-26 comes from. All 42 anchors verify against the working
tree at `bf32d1d` (`check_anchors.py --root .`, run from the repo root). Companion files in this directory, same roles as
the skill describes: `build_deck.js`, `run_model.py` → `run.json`, `anchors.json`, `deck.json`,
`CODE_FOR_DECK.md`, and the generated `DECK_SCRIPT.md`.

---

## The spine: six surfaces, one engine

The deck's organising claim is that IMPRESS-A has **six APIs, not one**, and that the separation is
enforced rather than asserted — `tests/test_layering.py` walks the source with `ast` against an
allow-list, so `policy` cannot reach `tools`, and `compose` cannot reach `exec`.

| # | Surface | Who writes against it | Entry point |
|---|---|---|---|
| 1 | CLI | an operator | `cli/__init__.py` — `run` / `tools` / `preflight` |
| 2 | Campaign YAML | a scientist | `CampaignSpec`, `runtime/executor.py:58` |
| 3 | `ControlPolicy` | a reasoner author | `policy/base.py` — `decide` or `conduct` |
| 4 | `CampaignSession` | a reasoner, in or out of process | `core/session.py` |
| 5 | `CampaignControlPlane` | an external caller | `control/plane.py`, `control/http.py` |
| 6 | Toolkit spec + `TaskAgent` | a tool author | `tools/spec.py`, `tools/agent.py` |

## The three dimensions, and the weak one

| Act | The question | The evidence | What it concedes |
|---|---|---|---|
| 1 · Functionality | What can you *write* against this that you cannot write against a pipeline? | a tool is a `spec.yaml` + a `TaskAgent`; a reasoner is one method; both admitted through the same five gates | the only toolkits that exist are the six stages of one chain, and no third party has authored either |
| 2 · Performance | What does the loop cost, and where does it serialise? | one `conduct` reasoner submitting many experiments; `as_completed` in finish order; the executor as sole writer of campaign state; a ~3 s mock campaign that refuses a graph and shrinks it; and slide 19, the only measurement anywhere of the two levers that move the science | **no serial baseline and no concurrent run**: every mock run here is one experiment in flight, and on the real chain `replicas > 1` has never executed (backlog A10). The 2026-10-26 analysis does NOT retire this — it measures both levers on *other code*, which makes it sharper, not softer |
| 3 · Usability | Application, platform, or component? | one YAML + one command; runtime-discovered toolkits; the same protocol in two transports; four user-directed slides, including the live 4 h run next door; and slide 26, how an agentic run fails on a cluster | **the component claim is empty** — nothing external has ever driven a campaign; `RemoteSession` is tested, not used; the live run is somebody else's code; and of the three cluster failure modes on slide 26 this package catches exactly one |

**Say the weak dimension out loud in the first three minutes.** It is usability-as-a-component: the
control plane and `RemoteSession` are the most carefully designed surfaces here and the least
exercised. Nothing outside this package has ever driven a campaign.

**And say what the live slides are not.** Slides 24-25 show an LLM driving the *reference* IMPRESS
pipeline's toolkit for four hours on Delta — the closest thing in this repository to what this
engine is for, and it is not this engine: different code, no campaign engine, no gates, no
interlock, no trust. It is evidence that the idea pays on this hardware. It is not evidence that
this implementation does. Its own caveats travel with it, and **both got worse with the 2026-10-26
analysis next door, not better**: the reference arm's *own* `fastrelax` pass rate fell 63.6% -> 49.4%
with the decision layer held fixed, only 1.3 of those 14.2 points explained by binder length, so the
3.3x is an upper bound nobody should quote; and the `fastrelax` gap it turns on is no longer the
decision layer's to claim -- the agentic *harness* pack-minimises before relaxing and the reference
harness never does (0 of 5,002 decoys across 14 runs), *including the scripted route at 48 of 48,
which has no model in it at all*. It is a confound between the two examples.

**One claim to state precisely rather than loosely.** `replicas > 1` *does* execute — the mock
campaign mined for this deck composed three lineages, had them refused at the interlock's cost cap,
and ran two. What has never executed is `replicas > 1` on the **real** six-stage chain, which is
backlog A10, and the slide that shows the refusal says so on the slide.

## Per-slide intent (draft)

**Framing (1-7)** — title with the commit; what this is not (one chain, one node, no external
driver); the six-surface table above; the loop as one line: `observe → DECIDE → compose → validate
→ execute → analyze → update → terminate?`; and the point that the reasoner is *not* the loop body.

Then **the two mediation slides**, which are the only place in the deck where both ends are in
one picture:

- **6 · what the caller states, and what comes back.** Four inbound groups — what “better” means
  (`goal` + `objectives`), what may run (a toolkit inventory discovered from a directory), what it
  may spend and where, and who decides — against the live channels out (`observe()` returning the
  *same* object the policy sees, events, provenance, ledger, artifacts) and the steering that goes
  back the other way. Ends on the asymmetry: the caller never names a task, a node or a tool
  parameter, and the engine never invents an objective or a budget.
- **7 · how that becomes processes on nodes.** Seven stages left to right — intent, compose, admit,
  parameterize, deploy, engine, tasks — each with the file that does it; the typed return path
  under them; and two cards for the parts that are genuinely ours: resource shapes are not
  portable (RADICAL ranks vs Dragon process templates), and the two asyncflow idioms (an unawaited
  future as an argument IS a DAG edge; `gather` is for independent work). Red line at the bottom:
  every realized task in the mined run is a mock, and the real chain has only run one lineage wide.

**Act 1 · Functionality (8-14)** — the YAML as the scientific question (`stages`, `params`,
`objectives`, `replicas`) next to the `ExperimentIntent` a policy emits, to make the point that a
policy never names a tool parameter. Then `Decision` as four cases. Then `ToolSpec` — typed ports
over `ArtifactType`, `Pattern` as *scheduling* implication, `frozen_parameters`, and the
load-is-validating rule (default outside its own range is a load-time error; a toolkit is disabled
whole). Then `TaskAgent`'s four phases, orchestrated by `__call__` and deliberately not
overridable — the name on the slide is `__call__`, because that is what the file has; the
module's own docstring and `agent/CLAUDE.md` still say `execute()`. Close on the
five gates + dry-run, and `ValidationFailure.transient` — the field that stops a policy answering
contention by mutilating its own intent.

**Act 2 · Performance (15-20)** — `CampaignSession` as the inversion: the loop used to call the
reasoner, now the reasoner calls the campaign. Two-lane coroutine diagram: `pump` vs `conduct`,
whichever finishes first ends the campaign. Then the mined run, in full: three graphs composed, one
refused at the interlock as `transient`, two admitted at width 2, four nodes absorbed, all four
`suspect`, front of 3, in about 3 s. Then measured-and-not-measured. Then the interlock as the one place
the API *refuses* breadth — and `pattern_signature` as shape-only-but-not-quite: it excludes
parameter values deliberately and includes replica multiplicity by accident, so the width-3 graph
and the width-2 graph are two patterns (mined: two signatures, two cleans, `promote_after = 3`,
nothing promoted).

New in this revision: **19 · the two levers that move the science, and nobody has pulled both.** The
skill's "scale and scientific yield are not linear in each other" slide, which this act had nothing
like. A packing ladder of one policy held fixed at k = 1, 2, 4, 6, 8 (x5.52 backbones per node-hour,
x5.11 high-quality folds per GPU-hour), against four decision layers at one hour and k = 1 — where
the spread across *models* (2.88 to 8.08 passing folds per GPU-hour) is larger than the gap between
"model" and "no model", and **Qwen3.5-122B comes in below the scripted route, which has no model in
it at all**. The decision layer is worth about x3 at matched packing; no run has ever had both. Every
figure **TRANSCRIBED**, and the red line says why it is in an act about *this* engine: IMPRESS-A has
measured **neither** lever, because `replicas` **is** the packing lever and has never exceeded 1 on
the real chain.

**Act 3 · Usability (21-29)** — the act opens **user-directed**, with four slides that carry no
protocol and almost no code:

- **22 · what running one is actually like.** Five steps from the user's chair: write about twenty
  lines, run `preflight` on the login node, submit, stop watching, read the reason it stopped. The
  narrative is mined from this deck's own campaign, so it cannot drift from the evidence — it asked
  for 3 lineages, was refused on cost, came back with 2, and nobody was woken up.
- **23 · when it says no, it says what to change.** The three places it can refuse (preflight, the
  gates and interlock, QC on the way out) — and in red the one place it does *not* refuse loudly:
  inflated cost models once let a policy hand back a graph that could no longer produce the
  objective. It warns now; a warning is not a gate.
- **24 · the live evidence from next door.** The 4 h paired comparison between the reference
  pipeline's state machine and an LLM holding the same eight tools: equal throughput, a very
  unequal funnel, and two load-bearing caveats in red. **TRANSCRIBED** — the only figures in this
  deck that are.
- **25 · what that says about these surfaces.** Four observations mapped onto the surface that
  answers each, ending in red: none of it ran through IMPRESS-A. Row 4 is a **correction**: this
  slide used to credit in-allocation serving with "$0 of API". It costs a second billed node that
  runs no pipeline, plus 27.3% of the allocation spent before the first task event — 0.243 GPU-h per
  passing fold rather than 0.121. The deck was wrong by a factor of two in its own favour.
- **26 · how an agentic run fails on a cluster, and what here would catch it.** Three runs next door
  kept as evidence rather than as measurements, each against the surface in this package that
  answers it. The honest tally is **one of three**: `preflight` covers the cheap pre-flight abort
  (`23231485`, 9 s, no run tree); gate 1 catches the lost-writes run (`23206285`) but catches it as a
  *science* failure, so the interlock then demotes a perfectly good workflow shape for a broken
  container bind — a finding, left on the slide rather than fixed; and for the silent fallback
  (`23219379`, 284 of 288 turns on the scripted route, a transcript that reads entirely healthy)
  IMPRESS-A would catch **nothing**, because the gates check artifacts and not who chose them. That
  is ask 5, rewritten. Two of its three rows carry mined anchors; the third has none in this
  checkout and says so.

Then the technical half of the act: `preflight` as the login-node contract (tri-state, and why a
timeout is never a pass); the control plane — synchronous admission (202/409), waiting as a long
poll (200/204/410), `observe()` returning the *same* object a policy sees; and the layering test as
the thing that keeps all six surfaces honest.

**Close (30-31)** — status by dimension, red column the same length as the green one; then asks,
grouped by the dimension each one damages.

## Numbers `run_model.py` must mine

Surface counts (tools registered, gates implemented, toolkits, control-plane operations, HTTP
routes), the `ALLOWED` layering table's row count, test count, and a real `impress-a run
campaigns/mock-stabilize.yaml --model D` in a temp directory for the live loop figures. Every
latency the deck prints is derived from `mock.timeline` at build time rather than typed, so a
slower host moves the number instead of making the slide wrong.

**Two transcribed sections, both under `live`, both with a `source` field.** `live.runs` is from
`examples/agentic_small_molecule_binding/CLAUDE.md`, with the job ids it names. `live.analysis` is
from the sibling analysis project `impress-agentic-performance` (`report.md` §§10-14, verified by
its `tools/verify.py`, 19 checks) and holds the four-model survey, the in-allocation cost
accounting, the packing ladder, the reference-pipeline regression series and the three failure
modes. `live.code` is mined on every build (the tools that example gives its model, its profiles,
and the methods it overrides). Slides 19, 24, 25 and 26 repeat their source in their footers;
nothing else in this deck is transcribed.

Note that two survey arms (`beam-reflection`) ran a **newer revision of the example next door** than
this checkout carries — `models.yaml` here lists 7 profiles and none of them is beam — so that arm
cites no line in this repository, and slide 19's footer says the source rather than a file.

---

## Mined, at `bf32d1d` (`run.json`)

6,621 lines of `src/` across 10 packages · 168 tests in 9 files · 20 gate fixtures, 11 of them
`.bad` · 11 tools in 5 toolkits, 4 real · 5 QC gates implemented · `CampaignSpec` 22 fields ·
`ControlPolicy` 3 methods · `Decision` 4 members · `ExperimentIntent` 6 fields ·
`CampaignSession` 10 operations · `CampaignControlPlane` 19 operations behind 15 HTTP route heads ·
`ToolSpec` 15 fields · 8 compute patterns, 2 of them used · 12 artifact types · 10 layers in the
allow-list, `core` importing none of them.

**The run:** `mock-stabilize.yaml --model D`, about 3 s (it moves with the host), 2 cycles, 3 graphs composed, 1 refused
(interlock, `transient: true`, "provisional pattern capped at 10% of available cpu_hours"),
2 admitted at 2 lineages each, 4 design nodes absorbed, all 4 `suspect`, Pareto front of 3,
14 provenance records across 5 kinds, 7 ledger records, 2 pattern signatures, 2 clean runs,
0 promotions against `promote_after = 3`.


---

## What the 2026-10-26 evidence changed, and what it did not

The sibling analysis (`impress-agentic-performance`, `report.md` §§10-14) landed after the previous
revision of this deck. It was checked against both concessions, and **neither moved**:

**Act 2 — "no serial baseline and no concurrent run" — STANDS, verbatim.** Nothing in the new
evidence is a run of IMPRESS-A. The packing ladder is five runs of the *reference* pipeline's
`adaptive_decision()` at k = 1…8; the four-model survey is the *agentic example* next door; the
in-allocation arms serve a model beside that example. IMPRESS-A still has exactly one experiment in
flight in every run it has ever performed, still has no serial run to divide by, and `replicas > 1`
has still never executed on the real six-stage chain. What the evidence *did* do is make the
concession sharper rather than softer: the two levers that move the science are now measured — ×5.52
for packing, about ×3 for the decision layer — on code that is not this engine, and this engine has
measured neither. That is slide 19, and it is the reason slide 18's red card grew a sixth bullet
rather than losing one.

**Act 3 — "the component claim is empty" — STANDS, verbatim.** Still nothing outside this package
has ever driven an IMPRESS-A campaign. The closest candidate in the new data is in-allocation vLLM
serving (`23207314`), and it is not a counterexample on two counts: it is an *endpoint the example
next door calls*, which would be the platform claim and not the component claim, and it is not
IMPRESS-A's platform — that example shares no code with this package. `RemoteSession` and the 19
control-plane operations remain tested and unused.

**Three things the evidence did change, all of them against the deck:**

1. Slide 25's in-allocation row credited "$0 of API" and was wrong by 2x in the deck's own favour.
   In-allocation serving bills a second node that runs no pipeline and spends 27.3% of a one-hour
   allocation before the first task event: 0.243 GPU-h per passing fold, not 0.121. Corrected.
2. Slide 24's two caveats both got heavier. The weak baseline is now a measured series rather than a
   suspicion (63.6% → 49.4% fastrelax, decision layer held fixed, 1.3 of 14.2 points from binder
   length), and the "unexplained fastrelax gap" is now mostly a *harness* confound rather than the
   decision layer's win — the scripted route, with no model in it, pack-minimises 48 of 48 times.
3. A new honest gap, on slide 26: of three real cluster failure modes, this package would catch one.
   The silent fallback (284 of 288 turns on a scripted route, with a healthy-looking transcript) is
   invisible to every gate here, because the gates check artifacts and not who chose them. That
   rewrote ask 5 and one cell of the status slide; it did not get written as a feature.

**Nothing in the colour palette was touched.** `impress_run_archive/ANALYSIS_BRIEF.md` §7 uses
adaptive = ochre and pass-through = blue; the sibling analysis projects deliberately use blue =
adaptive and document the divergence. Both are intentional and both are left as they are — this deck
does not plot either scheme, and the figures it transcribes are quoted as numbers, not redrawn.
