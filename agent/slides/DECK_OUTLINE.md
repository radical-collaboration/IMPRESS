# IMPRESS-A — code walkthrough

**Format:** three acts, ~29 min of speech on the full path · **Audience:** the lab, including the
authors of the reference IMPRESS pipeline, `radical.asyncflow`, `rhapsody`, ORBIT and Flowgentic.

**The baseline is IMPRESS, not nothing.** The previous version of this deck explained what IMPRESS-A
is and does against no alternative, which is the wrong comparison for this room: an adaptive
pipeline that works already exists next door, at a scale this project has not touched. Every claim
here is therefore framed as *what composing a graph buys over writing one down* — and the slides
say, in red, where that buys nothing yet.

**Derived against `main` @ `ffac4b0`.** Companion files:

| File | Role |
|---|---|
| `build_deck.js` | the deck. Shared machinery comes from the code-walk-deck skill's `deck_lib.js`; every diagram is native editable shapes, never an image |
| `deck.json` | title, the three acts, the running orders, what to protect and what to say out loud — read by `make_script.py` |
| `run_model.py` → `run.json` | every number on a slide: mined from this checkout, mined from the reference checkout, or transcribed with its source named |
| `anchors.json` | every `file:line` the deck prints, including the five into the reference pipeline |
| `CODE_FOR_DECK.md` | every on-slide code block, keyed `S<slide>-<letter>`, anchored and fidelity-marked |
| `DECK_SCRIPT.md` | the spoken script, **generated** from the deck's own `addNotes`, with measured timings |

**Timings live in `DECK_SCRIPT.md`**, measured by `make_script.py` and never restated here. Three
orders: the full path, a default that fits 30 minutes, and a hard twenty. **Pick one before you
walk in.**

---

## The three dimensions, and the weak one

Slide 4 states this and the dividers repeat it per act.

| Act | The question | The evidence | What it concedes |
|---|---|---|---|
| 1 · Functionality | What can you ask for that an adaptive pipeline cannot be asked? | composition per cycle, typed and gated; a tool as a spec file; four control models over one executor | every graph composed so far is the six-stage shape the reference pipeline already had |
| 2 · Performance | What does composing, validating and scoring a graph cost? | overhead 2.8 s of a ~160 s run, scrutiny 0.0 s [−0.9, 1.2]; both ends of the backend lifecycle bounded; tasks 95% of elapsed | no serial baseline, no head-to-head, one lineage on one of four GPUs |
| 3 · Usability | Application, platform, or component? | one YAML and one command; runtime-discovered toolkits and a control plane in two transports | the component claim is empty, and `--model C` fails open |

**Say the weak dimension out loud in the first three minutes.** It is performance at scale, and the
reason is `replicas > 1`.

---

## The one thing to be straight about

**Sixteen complete six-stage runs, every one of them a single lineage on one of four GPUs.** Job
22692304 ran all six stages to `6/6 tasks ok` in 2m53s with all four objectives valued, and
22728140's pattern then held trust for three consecutive cycles. What that does *not* cover:

- `replicas > 1` has **never executed**, so the independence invariant is unexercised — and its
  cheap route is dead: the pattern signature includes replica multiplicity, so trust earned at
  width 1 does not transfer (slide 18, backlog A10).
- **No node has ever reached plain `pass`**, at a ~31% acceptance rate over sixteen runs. More
  draws, not code.
- **No measurement has ever superseded a prediction**, so the calibration machinery — the one
  capability a composed graph has that a written-down one does not — is untested.
- Trust rests on the **integrity** gates alone (decision 0013), and they are thin. A tool emitting
  well-formed, low-scored garbage can promote. Backlog B1, and ask 6.

## And the three rules that keep the comparison fair

The reference pipeline's authors are in the room and can check every one of these.

1. **Credit first, on slide 3 and again on 15.** That pipeline has run real multi-node campaigns and
   paid for a list of lessons we inherited none of — including the `$WORK_DIR`/NVMe fix ported out
   of its PR #67.
2. **No throughput claim, ever.** Their figures are A40, 1–8 nodes, 8–256 pipelines; ours are one
   node of `gpuA100x4-interactive` running one serial chain. State both denominators; divide
   nothing. There is no head-to-head and the deck says so twice.
3. **Do not claim "we catch silent failure and they do not."** On the two Rosetta stages we share,
   *their* thresholds are stricter — `total_score < -250`, `fa_rep < 100`, an `interaction_energy`
   we never compute, against our `≤ 0.0` and `≤ 500.0` and nothing (backlog G4/G5). Slide 10 prints
   both columns, mined from both checkouts. The defensible claim is about **where the verdict lives
   and whether it can be omitted**, not about strictness.

Two more that are easy to trip over: **P7, the pattern reserved for running an IMPRESS pipeline as
one of our tools, has no member** — it is a contract, not a result (backup B2); and the interlock
**buys examination and delay, not soundness** — a consistent novel silent failure promotes.

---

## Visual vocabulary

```
line style = status      solid   built, runs end to end against something real
                         dotted  built and tested, never exercised for real
                         dashed  designed for, not implemented

orange                   a RADICAL component, wherever it appears
brown/tan                the reference IMPRESS pipeline, wherever it appears
```

Colour roles: `reason` indigo (the policy layer) · `exec` teal (the executor and runtime) ·
`compose` green (composition, validation, the interlock) · `tool` violet (tools and task agents) ·
`radical` orange · `base` tan (the baseline) · `fail` red (findings and caveats).

