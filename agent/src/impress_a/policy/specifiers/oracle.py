"""Model B's Specifier half: one structured call per signal.

`DECISION_SCHEMA` asked for a whole `Decision` in one object - a kind, a stage list, a replica
count, a params dict, a node to branch from and a reason - so one call answered "what should
the campaign be trying to achieve" and "which tool should run next" at the same time, and
nothing in a transcript could say which half a model was good at. It splits into `SPEC_SCHEMA`
here and `STAGE_SCHEMA` in `policy/planners/oracle.py`, which is the whole point of the
four-arm design: two seams, separately attributable.

**The model answers in the Spec's own vocabulary, not in the engine's.** It names metrics and
thresholds; it never names a tool, a replica count or a node id. That is not a restriction for
tidiness - `policy/specifier.py` records that a Specifier able to reach `tools` stops emitting
abstract intent - and it means the same reply is valid against the mock chain and the real one.

**It may not declare an objective satisfied**, for the same reason model C's caller may not:
satisfaction is computed from realized data, and a model able to assert it could end a campaign
by saying the work was done. `BaseSpecifier.satisfied` does that computation and this half
inherits it unchanged.

**Bounded, corrected, and degraded loudly.** `policy/reasoning.ask` owns all three, shared with
model A's nodes, so there is one answer to "what happens when the model will not answer" rather
than one per model.
"""
from __future__ import annotations

import json
from typing import Any

from ...core.goal import Goal
from ...core.spec import Aim, SatisfactionRule, Spec, SpecObjective, SpecRevision
from .. import reasoning
from ..specifier import BaseSpecifier, SpecEvidence
from .explicit import ThresholdSpecifier

#: What one Spec decision looks like. Prose values: handed to the client as a schema too,
#: which an endpoint that enforces `response_format` can act on.
SPEC_SCHEMA = {
    "action": "one of: hold | refine | retire",
    "metric": "the metric to refine on (refine only); must be one the campaign declares",
    "parent_node": "the design id to improve on (refine only); must be one on the front",
    "min": "lower bound the refined design must clear, or null",
    "max": "upper bound the refined design must clear, or null",
    "retire": "list of objective statements that cannot be measured here (retire only)",
    "rationale": "one sentence naming what is limiting the campaign",
}

ACTIONS = ("hold", "refine", "retire")


def _validator(ev: SpecEvidence) -> Any:
    """Every check on a reply, built against the live state and run INSIDE the retry loop.

    Placement is the whole value of it, and getting it wrong here was a real defect: these
    checks sat after `reasoning.ask` returned, so a model that named a metric the campaign
    never declared raised past `revise`, past `_respecify`, and out of the driver's `conduct`
    - ending the campaign on a reply the model would have corrected if asked. It is the same
    mistake a test caught in model A's strategy enum, in the one place where the consequence
    is a dead campaign rather than a degraded decision.
    """
    declared = {o.name for o in ev.observation.objectives}
    front = {n.id for n in ev.observation.pareto_front}

    def check(raw: dict[str, Any]) -> None:
        action = str(raw.get("action", "")).strip().lower()
        if action not in ACTIONS:
            raise ValueError(f"action {action!r} is not one of {ACTIONS}")
        if action != "refine":
            return
        metric = str(raw.get("metric") or "")
        if metric not in declared:
            raise ValueError(
                f"metric {metric!r} is not one this campaign declares ({sorted(declared)}); "
                f"an objective on a metric no tool reports makes every later Stage refusable")
        parent = str(raw.get("parent_node") or "")
        if not parent:
            raise ValueError("a refine action must name the parent_node it improves on")
        if parent not in front:
            raise ValueError(f"parent_node {parent!r} is not on the current front "
                             f"({sorted(front)})")

    return check


