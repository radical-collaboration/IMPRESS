# IMPRESS-A — code walkthrough

**Format:** 20 minutes, code walk, technical discussion · **Audience:** the lab, including the
authors of `radical.asyncflow`, `rhapsody`, ORBIT and Flowgentic.

Because the middleware authors are in the room, this deck is weighted toward the **seam** — slides
8 and 9 — and it **ends with questions** rather than a summary. Slide 17 is six specific things we
want this room's opinion on, four of them reproducible against their code.

**Derived against `main` @ `3e64ba6`.** Companion files:

| File | Role |
|---|---|
| `build_deck.js` | the builder; every diagram is native editable shapes, never an image |
| `run_model.py` → `run.json` | every number on a slide, mined from this checkout or transcribed with its source named |
| `CODE_FOR_DECK.md` | every on-slide code block, keyed `S<slide>-<letter>`, anchored and fidelity-marked |
| `check_anchors.py` | asserts every `file:line` the deck prints still points where it claims |
| `make_script.py` → `DECK_SCRIPT.md` | the spoken script, **generated** from the deck's own `addNotes`, so it cannot drift |

**Measured: 22.0 minutes of speech** for the full path. `DECK_SCRIPT.md` carries three running
orders — full (22.0), default (18.3, dropping 6 and the 10–11 tools pair) and a hard twenty (17.4,
also dropping 15). **Pick one before you walk in** — the full path no longer fits a 20-minute slot.

---

## The one thing to be straight about

**One campaign has completed, and it is one lineage, one cycle, one draw.** Job 22692304 ran all six
stages to `6/6 tasks ok` in 2m53s with all four objectives valued. Everything else about the real
path is still untested:

- `replicas > 1` has **never executed**, so the independence invariant — N lineages must produce N
  `DesignNode`s with *different* metrics — is unexercised, and it is the invariant most likely to be
  silently wrong.
- **Nothing has ever been promoted** by the trust ledger, so the trusted code path has never run.
  Until `52332c6` it structurally could not (slide 13).
- **No measurement has ever superseded a prediction**, so the calibration machinery is untested
  against reality.
- The node that campaign produced is `suspect`, not `pass`. Say that it is the interlock working,
  not a defect, before anyone asks.

Say all of this on slide 2 and again on slide 16, and do not let slides 12 and 13 imply otherwise.
Slide 11 carries the smaller version of the same point: of the eight compute patterns, two have a
member, so three of the taxonomy's dispatch paths have never been taken by any tool.

**Second: the Delta durations on slide 12 are transcribed**, from `plans/first-real-run.md` and
`plans/backlog.md`. The raw logs live under `$WORK_DIR/impress_a_runs/<job>` on Delta, not in this
checkout. `run.json` labels them, and the slide's footer says so. Everything else on the slides —
code statistics, the mock campaign, the three pattern signatures — is computed live by
`run_model.py` against this checkout.

---

## Visual vocabulary

Carried over from the `designagent` deck so the two read as siblings:

```
line style = status      solid   built, runs end to end against something real
                         dotted  built and tested, never exercised for real
                         dashed  designed for, not implemented

orange                   a RADICAL component, wherever it appears
```

Colour roles: `reason` indigo (the policy layer) · `exec` teal (the executor and runtime) ·
`compose` green (composition, validation, the interlock) · `tool` violet (tools and task agents) ·
`radical` orange · `fail` red (findings and caveats).

---

## Coverage map

| Topic | Slide |
|---|---|
| Purpose | 1–2 |
| Why the design looks like this | **3** |
| Architecture + diagram | 4–5 |
| Data / control flow | 6 |
| Composition, validation and trust | 7, 14 |
| **The middleware seam** | **8–9** |
| Tools, QC and the compute-pattern taxonomy | 10–11 |
| What the real runs measured | 12–13 |
| How to run it, and the test tiers | 15 |
| Status and open issues | **16** |
| Discussion | **17** |
| Control plane · control models | B1 · B2 |