---

## Slides

### Front matter — 1 to 5

**1 — Title.** The thesis is stated against the baseline: *composing the pipeline instead of writing
it down*. Carries the head commit and the live code statistics.

**2 — One goal, a campaign of composed experiments.** Six-step strip with the two edges that make it
a loop, then the measured card and, in red, what one completed campaign is not — now phrased in
baseline terms.

**3 — The baseline is not a blank page.** ★ The slide that makes the deck an argument rather than a
tour. Three bands: what IMPRESS already does (measured, from its own report); what it costs to
change it (mined from its checkout — 19 `next_step` assignments in one decision function,
thresholds in a `PROD` dataclass, the verdict computed inside the parsing coroutine, the hook a
plain closure); and the two measured facts that argue for composing (guided feedback is flat
against its own parent, ΔpLDDT +0.011 at p = 0.85; 804 folds are 596 clusters). Ends on the credit
line, and it is owed.

**4 — Three dimensions, and the one I have least evidence for.** The framing slide. Name performance
at scale as the weak column here, at minute three.

**5 — Two facts set the whole design.** The constraint slide. The closing inverse now names what it
is the inverse *of*: writing the DAG down is the right answer under review, and next door it is
1,450 lines of pipeline class per use case.

### Act 1 · Functionality — 6 to 10

**6 — divider.** **7 — Two coroutines, one writer** (F1; never draw the policy inside the executor's
frame). **8 — Layers, and the four arrows that are not there** (F2; the point is that it is
*asserted*, by an `ast` walk). **9 — Admission: five gates, an interlock, a reservation** (why
RESERVE is last; and the interlock's honest limit). **10 — A tool is a spec file, and QC is part of
the spec** — carries the where-the-verdict-lives table and the admission that their thresholds are
stricter than ours.

### Act 2 · Performance — 11 to 18

**11 — divider.** **12 — ★ One generic factory, and a submit that does not await** (never cut
`_run.__name__` or the unawaited `gather`; close on advisory cancellation, measured not assumed).
**13 — ★ Building the engine on the loop that will use it** (with what each lesson cost: two
allocations, one two-hour allocation, ~64 GPU-h). **14 — What the loop costs, and what is not
measured** — the measured-and-not-measured ledger; the red card is written as refusals, not
apologies. **15 — Seven jobs: what storage bought, and what trust cost** (F3; one variable, and the
near-miss where the queued fix would have hidden a 471-second import behind a timeout). **16 — Where
scale stops buying yield** — the most valuable slide in the act, and almost none of it is our data.
**17 — Four defects that reached real hardware.** **18 — The ledger that forgot, and what it still
forgets** (the A10 signature finding; pose it as a question — no code was changed for it).

### Act 3 · Usability — 19 to 21

**19 — divider.** **20 — As an application** (one YAML, one command, the laptop tier — and its
corollary). **21 — As a platform** (the control plane; and the component claim, which is empty).

### Close — 22 and 23

**22 — What is real, and what is not, by dimension.** Three columns, three green rows and three red
rows each. **Do not compress this slide**; the equal column lengths are the argument.

**23 — Seven things I would like this room's opinion on.** Grouped by what each one costs. Ask 7 is
new and comes straight out of the baseline's numbers: is per-GPU packing reachable through a
rhapsody resource shape, or does it need Dragon placement we do not control?

### Backups

**B1 — one experiment, typed at every hop** · **B2 — eight compute patterns** (carries the P7
census) · **B3 — four control models over one executor** (keeps the Flowgentic credit).

Both B1 and B2 were content slides in the previous version. They are out of every running order
now; do not put them back to fill time.

---

## Delivery notes

- **Open two terminals.** One in the repo root, one in `../IMPRESS`. Five anchors on these slides
  point into *their* checkout, and this audience may well ask you to open them.
- **Have `run.json` open.** Every number is in it, and "let me show you where that came from" is a
  stronger answer than repeating the number.
- **If the room goes deep on the engine or the backend**, stay on 13 and go to 21 if they ask about
  the process split. That is what they came for.
- **If someone asks why the outer loop is not a framework's**, go to B3. Flowgentic's own README
  agrees with us, and saying so with credit ends the exchange well.
- **If someone proposes fixing the signature on the spot** (slide 18), resist deciding in the room.
  The trust campaign is written and ready; changing pattern identity first would invalidate it.
- **Demo, if wanted:** `pytest tests -q -k lying` is 20 seconds and shows a tool that succeeds,
  reports 0.91 designability, and is failed by QC anyway.

---

## Before presenting

```sh
S=~/.claude/skills/code-walk-deck/scripts
PYTHONPATH=src python3 slides/run_model.py
python3 $S/check_anchors.py --anchors slides/anchors.json --root <workspace>
python3 $S/make_script.py --deck slides/build_deck.js
NODE_PATH=<dir with pptxgenjs> node slides/build_deck.js
soffice --headless --convert-to pdf --outdir slides slides/impress-a-codewalk.pptx
python3 $S/render_check.py slides/impress-a-codewalk.pptx   # and read the PNGs back
PYTHONPATH=src python3 -m pytest tests -q                   # the deck must not have touched the code
```

`build_deck.js` warns at build time if any code block would have to be set below 8.5 pt to fit.
That warning is the one build failure this deck cannot ship with — an overflowing code block on a
projector is unreadable from the third row.
