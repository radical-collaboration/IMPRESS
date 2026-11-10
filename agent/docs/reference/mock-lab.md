# The mock knob lab

**A measuring harness, not a result.** It runs the laptop surrogate of the small-molecule
binding chain across a grid of knob settings, flattens what the executor wrote into four
CSVs, and draws six figures from them. The whole thing finishes in about half a minute on a
laptop and needs no allocation.

Read `campaigns/README.md` first for what the surrogate campaign is and what each knob does.
This page is about the harness around it: what it runs, what it measures, and which of its
numbers mean anything.

## What a figure from here is allowed to claim

Every metric the six surrogates report is a **seeded random draw**
(`toolkits/mock/SKILL.md`). A response surface drawn here is a statement about the
surrogate's own arithmetic. It is not evidence about any molecule, and the disclaimer is
printed on every figure from `analysis/mock_lab.DISCLAIMER` rather than typed into a caption
a reader could drop when they paste the PNG into a slide.

What *is* measured honestly is the campaign's **behaviour** — how many cycles it took, which
gate refused what, whether the Pareto front filled, how long the control plane spent
deciding — because that is the same executor, the same composer, the same five gates and the
same interlock the Delta arms run. A behaviour observed here is the behaviour the real
campaign would show; a number observed here is not a measurement.

## Running it

```bash
impress-a mock-lab                                   # sweep, collect, figures
impress-a mock-lab --only arms --stage sweep         # the four arms, nothing else
impress-a mock-lab --stage figures                   # redraw from the tables already there
impress-a mock-lab --repeats 6 --jobs 8              # a tighter band, same wall clock
```

Figures need the optional extra: `pip install -e ".[figures]"`. The sweep and collect stages
do not — they write CSVs with the standard library, so a machine with no plotting stack can
still produce the tables.

Output lands in `campaigns/_runs/_analysis` by default, which is gitignored:

```
manifest.json          every cell, its knob setting, its exit code, its run directory
specs/<cell>.yaml      the campaign that cell actually ran
runs/<cell>/           that campaign's own run root - provenance, ledger, trust
logs/<cell>.log        its stdout and stderr tail
tables/*.csv           lineages, tasks, cycles, campaigns, phases
figures/*.png          the six figures
```

## The two kinds of cell

**Four arms**, which are the settings the ten-minute activity walks through and the four hues
in `analysis/plot_style.py`. Each is one reproducible campaign a person can re-run by hand
and get back:

| Arm | Setting | What the campaign does |
|---|---|---|
| `baseline` | shipped defaults | clears every bar; the Spec is satisfied; the front fills |
| `rescued` | `difficulty: 0.55`, plus `diffusion_steps: 200`, `packmin.cycles: 5`, `diffusion_samples: 25` | the same difficulty, bought back by three knobs |
| `hard` | `difficulty: 0.55` | acceptance shortfall; the front stays empty; trust untouched |
| `hopeless` | `difficulty: 0.85` | integrity failure; `CampaignAborted` after three all-failed runs |

**Sweep cells**, one campaign per knob value per repeat, each repeat under a different seed
salt. These carry the ensembles: 8 lineages a cell times 3 repeats is 24 independent draws
per point at the default settings.

Two deliberate differences from the shipped campaign, applied to every cell equally:

* `replicas: 4` (arms) or `8` (sweeps), because one lineage per cycle is not a distribution.
  This changes the pattern signature, so every cell runs **untrusted** under the interlock's
  10% cost cap — the same interlock for all of them.
* A sweep cell runs exactly **one cycle**. `ThresholdSpecifier.revise` adds a refinement
  objective as soon as the front is non-empty, so a multi-cycle cell mixes the knob's
  response with the planner's escalation away from it, and a sweep that cannot separate those
  is not a response surface.

## Isolation, and why it is not tidiness

Each cell runs as a subprocess of `impress-a run` with its own `IMPRESS_A_RUN_ROOT`,
`IMPRESS_A_TRUST_DIR` and `IMPRESS_A_SEED_SALT`.

The trust directory is the one that bites. The trust ledger is **cross-run state**: a cell
that promoted a pattern changes the interlock every later cell runs under, so a shared ledger
makes the sweep a function of its own iteration order rather than of the knob. The salt is
what makes `--repeat` draw different lineages instead of the same ones again (backlog G7).

**The four arms always run one at a time**, whatever `--jobs` says, because every wall-clock
figure comes from them. Run eight-wide, one arm's first cycle came back at 0.10s against
1.10s for the other three — scheduling noise presented as a property of the knob setting.
Sweep cells are read only for the metrics their tools drew, which CPU contention cannot
change, so they run in parallel.

## The reasoner axis

The six surrogates mock the **tools**. `--reasoners` mocks nothing: it varies the control
model *above* them, so the four knob arms run under each named reasoner and the lab measures
the half the four-model taxonomy is actually about.

```bash
impress-a mock-lab --reasoners D --reasoners null                    # offline, free
impress-a mock-lab --reasoners D --reasoners B --model-profile beam  # live
```