---

## Slides

### 1 — Title (0:00–0:45)
Motif: a reasoner feeding a gate, feeding a two-lineage graph, feeding an orange pool — the whole
talk in one strip. Carries `main @ a810d67` and the live code statistics.

### 2 — One goal, a campaign of composed experiments (0:45–1:50)
Six-step strip with the two edges that make it a loop, then two cards: what job 22692304 produced
(left, measured) and **what one completed campaign is not** (right, red). The right card is
load-bearing — put the caveats at minute two rather than letting someone find them at minute twenty.

### 3 — Two facts set the whole design (1:50–2:50)
**The slide to keep if you keep one.** A black band states both facts — a machine composes workflows
nobody reviewed, out of tools that fail silently — then five consequences, each with the file that
implements it. Closes by naming the condition under which the whole layer stops paying for itself:
*if a human reviewed every graph, you would write the DAG down once and schedule it.*

### 4 — Two coroutines, one writer (2:50–4:05) · **F1**
Two lanes with the session between them. **Never draw the policy inside the executor's frame** —
that is the old architecture and this room would catch it. The red arrow (rejection → `on_rejected`
→ retry) is the one people miss; it is bounded twice, and say why.

### 5 — Layers, and the four arrows that are not there (4:05–5:05) · **F2**
Eight bands, with the four forbidden edges drawn in red. The point to land: it is *asserted*, by an
`ast` walk, including deferred imports inside function bodies — not enforced by review.

### 6 — One experiment, and the type at every hop (5:05–6:10) *(cuttable)*
Six typed hops, then a real `--model D` run underneath: four admissions, the first refused by the
interlock, the policy shrinking and resubmitting. Recoverable in one sentence on slide 4 if cut.

### 7 — Admission: five gates, an interlock, a reservation (6:10–7:35)
The gate table, then the three things that are not gates. Two things to say: why RESERVE is last
(the dry-run awaits, so budget may have moved), and the interlock's honest limit — **examination and
delay, not soundness.** A consistent novel silent failure promotes.

### 8 — ★ One generic factory, and a submit that does not await (7:35–9:00) · `S8-A`, `S8-B`
The slide to defend hardest, and it is four lines. Never cut `_run.__name__` or the unawaited
`gather`. Close on advisory cancellation, which is **measured, not assumed**.

### 9 — ★ Building the engine on the loop that will use it (9:00–10:25) · `S9-A`
The construction half, with a column of what each lesson cost: two allocations to the loop-ownership
bug, one full two-hour allocation to Dragon's `Batch()`, and ~64 GPU-hours to a teardown that never
returned. If the room goes deep here, stay — it is the most useful thing in the deck for them.

### 10 — A tool is a spec file (10:25–11:45) *(cuttable)*
Spec, four phases, and the tool that lies. Then the honest gap: the real toolkits' gates are
thresholds on each tool's own opinion of itself, which is exactly what a confidently-wrong tool
passes.

### 11 — Eight compute patterns, and what each one forbids (11:45–13:00) *(cuttable)* · `S11-A`
The `pattern:` field from the previous slide, opened up. The table is the argument: the taxonomy is
organised by **what the orchestrator must do differently**, not by what the tool computes — a tool is
P4 for where it must be submitted. P6 is the one to land, because it is the only pattern that forbids
scheduling outright: the composer drops P6 stages before they become nodes and gate 4 refuses one
that got through, so a scheduled P6 is a composer bug caught as one.

Two honest halves, both mined by `run_model.py`'s pattern census. The last column is the census: all
eleven tools are P1 or P2, so the P6-inline, P4-ledger and P5-service paths are contracts the suite
asserts and nothing has taken. And the enum's own docstring says dispatch depends on these — it does
not yet, because all five consulting sites are in `compose/` and `tools/`, none in `exec/` or
`runtime/`. **Say that the docstring is ahead of the code; do not fix it in the room.**

