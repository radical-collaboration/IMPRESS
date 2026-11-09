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

Colour follows `analysis/plot_style.py` and means the same thing in all six: blue is the
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