| letter | what drives the campaign | needs a profile | repeated |
|---|---|---|---|
| `D` | `ThresholdSpecifier` + `ThresholdPlanner`; rules end to end | no | no |
| `null` | an empty Spec, so the campaign stops at cycle 0 | no | no |
| `A` | the four-node graph; two nodes call the model (`hypothesize`, `select_tasks`) | **yes** | `--reasoner-repeats`, default 3 |
| `B` | two schemas, one call each (`SPEC_SCHEMA`, `STAGE_SCHEMA`) | **yes** | `--reasoner-repeats` |

`C` is absent: it needs `impress-a serve` plus an `impress-a control` sidecar waiting on the
0600 `control_plane.url`, which is two processes per cell, and its caller-side reasoner
records have nowhere to land (backlog H8).

Sweeps stay on `D` whatever the axis says. They measure the surrogate's own response surface,
which no reasoner changes, so running them under four models buys four readings of one piece
of arithmetic.

### Three rules the live path enforces

**A live model with no profile is refused, not quietly run.** `--model A` without one runs its
rule cascades and `--model B` runs `RehearsalOracle`. Both report zero LLM calls — which is
exactly what a *degraded* live arm reports. A figure labelled "model B" drawn from the
rehearsal is the pre-registration's §8 void outcome manufactured on purpose, so the lab exits
2 and names the models it refused, before spending anything.

**One probe call before any live cell.** `cli._client_for` opens no socket, so without this the
first failure lands inside a campaign cycle, where `reasoning.ask` retries twice, writes
`reasoner_degraded` and runs model D's cascade — and the campaign exits 0. Every live cell
would do the same and the lab would draw a full set of figures for a model that never
answered. One round trip up front is the difference between "the endpoint is down" and
twenty-four quietly degraded arms.

**A cap on what it may spend.** `--max-llm-calls` (default 400), counted from what each cell
actually recorded rather than estimated — a corrective retry is a second call and a degraded
node is two calls that bought nothing. A cell the cap stopped is named in the manifest and
carries a `skipped` reason, because one silently missing from a figure reads as a model that
had nothing to show.

### What the lab reads about a reasoner

Nothing recorded a control model's behaviour until `890829d`: `ReasonerOptions.sink` had
writers throughout `policy/` and no subscriber, so a campaign left no prompt, no reply, no
model id, no timing and no degraded event. Two of the collected tables exist because of that
fix.

* **`decisions.csv`** — one row per LLM call: `node`, `attempt`, whether it was accepted,
  the `model_id` that answered, `elapsed_s`, and prompt/completion tokens as deltas. The
  prompt and reply bodies stay in `decisions.jsonl`; a CSV is for counting.
* **`params.csv`** — the parameter vector each Planner chose, from `stages.jsonl`'s
  `mappings`. `source` separates `campaign` from `reasoner`, because `mappings` holds the
  *effective* vector and `_apply_campaign_defaults` merges the campaign's `params:` into it
  before composition. Without the split every model would read as having set every knob.
* **`campaigns.csv`** gains `llm_calls`, `llm_retries`, `llm_s`, `llm_share`, token totals,
  `s_per_llm_call`, `degraded_events`, and `model_id` — read from the records rather than
  from the flag the lab passed, so a cell that asked for `beam` and was answered by something
  else shows it.

**Check `degraded_events` before reading any live arm's yield.** A non-zero count means the
arm fell back to model D's cascade, and what it produced is not that model's result. That is
the pre-registration's void rule, enforceable for the first time now that anything writes
these events.

### What the first live run found

`Beam-501B-A23B` via profile `beam`, four arms under model B, 2026-11-10. Twenty calls, zero
retries, zero degraded turns, and no allocation.

| | model D | model B (live) |
|---|---|---|
| seconds per decision | 0.35 | **19.96** |
| completion tokens per call | — | 1148 |
| share of campaign wall clock spent at the endpoint | — | **94–99%** |
| parameters it moved | 3, all quality | 9, including every breadth knob |

Two things worth carrying off the laptop. **The endpoint is the campaign** on this tier: the
six tools return in milliseconds and 94–99% of each live cell's wall clock was one model
thinking. And **model B raises breadth parameters that models A and D are forbidden to touch**
— `num_designs` to 2, 3, 4 and 8 — because `OraclePlanner._prompt` filters what it shows by
`tunable`, which does not look at kind. `rfd3_design`'s own spec records that `num_designs`
stays at 1 because its adapter keeps index 0, and its `cost_model` is per *invocation*, so
nothing prices the extra draws either. Backlog **H10**.

### `difficulty` is `operator_only`

`OraclePlanner` shows a live model every tunable parameter with its range and its `trades`
sentence, and `_apply_campaign_defaults` states that a policy wins on any key it set. The
dial reads "how hard this campaign is", 0.0 to 1.0. A model asked to satisfy the objectives
turns it down, the `hard` arm quietly becomes the easy one, and nothing says so.

