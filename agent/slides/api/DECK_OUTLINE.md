# IMPRESS-A — the API and the campaign loop

**Format:** three acts, target ~20 min of speech (≈2,500 words) · **Audience:** the lab, plus
anyone who has to write against this — a policy author, a toolkit author, or something driving a
campaign from outside the allocation.

**This is not the comparison deck.** `../build_deck.js` is the argument against the reference
IMPRESS pipeline, derived against `main` @ `ffac4b0`, and it stays as it is. This deck answers a
different question: *what are the surfaces, and what does the loop do between them?* Where the two
overlap (dispatch seam, gates), this one cites and does not re-argue.

**Derived against `merge-impress-a` @ `c163fe2`.** Companion files in this directory, same roles as
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
| 2 · Performance | What does the loop cost, and where does it serialise? | one `conduct` reasoner submitting many experiments; `as_completed` in finish order; the executor as sole writer of campaign state; a 2.9 s mock campaign that refuses a graph and shrinks it | **no serial baseline and no concurrent run**: every mock run here is one experiment in flight, and on the real chain `replicas > 1` has never executed (backlog A10) |
| 3 · Usability | Application, platform, or component? | one YAML + one command; runtime-discovered toolkits; the same protocol in two transports | **the component claim is empty** — nothing external has ever driven a campaign; `RemoteSession` is tested, not used |

**Say the weak dimension out loud in the first three minutes.** It is usability-as-a-component: the
control plane and `RemoteSession` are the most carefully designed surfaces here and the least
exercised. Nothing outside this package has ever driven a campaign.

**One claim to state precisely rather than loosely.** `replicas > 1` *does* execute — the mock
campaign mined for this deck composed three lineages, had them refused at the interlock's cost cap,
and ran two. What has never executed is `replicas > 1` on the **real** six-stage chain, which is
backlog A10, and the slide that shows the refusal says so on the slide.

## Per-slide intent (draft)

**Framing (1-5)** — title with the commit; what this is not (one chain, one node, no external
driver); the six-surface table above; the loop as one line: `observe → DECIDE → compose → validate
→ execute → analyze → update → terminate?`; and the point that the reasoner is *not* the loop body.

**Act 1 · Functionality (6-12)** — the YAML as the scientific question (`stages`, `params`,
`objectives`, `replicas`) next to the `ExperimentIntent` a policy emits, to make the point that a
policy never names a tool parameter. Then `Decision` as four cases. Then `ToolSpec` — typed ports
over `ArtifactType`, `Pattern` as *scheduling* implication, `frozen_parameters`, and the
load-is-validating rule (default outside its own range is a load-time error; a toolkit is disabled
whole). Then `TaskAgent`'s four phases with `execute()` deliberately not overridable. Close on the
five gates + dry-run, and `ValidationFailure.transient` — the field that stops a policy answering
contention by mutilating its own intent.

**Act 2 · Performance (13-17)** — `CampaignSession` as the inversion: the loop used to call the
reasoner, now the reasoner calls the campaign. Two-lane coroutine diagram: `pump` vs `conduct`,
whichever finishes first ends the campaign. Then the mined run, in full: three graphs composed, one
refused at the interlock as `transient`, two admitted at width 2, four nodes absorbed, all four
`suspect`, front of 3, in 2.9 s. Then measured-and-not-measured. Then the interlock as the one place
the API *refuses* breadth — and `pattern_signature` as shape-only-but-not-quite: it excludes
parameter values deliberately and includes replica multiplicity by accident, so the width-3 graph
and the width-2 graph are two patterns (mined: two signatures, two cleans, `promote_after = 3`,
nothing promoted).

**Act 3 · Usability (18-21)** — one YAML, one command, `preflight` as the login-node contract
(tri-state, and why a timeout is never a pass). Then the control plane: synchronous admission
(202/409), waiting as a long poll (200/204/410), and `observe()` returning the *same* object a
policy sees. Then the layering test as the thing that keeps all six surfaces honest.

**Close (22-23)** — status by dimension, red column the same length as the green one; then asks,
grouped by the dimension each one damages.

## Numbers `run_model.py` must mine

Surface counts (tools registered, gates implemented, toolkits, control-plane operations, HTTP
routes), the `ALLOWED` layering table's row count, test count, and a real `impress-a run
campaigns/mock-stabilize.yaml --model D` in a temp directory for the live loop figures. Anything
from a Delta archive goes in the transcribed section with its job id, and the slide repeats it.

---

## Mined, at `c163fe2` (`run.json`)

6,621 lines of `src/` across 10 packages · 168 tests in 9 files · 20 gate fixtures, 11 of them
`.bad` · 11 tools in 5 toolkits, 4 real · 5 QC gates implemented · `CampaignSpec` 22 fields ·
`ControlPolicy` 3 methods · `Decision` 4 members · `ExperimentIntent` 6 fields ·
`CampaignSession` 10 operations · `CampaignControlPlane` 19 operations behind 15 HTTP route heads ·
`ToolSpec` 15 fields · 8 compute patterns, 2 of them used · 12 artifact types · 10 layers in the
allow-list, `core` importing none of them.

**The run:** `mock-stabilize.yaml --model D`, 2.9 s, 2 cycles, 3 graphs composed, 1 refused
(interlock, `transient: true`, "provisional pattern capped at 10% of available cpu_hours"),
2 admitted at 2 lineages each, 4 design nodes absorbed, all 4 `suspect`, Pareto front of 3,
14 provenance records across 5 kinds, 7 ledger records, 2 pattern signatures, 2 clean runs,
0 promotions against `promote_after = 3`.
