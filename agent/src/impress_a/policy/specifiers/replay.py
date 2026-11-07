"""Replay a recorded campaign's specification decisions. Provenance as an executable artifact.

`ReplayPolicy` replayed `decisions.jsonl`, a record each model wrote for itself through an
optional sink - so what could be replayed depended on which model had bothered. The role split
makes this strictly better, because `specs.jsonl` and `stages.jsonl` are **executor-written**:
the Specifier authors a revision and the executor applies it and records it, so the record
exists for every model whether or not it keeps notes, and a reasoner cannot write a flattering
one.

Replaying the Spec half separately is what makes `--specifier replay --planner X` useful: it
pins the specification of a recorded campaign and lets a different Planner answer it, which is
the one experiment that isolates the planning half with no new allocation.

**It replays what was authored, not what was found.** Aims, objectives and deletions are the
Specifier's decisions and are reproduced; recorded satisfaction is not, because satisfaction is
computed from realized data and the replaying campaign has its own. So a replay does not
reproduce a cycle count - the recorded campaign's objectives may be met a cycle sooner or later
here - and that is the honest behaviour rather than a gap: reproducing a finding from another
campaign's draws would let a replay end claiming work it never did.

**It diverges loudly.** A record whose generation does not follow the Spec it is being applied
to means the campaign being replayed is not the campaign that was recorded, and continuing
would produce a run that looks like a replay and is not one. `ReplayDiverged` says so with
both generations.
"""
from __future__ import annotations

import logging
from typing import Any

from ...core.goal import Goal
from ...core.spec import Aim, Spec, SpecObjective, SpecRevision
from ..specifier import BaseSpecifier, SpecEvidence

log = logging.getLogger(__name__)


class ReplayDiverged(RuntimeError):
    """The recorded sequence no longer describes the campaign replaying it."""


class ReplaySpecifier(BaseSpecifier):
    """Re-author a recorded campaign's Spec, revision by revision."""

    name = "replay-spec"

    def __init__(self, records: list[dict[str, Any]]) -> None:
        if records is None:
            raise ValueError(
                "replay needs a recorded spec sequence: pass --replay-from <provenance dir>. "
                "A replay with no records is a different campaign, not a degraded one")
        self.records = [r for r in records if r.get("event") in ("initial", "revision")]
        self.i = 0

    async def initial_spec(self, goal: Goal) -> Spec:
        """The recorded initial Spec, rebuilt from its own objectives.

        `goal` is deliberately unused: a replay reproduces what was specified, and deriving
        the Spec from the Goal again would make the replay a fresh specification that happens
        to start from the same place.
        """
        del goal
        record = next((r for r in self.records if r.get("event") == "initial"), None)
        if record is None:
            raise ValueError("no `initial` event in the recorded spec sequence")
        self.i = self.records.index(record) + 1
        spec = Spec()
        spec.apply(SpecRevision(
            new_aims=[Aim(**a) for a in record.get("aims") or []],
            new_objectives=[SpecObjective(**o) for o in record.get("objectives") or []],
            rationale=f"{self.name}: recorded generation {record.get('generation')}"))
        return spec

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        """The next recorded revision, or an empty one once the record runs out.

        Exhaustion is not divergence: a replayed campaign may legitimately run longer than the
        one recorded - a slower allocation, a different draw - and the honest answer then is
        that the recording has nothing more to say about the specification.
        """
        del ev
        while self.i < len(self.records):
            record = self.records[self.i]
            self.i += 1
            if record.get("event") != "revision":
                continue
            recorded = int(record.get("generation") or 0)
            # The recorded generation is the one AFTER the revision was applied, so the Spec
            # being replayed must currently be one behind it.
            if recorded and recorded <= spec.generation:
                raise ReplayDiverged(
                    f"recorded revision reaches generation {recorded}, but the replaying "
                    f"Spec is already at {spec.generation} - this is not the campaign that "
                    f"was recorded")
            # Recorded `status_changes` are deliberately DROPPED. A status change is a
            # finding - `satisfied` computes it from realized data, and this half inherits
            # that computation - so replaying one would mark an objective satisfied on
            # ANOTHER campaign's evidence, and a replay whose draws came out worse would end
            # claiming work that was never done. What is replayed is what the recorded
            # Specifier AUTHORED: aims, objectives and deletions.
            return SpecRevision(
                new_aims=[Aim(**a) for a in record.get("new_aims") or []],
                new_objectives=[SpecObjective(**o)
                                for o in record.get("new_objectives") or []],
                deleted=list(record.get("deleted") or []),
                rationale=f"{self.name}: {record.get('rationale') or ''}".strip())
        return SpecRevision()


__all__ = ["ReplayDiverged", "ReplaySpecifier"]
