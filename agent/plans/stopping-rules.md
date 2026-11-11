# Stopping rules: the Goal asks for ten, the Spec was satisfied by one

**Status:** fixed on `agent/stopping-rules`, **unrun on hardware** · **Evidence:** jobs 23671024,
23671367 · **Items:** G11, and the C8 annotation it forces

## The problem, and the evidence

The second four-arm smoke (job 23671367) ran clean - four arms, exit 0, no crashes - and was
still not an experiment. Arm C ran 24 tasks and stopped at **cycle 0** on *"every spec objective
satisfied"*. Arms A, B and D each managed one cycle before a separate defect (G10) stopped them.

Arm C's stop was correct behaviour, and that is the finding. `ThresholdSpecifier.initial_spec`
built one `SatisfactionRule` per declared objective and left `n` at its default of **1**
(`policy/specifiers/explicit.py`). So the Spec was satisfied by the **first** design clearing
each bar, while the campaign's Goal reads

> Design at least ten distinct small-molecule binders meeting every declared threshold

and the experiment's primary endpoint counts distinct T2 designs per billed node-hour. Two
stopping rules disagreed and the laxer one won - backlog X1's shape, inverted.

**`target_front` was dead config.** G11 recorded that the declared value "never reaches" the
rule. It was worse: `target_front` was parsed into `CampaignSpec`, forwarded into
`ReasonerOptions`, and **read by no code anywhere**. Both Delta arm specs have declared
`target_front: 10` since they were written, and it had never done anything. That is section E's
category - configuration that exists and does nothing - the same class as E1's `tool_delivery`
switch, and it had survived because the field existed in two places and so looked wired.

A node did clear every bar on that run: `complex_plddt` 0.904 against a 0.75 bound,
`ligand_iptm` 0.851, `shape_complementarity` 0.731, `interaction_energy` -25.47. So the campaign
was right to say the Spec was satisfied. It was the Spec that was asking for too little.

## The change

**`target_front` moves onto the `Goal`.** `core/goal.py`'s own docstring decides this: the Goal
carries "what success means" and deliberately not "how the campaign is driven - backend,
concurrency, stagnation, cycle bounds". *Ten designs* is success criteria, not a loop knob.
Keeping it there means `ThresholdSpecifier.initial_spec(goal)` reads it directly, so `_spec_d`
keeps its recorded ruling - "takes nothing from the options: a deterministic `Goal -> Spec` is a
function of the Goal" - which threading the value through `ReasonerOptions` would have broken.

**The rule.** A **bounded** objective gets `n = goal.target_front`; an **unbounded** one stays at
`n = 1`. The second half is not an oversight: an unbounded objective ranks, it has no finish
line, and ten readings of a number nobody has to beat say nothing more than one. The suite
already ruled on that, and that test passes untouched.

**Nothing else moves.** `CampaignSpec.target_front` defaults to 0, so every campaign that
declares no front target keeps `n = 1`. The value is deliberately **not** taken from
`ReasonerOptions.target_front`, whose default is 3 - that would have silently retuned every
existing campaign. The refinement path is untouched: `explicit.py` and `oracle.py` both set
`n = hits + 1` on purpose, so a refinement objective is not satisfied by its parent's
already-realized measurement.

**It crosses the control plane too**, via a new `CampaignObservation.target_front`. An external
caller builds its `Goal` from the observation and from nothing else, so without this a *served*
campaign's Specifier would use the default while an in-process one used the spec's. In the
four-arm experiment that is arm C stopping at one design while A, B and D run to ten: a
difference between arms which is not the model, invisible because every arm would still have
completed with plausible numbers. It is exactly what `impress-a compare`'s one-variable guard
exists to refuse, and the guard cannot see it.

One fix site serves four Specifiers - `oracle.py`, `agentic.py` and `external.py`'s fallback all
delegate `initial_spec` to `ThresholdSpecifier`. `replay.py` is deliberately excluded: it
rebuilds objectives verbatim from recorded `specs.jsonl`, and a replay that re-derives `n` stops
reproducing the campaign it replays.

## What this rule is not

`n` counts **readings**, not distinct designs: `DataRegistry.satisfies` is
`len(metrics(metric)) >= n`, one row per (task, metric) per ingested outcome. The endpoint is
distinct T2 designs after sequence clustering, which is a smaller number. At one scoring task
per lineage the two track closely enough to stop on, but **this is a stopping condition and not
a score** - the harness is what scores, and a report must not quote `n` as a yield.

Making `n` count distinct `node_id`s was considered and rejected: that field is only populated
when a run produced exactly one node, so it would silently undercount at width 4, and three
other rule kinds share the primitive.

## Test

**`test_a_campaign_asked_for_ten_designs_is_not_satisfied_by_one`** (new) - a campaign
declaring `target_front: 10`, whose tools clear both bars on run 1, must NOT stop on "every
spec objective satisfied"; it stops on `max_cycles`. Its second half checks the count lands on
bounded objectives only.

**`test_the_front_target_reaches_a_remotely_driven_campaign_too`** (new) - the observation and
the in-process Goal both carry the declared value.

**`test_the_listener_stops_the_campaign_when_every_objective_is_satisfied`** - unchanged. A
campaign declaring no target still stops at one, which is right.

**`test_an_unbounded_objective_gets_a_measurement_rule_not_a_vacuous_one`** - unchanged, and
must stay so: if it fails, the count has reached unbounded objectives and the fix is wrong.

**`test_split_process.py` / `test_remote_session.py`** - `stop_reason` parity across
in-process, remote and replay.

Both new tests were confirmed to fail with their own change reverted - the first on the stop
reason, the second on the observation field.

**On hardware**, in order: `impress-a validate-tasks` on the smoke spec (6/6 and exit 0 at job
23670965), then the four-arm array. The pass criterion is the one section 11 of the
pre-registration names and the last two smokes failed: **at least 3 cycles per arm in 40
minutes**, and no arm stopping on "every spec objective satisfied". Record the job id in the
backlog row and in this file's status line in the same step.

Expect arms to stop on `max_cycles` or budget now. If an arm still gets ten readings over
`complex_plddt >= 0.75` inside an hour, that is a finding about the fold bar worth more than
this fix, and it belongs with the pre-registration re-baseline below.

## Deliberately not in this change

- **The pre-registration re-baseline.** §3 asserts `C_T3 = 0` from `complex_plddt` measurements
  of 0.426 / 0.486 / 0.507 ("0 of 3"); §13 derives `p_T2 ~ 0.06`, `p_T3 <= 0.04` and "ten T3
  designs is not reachable" from that same one-sample baseline; §12's 0.06 / 0.02 cut-points
  come from §13's arithmetic, and §14's first claim rests on it. Those three runs came from the
  `/work/hdd` checkout (C11), so the baseline describes different code - and arm C has since
  measured 0.904, one for one over the T3 bar. That re-derivation needs its own evidence and its
  own amendment; burying it in a stopping-rule diff is how a pre-registration stops meaning
  anything. §2, §4, §5, §9 and §11 do not depend on it.
- **The C11 annotation sweep** over the eleven other backlog items citing pre-2026-11-08 jobs.
  Only C8 is annotated here, because it quotes the same baseline as settled fact in the file
  where G11 now contradicts it.
