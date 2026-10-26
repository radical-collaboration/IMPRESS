# IMPRESS-A — the API and the campaign loop

**Format:** three acts, four running orders — the full path runs ~39 min of speech, and **D · for
users** is a 19-minute path that keeps the experiential slides and drops the protocols ·
**Audience:** the lab, plus anyone who has to write against this (a policy author, a toolkit
author, something driving a campaign from outside the allocation) — and, on order D, anyone who
only has to *run* it.

**This is not the comparison deck.** `../build_deck.js` is the argument against the reference
IMPRESS pipeline and it stays as it is; it carries its own `run.json` and its own derivation. This deck answers a
different question: *what are the surfaces, and what does the loop do between them?* Where the two
overlap (dispatch seam, gates), this one cites and does not re-argue.

**Derived against `examples/agentic-small-molecule-binding` @ `b5a3b2d`.** `agent/` has not changed since `c163fe2`; the branch has, which is
where the live evidence on slides 23-24 comes from. Companion files in this directory, same roles as
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
| 2 · Performance | What does the loop cost, and where does it serialise? | one `conduct` reasoner submitting many experiments; `as_completed` in finish order; the executor as sole writer of campaign state; a ~3 s mock campaign that refuses a graph and shrinks it | **no serial baseline and no concurrent run**: every mock run here is one experiment in flight, and on the real chain `replicas > 1` has never executed (backlog A10) |
| 3 · Usability | Application, platform, or component? | one YAML + one command; runtime-discovered toolkits; the same protocol in two transports; and four user-directed slides, including the live 4 h run next door | **the component claim is empty** — nothing external has ever driven a campaign; `RemoteSession` is tested, not used; and the live run is somebody else's code |

**Say the weak dimension out loud in the first three minutes.** It is usability-as-a-component: the
control plane and `RemoteSession` are the most carefully designed surfaces here and the least
exercised. Nothing outside this package has ever driven a campaign.

**And say what the live slides are not.** Slides 23-24 show an LLM driving the *reference* IMPRESS
pipeline's toolkit for four hours on Delta — the closest thing in this repository to what this
engine is for, and it is not this engine: different code, no campaign engine, no gates, no
interlock, no trust. It is evidence that the idea pays on this hardware. It is not evidence that
this implementation does. Its own caveats travel with it: the reference arm came in about 2x worse
than its own record, so the 3.3x is an upper bound nobody should quote, and the `fastrelax` gap it
turns on is unexplained.

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

**Act 2 · Performance (15-19)** — `CampaignSession` as the inversion: the loop used to call the
reasoner, now the reasoner calls the campaign. Two-lane coroutine diagram: `pump` vs `conduct`,
whichever finishes first ends the campaign. Then the mined run, in full: three graphs composed, one
refused at the interlock as `transient`, two admitted at width 2, four nodes absorbed, all four
`suspect`, front of 3, in about 3 s. Then measured-and-not-measured. Then the interlock as the one place
the API *refuses* breadth — and `pattern_signature` as shape-only-but-not-quite: it excludes
parameter values deliberately and includes replica multiplicity by accident, so the width-3 graph
and the width-2 graph are two patterns (mined: two signatures, two cleans, `promote_after = 3`,
nothing promoted).

**Act 3 · Usability (20-27)** — the act opens **user-directed**, with four slides that carry no
protocol and almost no code:

- **21 · what running one is actually like.** Five steps from the user's chair: write about twenty
  lines, run `preflight` on the login node, submit, stop watching, read the reason it stopped. The
  narrative is mined from this deck's own campaign, so it cannot drift from the evidence — it asked
  for 3 lineages, was refused on cost, came back with 2, and nobody was woken up.
- **22 · when it says no, it says what to change.** The three places it can refuse (preflight, the
  gates and interlock, QC on the way out) — and in red the one place it does *not* refuse loudly:
  inflated cost models once let a policy hand back a graph that could no longer produce the
  objective. It warns now; a warning is not a gate.
- **23 · the live evidence from next door.** The 4 h paired comparison between the reference
  pipeline's state machine and an LLM holding the same eight tools: equal throughput, a very
  unequal funnel, and two load-bearing caveats in red. **TRANSCRIBED** — the only figures in this
  deck that are.
- **24 · what that says about these surfaces.** Four observations mapped onto the surface that
  answers each, ending in red: none of it ran through IMPRESS-A.

Then the technical half of the act: `preflight` as the login-node contract (tri-state, and why a
timeout is never a pass); the control plane — synchronous admission (202/409), waiting as a long
poll (200/204/410), `observe()` returning the *same* object a policy sees; and the layering test as
the thing that keeps all six surfaces honest.

**Close (28-29)** — status by dimension, red column the same length as the green one; then asks,
grouped by the dimension each one damages.

## Numbers `run_model.py` must mine

Surface counts (tools registered, gates implemented, toolkits, control-plane operations, HTTP
routes), the `ALLOWED` layering table's row count, test count, and a real `impress-a run
campaigns/mock-stabilize.yaml --model D` in a temp directory for the live loop figures. Every
latency the deck prints is derived from `mock.timeline` at build time rather than typed, so a
slower host moves the number instead of making the slide wrong.

**The one transcribed section is `live.runs`**, from
`examples/agentic_small_molecule_binding/CLAUDE.md`, with the job ids it names. Its `live.code`
half is mined on every build (the tools that example gives its model, its profiles, and the methods
it overrides). Slides 23 and 24 repeat the source in their footers; nothing else in this deck is
transcribed.

---

## Mined, at `b5a3b2d` (`run.json`)

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
