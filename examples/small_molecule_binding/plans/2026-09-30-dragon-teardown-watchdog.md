# Dragon `flow.shutdown()` teardown hang — still unfixed

**Severity:** high · **Status:** open
**Evidence:** job `22491438` (observed), job `22534628` (masked by TIMEOUT)

## The defect

Recorded in the CLAUDE.md 2026-09-27 row and still present. On job `22491438`, after
`[MANAGER] All pipelines finished. Exiting.` and `Shutting down Dragon backend`,
`flow.shutdown()` never returned. The job sat for exactly 60 minutes and had to be `scancel`led,
ending `State=CANCELLED` at `Elapsed=07:41:11` with `=== ... pipeline done ===` never printed.

That burned **~64 GPU-hours (37% of the job's billed total) for zero output**. The burn rate scales
with width: 32 GPU-h per hung hour at 8 nodes, 64 at 16.

## Why job 22534628 did not show it

It never got there. All 32 pipelines were still working when the 12 h wall limit hit
(`State=TIMEOUT`, `Elapsed=12:00:10`), so `flow.shutdown()` was never reached. The hang is
unobserved on this run, **not fixed**.

This also means the 12 h wall limit — chosen in the 2026-09-28 row specifically to bound this
risk — did its job, but by accident: it bounded a run that was too slow to finish rather than one
that hung on teardown.

## Why it matters more after the serialization fix

Once the adaptive bottleneck is gone, campaigns should actually *reach* completion inside their wall
limit. That makes teardown the thing standing between "work is provably done" and "job exits" — and
it moves this from a latent risk to one that fires on most runs.

## What is needed

There is no resume and no watchdog, so the SLURM wall limit is the only backstop.

1. **Bound `flow.shutdown()` in code.** Wrap it in `asyncio.wait_for` with a generous timeout (a few
   minutes is far beyond any legitimate teardown), and on expiry log loudly and exit the process
   rather than waiting. All scientific output is already on disk per-task at that point — nothing is
   lost by a hard exit after the manager reports all pipelines finished.
2. **Keep `--time` right-sized.** Do not return to 48 h. At 8 nodes a 48 h request exposes ~1536
   GPU-h to an unattended hang versus 384 at 12 h.
3. Consider emitting an explicit "teardown started"/"teardown complete" pair to the log so the hang
   is greppable rather than inferred from a missing final line.

## Where the code is

`run_small_molecule_binding.py`, `impress_smallmol_bind()` — the `try`/`finally` that calls
`await flow.shutdown()`. Note the telemetry `stop()` already sits in `finally` *before*
`flow.shutdown()` (CLAUDE.md 2026-09-28), deliberately, so the telemetry file survives an error
there; any timeout wrapper must preserve that ordering.
