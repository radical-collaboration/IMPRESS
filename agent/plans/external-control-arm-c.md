# Arm C served a campaign that two reasoners drove and neither finished

**Status:** fixed on `agent/stopping-rules`, **unrun on hardware** · **Evidence:** job 23675997
(arm C), job 23675869 (arm B, for the liveness measurement) · **Items:** G12

## The problem, and the evidence

The third four-arm smoke (array 23675376) ran clean and arm C still produced one cycle. Its
campaign log, in full, is four lines:

    23:38:14  serving campaign with C attached: an external caller steers it in place
    23:39:42  submitted r0001: ... 24 tasks (trusted=True)
    23:42:17  external planner: no directive in 120.0s; on_timeout=stop
    23:42:17  stop requested: guard(external-plan) planned nothing at cycle 0
    23:42:59  reaped r0001: 24/24 tasks ok

The first reading of this was that the `ExternalPlanner`'s 120 s patience expired while
r0001 was still running - G10's shape, a timeout shorter than a cycle counting normal work as
silence - and that the cure was to raise the timeout or suspend it while work is in flight.

**That reading is wrong, and the stop reason says so.** It names *cycle 0*. `RolesDriver`
increments `turn` the moment a stage is deployed (`runtime/roles.py`), so a planner that had
already placed r0001 could not time out at cycle 0. The served driver never completed a turn.
It was never going to.

### Two drivers, one executor

`impress-a serve <spec> --model C` builds model C's halves **in the serving process** and then
calls `mgr.run()`. That process therefore drives the campaign itself, and its Planner is an
inbox: it waits for a caller to `steer` it.

`impress-a control` is not that caller. It is the same `RolesDriver` the in-process arms use,
pointed at a `RemoteSession`, and it drives by calling `submit_stage` over the plane. It never
calls `plane.steer`. Nothing shipped in this project does.

So arm C ran two reasoners against one executor:

| process | halves | what it did |
|---|---|---|
| `serve --model C` | `ExternalSpecifier` / `ExternalPlanner` | waited at turn 0 for a directive nothing would send; stopped the campaign |
| `control --model B` | Beam-backed oracle halves | planned and submitted r0001, correctly |

The sidecar's work was real - 24 tasks, six stages, all ok - and the other driver in the same
process killed the campaign underneath it. The 120 s coincidence is just the served driver's
first `plan()` call, ~35 s after r0001 was submitted, timing out on schedule.

That also explains the *previous* smoke (23671367), where arm C stopped at cycle 0 on "every
spec objective satisfied": the served driver's Specifier saw a Spec the sidecar's run had
already satisfied at `n=1`, and the served driver got there first.

### The second defect the first one hid

`cli.control_campaign` built its driver with `max_turns=10_000` - a number no campaign
declares - while every in-process arm is driven through `spec.max_cycles` by `manager.py`. Arm
C has never survived past cycle 1, so nothing could notice. With the arrangement above fixed,
arm C would have run until its budget, its stagnation limit or its wall clock stopped it while
A, B and D stopped at six cycles: a difference between arms which is not the model, which is
precisely what `impress-a compare`'s one-variable guard exists to refuse and precisely what it
cannot see.

This is G11's gap again, in the half of the observation that says how a campaign is *driven*
rather than what it is *for*.

## The change

**Arm C serves bare.** `scripts/delta_gpu_run.sh` drops `--model` and `--caller-timeout` from
the serve branch. Without `--model`, `serve` attaches `_Idle` - "a reasoner that is not there"
- which is what the two-process split was built for, and the sidecar becomes the campaign's one
and only reasoner. B and C then differ in exactly one thing: whether the reasoner sits in the
executor's process or drives it over the plane. That is the contrast the launcher already
claimed and the one arm C can honestly make.

**The campaign's bounds cross the plane.** `CampaignObservation` gains `max_cycles` and
`max_attempts`, populated by `executor.observe()` from the spec, and `control_campaign` drives
with `obs.max_cycles or 10_000` and `obs.max_attempts or 4`. 0 means the served campaign
declared nothing, so no existing caller moves.

**The liveness bound is now what bounds arm C, and it was left at 120 s.** It is armed by
`plane.register`, suspended while any run is in flight, and refreshed by every `observe()`, so
the only window it watches is the caller thinking between cycles. Measured on arm B of job
23675869, that window - two Beam calls and the deploy - is **9-13 s** (23:42:44.9 -> 23:42:57.4
on its sixth cycle). 120 s is about ten times the observed need, and raising a liveness bound
to cover a caller that has actually died is the failure it exists to prevent. Both arm specs
carry that measurement in place of the comment that described the arrangement this change
removes.

## What is deliberately not in this change

**Model C's own code is still unexercised on hardware.** The external inbox halves,
`on_timeout`, directive validation and the `steer` route are covered by `tests/` and by
nothing on Delta, because nothing shipped steers a campaign. Writing that caller - a process
that observes, asks a model for a *directive* rather than for a stage, and pushes it through
`plane.steer` - is a real piece of work with its own design question (what a directive should
contain that a stage does not), and it is G12's open half. Until it exists, arm C measures the
out-of-process split, not the inbox halves, and the pre-registration should say so.

**The prereg re-baseline** and **the C11 annotation sweep** stay where `stopping-rules.md`
left them.

## Test

**`test_a_remotely_driven_campaign_stops_where_the_campaign_said_to`** (new,
`tests/test_split_process.py`) - two real processes, `serve` and `control`, against a spec
declaring `max_cycles: 2`. The served process must report `max_cycles=2 reached`. It declares
`target_front: 10` as well, so satisfaction cannot reach the stop first and make the assertion
pass for the wrong reason. Confirmed to fail with the change reverted: the campaign ran **6**
cycles and stopped on "every spec objective satisfied".

**`test_serve_and_control_drive_a_campaign_in_two_processes`** - unchanged, and it is the
arrangement arm C now uses: bare `serve` plus `control`.

**`test_model_c_is_refused_by_run_rather_than_silently_becoming_d`**,
**`test_an_external_caller_steers_both_halves_over_the_socket`**,
**`test_an_unaddressed_half_is_refused_with_its_reason_over_http`** - unchanged. Model C's
halves and the `steer` route keep their coverage; what changed is which arrangement Delta runs,
not whether the code works.

**On hardware**: the four-arm array. Arm C's pass criterion is section 11's - at least 3 cycles
in 40 minutes - plus a stop reason that reads `max_cycles=6 reached`, which is the one line
that proves both halves of this fix at once.