So it is marked `operator_only` in `mock_rfd3_design/spec.yaml`: the campaign may declare it,
a reasoner may not propose it. Enforced in one seam, `tools/view.card_for`, which reports it
under `TaskCard.frozen` and leaves it out of `TaskCard.parameters` — `_knobs.tunable` skips
it, B's prompt omits it, and B's schema check refuses a reply naming it with the reason the
spec gave. Gate 3 reads `ToolSpec.frozen_parameters`, which stays empty, so the campaign path
is untouched and no seeded draw moves.

Checked rather than assumed: `campaigns.csv` carries `difficulty_proposed`, which is empty
unless a reasoner's value reached a deployed stage or a rejection named the dial as frozen,
and `f9-knobs-moved.png` asserts that it appears for nobody.

## The tables

| File | One row per | Carries |
|---|---|---|
| `lineages.csv` | `DesignNode` | the whole chain's metrics merged, the QC verdict, and the failed gates split into `failed_integrity` / `failed_acceptance` |
| `tasks.csv` | task | its `stage_index` in the chain, verdict, gates, timing, both sides of its cost, and every metric it reported prefixed `m_` |
| `cycles.csv` | composed graph | signature, whether it was trusted, the interlock's scrutiny, the estimate, and the gate that refused it if one did |
| `campaigns.csv` | cell | stop reason, whether it aborted, cycles, front size, verdict counts, wall clock, busy time, overhead, decisions and tasks per second |
| `phases.csv` | cycle | where that cycle's wall clock went, segment by segment |

Two things in there are easy to get subtly wrong, so they are done once and tested:

* **Busy time is a union of intervals, not a sum of durations.** `workers: 4` overlaps
  tasks, so a sum double-counts; and `wall - sum` can go negative and then reads as negative
  overhead. The union is correct at any concurrency.
* **A metric a tool did not report is `None`, never `0.0`.** A tool omits a metric it could
  not read (the `metrics_reported` invariant), and fabricating a zero turns "the tool broke"
  into "the design is weak".

## The figures

| File | Shows |
|---|---|
| `f1-metric-ensembles.png` | each campaign objective against `difficulty`, mean ± 2σ population spread, with its acceptance bar and the arms marked |
| `f2-knob-response.png` | `complex_plddt` against the four knobs that have a real counterpart, on one shared y-axis so the spans are comparable |
| `f3-stage-funnel.png` | per-stage pass rate per arm, and the failures split into acceptance shortfalls and integrity failures |
| `f4-decision-rate.png` | elapsed seconds against decision index — slope is seconds per decision — and decisions/s against tasks/s |
| `f5-control-time.png` | where a cycle's wall clock goes, cycle 0 against every cycle after it |
| `f6-stop-vs-front.png` | what each arm's campaign *said* against what it actually had on the front |
| `f7-reasoner-yield.png` | front size per arm per control model — does a reasoner rescue a campaign the rules cannot? |
| `f8-decision-cost.png` | what one decision costs in seconds and in tokens, by who made it |
| `f9-knobs-moved.png` | which knobs each model moved, and how far up their declared ranges |

**The control model does not get a hue.** The four validated colours are spent on the four
knob arms and colour follows the entity, so in f7–f9 a model takes the *fill* channel —
hatch and face alpha inside the arm's own colour (`plot_style.MODEL_FILLS`). It survives
every CVD simulation by construction, reads in greyscale, and the arm identity a reader
learned in f1–f6 carries straight across.

Colour follows `analysis/plot_style.py` and means the same thing in all nine: blue is the
best-performing configuration, magenta is the run that did not complete, and a sweep line is
drawn in the **neutral** grey because a sweep is a measure rather than one of the compared
entities. Bands are `± 2σ` **population spread over lineages**, never a standard error — at
24 lineages the two differ by about five times, and a band read as a confidence interval
makes adjacent knob settings look separated when they are not.

## Three things the lab found

Worth knowing before you read its output, because two of them are defects in the system it
measures rather than in the surrogate.

1. **`hard` stops on "every spec objective satisfied" with an empty Pareto front.** Not a
   bug in the lab. `DataRegistry.ingest` records a task's metrics whatever the QC verdict and
   `SatisfactionRule` counts those readings, while `core/pareto` correctly refuses a FAIL node
   a place on the front. `f6-stop-vs-front.png` exists to make that gap unmissable. Backlog
   **G14**.
2. **An aborted campaign's provenance says `reason: completed`.** `hopeless` raises
   `CampaignAborted` and the only durable trace of why is the process's stderr, so
   `collect` derives `aborted` from the exit code instead. Backlog **G15**.
3. **About one first cycle in eight stalls for an extra ~1.0s** inside asyncflow's
   run-component loop, which waits on its component-change event with a 1.0s timeout.
   Irrelevant on hardware, 90% of the first cycle here, and the reason every wall-clock
   caption says so. Backlog **G16**.

## Extending it

Add a knob to `SWEEPS` in `analysis/mock_lab.py` — the tool, the parameter and the values —
and it sweeps. Add an arm to `ARMS` and it must also get a hue in `plot_style.RUN_STYLES`;
`style_for` raises on an unknown arm rather than inventing one, because a silent fifth hue
would break the colour identity every figure in a report depends on. A fifth categorical
colour has to be re-validated first — see the `campaign-plot-style` skill's
`references/palette.md`.
