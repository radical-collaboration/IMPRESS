# Done — stagnation under fan-out

## Problem

Stagnation terminates a campaign when the Pareto front stops improving. It counted **absorbed runs**,
which was correct while a cycle absorbed exactly one result. Once several experiments could be in
flight it was wrong: a four-wide ensemble produces four absorptions in quick succession, and if none
moves the front the default `stagnation_limit: 3` fires within about a second — regardless of how
well the campaign is doing.

## Why it took three encounters to fix

1. Stage 3's pause test died at exactly 10-12 runs and looked like a pause that never lifted.
2. Stage 4's fan-out test became **flaky** — passing once, failing once. Worse than failing, because
   it presents as infrastructure noise rather than as a defect.
3. Three tests ended up carrying `stagnation_limit = 10_000` purely to opt out.

Each time the workaround went into the test and the defect stayed in the executor. The lesson worth
keeping: **a magic number appearing in a third test is a bug report.** The first two were treated as
test setup; only the pattern made it visible.

## The ruling

**The flaw was evidential, not arithmetic.** Those four runs were launched before any of them
reported. Not one could have been informed by the others' results. Counting them as four independent
pieces of "we tried and failed to improve" evidence is the same mistake the interlock already refuses
to make when it rules that concurrent instances of a pattern are *one draw sampled twice*.

So: **count a completed run only if it was submitted after the previously counted run's result had
already been absorbed.** A run already in flight when that result landed belongs to the same wave and
never saw the evidence it is being blamed for ignoring.

- One increment per wave: four concurrent non-improving runs advance the counter by one, not four.
- Serial behaviour is bit-identical — at `concurrency: 1` every run is submitted after the previous
  was absorbed, so every run counts, exactly as before.
- A reasoner that merely polls still never advances it, preserving the Stage 0 property.

Implementation: `RunRecord.informed_by` (absorptions visible at admission), a `_counted_through`
watermark on the executor, and `_note_progress(rec)`.

## Evidence it worked

The three `stagnation_limit = 10_000` workarounds were **removed**, and the suite stayed green —
including the pause test, which had been expected to still need one legitimately.

The new test was checked against the restored old rule: one 4-wide wave gives `_stagnant = 4` where
the test asserts `1`. It fails on the old behaviour rather than passing vacuously.

A reasoner running 4 waves of 6 experiments at `concurrency: 8` delivered 24/24 and ended for the
reason it chose. Under the old counting it would have died during the first wave, reporting a stop
reason that sounded authoritative.

The stop reason also stopped lying: it said "front unchanged for N **cycles**" and had not counted
cycles since Stage 0. It now says "over N informed attempts".