class OracleSpecifier(BaseSpecifier):
    """One `SPEC_SCHEMA` call per signal, with a declared fallback."""

    name = "oracle-spec"

    def __init__(self, oracle: Any = None, fallback: Any = None, sink: Any = None) -> None:
        #: None is the rehearsal, which is what `--model B` runs with no profile named.
        self.oracle = oracle
        #: A declared fallback is mandatory for a real run (Part A risk R7): an API outage
        #: must degrade explicitly, never stall a multi-GPU allocation. Defaulted to model
        #: D's Specifier so the campaign keeps specifying rather than stopping.
        self.fallback = fallback or ThresholdSpecifier()
        self.sink = sink
        self.degraded = False

    async def initial_spec(self, goal: Goal) -> Spec:
        """Delegated, for the reason model A delegates it.

        `Goal -> Spec` for the declared objectives is a transcription, and the four-arm
        comparison requires every arm to start from the same objectives - an arm whose
        Specifier emits a different set is void for the primary endpoint. A model asked to
        restate four objectives it was given can only get it wrong.
        """
        return await self.fallback.initial_spec(goal)

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        if self.oracle is None:
            return await self.fallback.revise(spec, ev)
        try:
            raw = await reasoning.ask(
                self.oracle, "spec", self._prompt(spec, ev), SPEC_SCHEMA,
                required=("action", "rationale"), validate=_validator(ev),
                sink=self.sink, cycle=ev.cycle)
            return self._to_revision(raw, spec, ev)
        except reasoning.NodeRefused as refused:
            self.degraded = True
            reasoning.degraded(self.sink, "spec", ev.cycle, str(refused),
                               getattr(self.fallback, "name", "?"))
            return await self.fallback.revise(spec, ev)
        except ValueError as unusable:
            # The validator should have caught this inside the retry, so arriving here means a
            # check exists in one place and not the other. Degrade rather than raise: a
            # reply nobody can apply is not a reason to end a campaign that is otherwise
            # healthy, and the transition says a decision was lost.
            self.degraded = True
            reasoning.degraded(self.sink, "spec", ev.cycle, f"unusable reply: {unusable}",
                               getattr(self.fallback, "name", "?"))
            return await self.fallback.revise(spec, ev)

    def _to_revision(self, raw: dict[str, Any], spec: Spec,
                     ev: SpecEvidence) -> SpecRevision:
        """A reply as a revision.

        The references were checked by `_validator` inside the bounded retry, where the model
        could still be told. They are re-checked here rather than assumed, because this method
        is also the one a test calls directly and because a validator and an applier that
        disagree is the kind of gap that only shows up as a dead campaign - `revise` turns a
        `ValueError` from here into a degraded decision rather than letting it escape.
        """
        action = str(raw.get("action", "")).strip().lower()
        if action == "retire":
            dead = ThresholdSpecifier().unproducible(spec, ev)
            return SpecRevision(deleted=list(dead),
                                rationale=f"{self.name}: {raw.get('rationale', '')}")
        if action != "refine":
            return SpecRevision()

        metric = str(raw.get("metric") or "")
        declared = {o.name for o in ev.observation.objectives}
        if metric not in declared:
            raise ValueError(
                f"metric {metric!r} is not one this campaign declares ({sorted(declared)}); "
                f"an objective on a metric no tool reports makes every later Stage refusable")
        parent = str(raw.get("parent_node") or "")
        if parent not in {n.id for n in ev.observation.pareto_front}:
            raise ValueError(f"parent_node {parent!r} is not on the current front")

        goal_obj = next(o for o in ev.observation.objectives if o.name == metric)
        rule = SatisfactionRule(
            kind="metric_in_range", metric=metric,
            # The campaign's own bounds win over the model's. A model may choose WHICH
            # objective to push on; moving the threshold it is judged against would let an
            # arm declare success at a weaker number than the one it is being compared on.
            min=goal_obj.min, max=goal_obj.max)
        bound = rule.as_objective()
        hits = sum(1 for d in ev.data.metrics(metric)
                   if bound is not None and bound.satisfied_by(d.value))
        aim = Aim(statement="refine the best design so far")
        return SpecRevision(
            new_aims=[aim],
            new_objectives=[SpecObjective(
                aim=aim.id, statement=f"improve {metric} on {parent}", targets=[metric],
                parent_node=parent,
                # `hits + 1`, for the reason `ThresholdSpecifier` records: the parent's own
                # measurement is already realized, so a default rule is met the moment the
                # objective exists - which also defeats the open-refinement cap, because a
                # satisfied objective is not an open one.
                satisfied_when=rule.model_copy(update={"n": hits + 1}))],
            rationale=f"{self.name}: {raw.get('rationale', '')}")

    def _prompt(self, spec: Spec, ev: SpecEvidence) -> str:
        obs = ev.observation
        front = [{"id": n.id, **{o.name: n.metric(o.name) for o in obs.objectives}}
                 for n in obs.pareto_front]
        return (
            "You are the Specifier of an autonomous protein-design campaign. Decide what the "
            "campaign should now be trying to achieve. Do NOT choose tools or parameters - "
            "another role does that.\n"
            f"GOAL: {obs.goal}\nCYCLE: {obs.cycle}\n"
            f"OBJECTIVES: {[o.model_dump() for o in obs.objectives]}\n"
            f"OPEN: {[o.statement for o in spec.open_objectives()]}\n"
            f"PARETO FRONT ({len(front)}): {json.dumps(front, default=str)}\n"
            # Two machine-readable lines, and they are a contract rather than redundancy.
            # They are unambiguous for a live model - no Python repr to interpret - and they
            # are what `RehearsalOracle` keys on, so the stand-in exercises the same `think`
            # signature as the live client instead of needing one of its own.
            f"FRONT_IDS: {json.dumps([n.id for n in obs.pareto_front])}\n"
            f"METRICS: {json.dumps([o.name for o in obs.objectives])}\n"
            f"POPULATION: {obs.population.model_dump()}\n"
            f"BUDGET REMAINING: {({d: obs.budget.remaining(d) for d in obs.budget.limits})}\n"
            "hold = the Spec is right as it stands; refine = add one objective to improve a "
            "named design on a named metric; retire = an objective cannot be measured here."
        )


__all__ = ["ACTIONS", "SPEC_SCHEMA", "OracleSpecifier"]
