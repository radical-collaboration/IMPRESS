"""Replay a recorded campaign's planning decisions, Stage by Stage.

The counterpart to `policy/specifiers/replay.py`, and the half that got the most out of the
refactor: a Stage is now a durable artifact with an id, an attempt, its task mappings and -
since this phase - the **parameters** each task was given. `ReplayPolicy` could only replay an
`ExperimentIntent` reconstructed from a `decisions.jsonl` entry a model had chosen to write,
and before `mappings` was recorded, a replay re-ran the same chain with different numbers and
called it the same experiment.

**It replays the Stage, not the Planner.** The recorded mappings are used verbatim - tools,
params, lineages, wiring, seeds, parent node - rather than re-derived from the Toolkit. A
re-derivation would silently absorb every change made to the planner since, which is the one
thing a replay must not do.

**A rejection is divergence.** The recorded Stage was admitted when it ran; if the replaying
campaign refuses it, something about the campaign differs - budget, trust, site caps, the
gates - and the right answer is to say so rather than to improvise a smaller Stage and report
a replay.
"""
from __future__ import annotations

import logging
from typing import Any

from ...core.decision import ValidationFailure
from ...core.spec import Spec, Stage, TaskMapping
from ..planner import BasePlanner, PlanningContext
from ..specifiers.replay import ReplayDiverged

log = logging.getLogger(__name__)


class ReplayPlanner(BasePlanner):
    """Re-deploy a recorded campaign's Stages, in order."""

    name = "replay-plan"

    def __init__(self, records: list[dict[str, Any]]) -> None:
        if records is None:
            raise ValueError(
                "replay needs a recorded stage sequence: pass --replay-from <provenance dir>. "
                "A replay with no records is a different campaign, not a degraded one")
        self.records = [r for r in records if r.get("event") == "deployed"]
        self.i = 0

    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        """The next recorded Stage, or None - which ends the campaign, as exhaustion should.

        The objectives a recorded task served are **remapped onto this Spec's own ready
        objectives**, because objective ids are minted per campaign and the recorded ones name
        nothing here. The Reviewer checks coverage against the applied Spec, so carrying the
        recorded ids over would make every replayed Stage fail at `gate="coverage"` with a
        list of ids from another campaign.
        """
        del ctx
        while self.i < len(self.records):
            record = self.records[self.i]
            self.i += 1
            mappings = record.get("mappings")
            if not mappings:
                raise ReplayDiverged(
                    f"recorded stage {record.get('stage')!r} carries no `mappings`, so its "
                    f"parameters were never recorded - replaying it would re-run the same "
                    f"chain with different numbers. Re-record against a current campaign")
            served = sorted(o.id for o in spec.ready())
            tasks = [TaskMapping(**{**m, "objectives": served}) for m in mappings]
            return Stage(spec_generation=spec.generation, tasks=tasks,
                         parent_node=record.get("parent_node"),
                         rationale=f"{self.name}: recorded stage {record.get('stage')}")
        log.info("replay: the recorded stage sequence is exhausted")
        return None

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """None, loudly: the recorded Stage was admitted when it ran.

        `BasePlanner.replan` would answer the same way, but silently. A replay refused where
        the original was admitted is the most informative thing a replay can tell you - the
        campaign differs from the one recorded - and it belongs in the log at the moment it
        happens rather than being inferred from a stop reason later.
        """
        del spec, ctx
        log.error("replay diverged: recorded stage %s was admitted when it ran and is now "
                  "refused at %s: %s", stage.id, rejection.gate, rejection.reason)
        return None


__all__ = ["ReplayPlanner"]