Cut it with 10 if the clock is tight — the `pattern:` line on slide 10 recovers it in one sentence.

### 12 — Four jobs to one completed campaign (13:00–14:15) · **F3**
Stacked bars on a shared axis. The figure is about **one variable** — HDD versus NVMe. Land the
near-miss: the queued fix was to raise three walltimes six-fold, which would have hidden a 471-second
import behind a timeout.

### 13 — Four defects that reached real hardware (14:15–15:35)
Each invisible to a dry run. Ends on the two sentences worth carrying away: *"checked against the
binary" is not "executed"*, and *a plausible explanation is not a diagnosis*.

### 14 — The ledger that forgot, and what it still forgets (15:35–17:15)
Two findings. The first (A12) is a path bug whose interest is **how it hid** — a ledger that silently
reset looks identical to one that has not earned promotion yet. The second was found while building
this deck: the pattern signature includes replica multiplicity, so promoting a `replicas: 1` campaign
does nothing for `replicas: 4`. Pose the second as an open question, not a fix — **no code was
changed for it.**

### 15 — Running it, and what the test tiers cover (17:15–18:05) *(cut in order C)*
Commands and the test-file table. The split that matters: the whole local tier runs on a laptop with
no allocation, and the corollary is that everything only verifiable on HPC is unverified.

### 16 — What is real, and what is not (18:05–19:05)
Two columns, seven rows each. **Do not compress this slide.** An audience that catches you
overclaiming stops believing everything else, and this deck's credibility rests on the caveats being
volunteered rather than extracted.

### 17 — Six things I would like this room's opinion on (19:05–20:25)
Dark slide, six boxed questions. Four for the middleware authors, one for everyone (the signature
question from slide 14), one for the domain people (which structural gate to build first). End
there; the questions are the ending.

### B1 — The control plane and the out-of-process reasoner *(backup)*
One protocol, two shipped transports, synchronous admission and why it cannot be deferred. Then the
gap: no `serve`, no `reason`, so `--model C` fails open and reports a model-D campaign as model C.

### B2 — Four control models over one executor *(backup)*
The A/B/C/D table, decorators rather than subclasses, and the claim everything rests on: below the
policy layer all four are byte-identical. Includes the editorial note on why the outer loop is still
ours, with credit to Flowgentic's own README for reaching the same conclusion.

---

## Delivery notes

- **Open two terminals.** One in the repo root for `pytest` and `grep`, one for a campaign. Every
  anchor on a slide is greppable live, and this audience may ask you to.
- **Have `run.json` open.** Every number is in it, and "let me show you where that came from" is a
  stronger answer than repeating the number.
- **If the room goes deep on the engine or the backend**, stay on 9 and go to B1 if they ask about
  the process split. That is what they came for.
- **If someone asks why the outer loop is not a framework's**, go to B2. Do not relitigate it on the
  clock — Flowgentic's README agrees with us, and saying so with credit ends the exchange well.
- **If someone proposes fixing the signature on the spot** (slide 14), resist deciding in the room.
  The trust campaign is written and ready to submit; changing pattern identity first would
  invalidate it.
- **Demo, if wanted:** `pytest tests -q -k lying` is 20 seconds and shows a tool that succeeds,
  reports 0.91 designability, and is failed by QC anyway.

---

## Before presenting

```sh
python3 slides/run_model.py          # regenerate run.json from this checkout
python3 slides/check_anchors.py      # 44/44 — do not present a drifted anchor
python3 slides/make_script.py        # regenerate DECK_SCRIPT.md from the deck's notes
NODE_PATH=<dir with pptxgenjs> node slides/build_deck.js
pytest tests -q                      # the deck must not have touched the code
```

`build_deck.js` warns at build time if any code block would have to be set below 8.5pt to fit. That
warning is the one build failure this deck cannot ship with — an overflowing code block on a
projector is unreadable from the third row.
