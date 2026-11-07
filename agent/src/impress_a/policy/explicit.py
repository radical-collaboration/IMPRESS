"""Control model D - explicit user-supplied policies.

Not the fallback option; the scientific control. A campaign run under D with a fixed seed
is reproducible end to end, which makes it the baseline against which A and B must justify
their cost. `ReplayPolicy` turns a provenance log from a record into an executable artifact.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.decision import (
    Backtrack,
    CampaignObservation,
    ComposeAndRun,
    Decision,
    ExperimentIntent,
    Stop,
    ValidationFailure,
)
from .base import BasePolicy

log = logging.getLogger(__name__)

SELF_CONSISTENCY = ["mock_generate", "mock_design", "mock_fold", "mock_score"]


class ThresholdPolicy(BasePolicy):
    """Rule cascade over the self-consistency loop.

    Escalates sampling while the front is empty, exploits when it is not, and backtracks
    off a dead branch rather than refining it forever.
    """

    name = "threshold"

    def __init__(self, stages: list[str] | None = None, max_cycles: int = 6,
                 target_front: int = 3, base_replicas: int = 2):
        self.stages = stages or SELF_CONSISTENCY
        self.max_cycles, self.target_front = max_cycles, target_front
        self.base_replicas = base_replicas
        self._stalled = 0
        self._validate_stopping_condition()

    def _validate_stopping_condition(self) -> None:
        """Fail loudly at construction if no stopping condition exists.

        Adopted from campaign_manager (Phase 3, pattern #9) - catches the commonest
        policy authoring error at the earliest possible point.
        """
        if not self.max_cycles and not self.target_front:
            raise ValueError(f"{self.name}: no stopping condition (max_cycles/target_front)")

    async def decide(self, obs: CampaignObservation) -> Decision:
        if obs.cycle >= self.max_cycles:
            return Stop(reason=f"max_cycles={self.max_cycles} reached")
        if len(obs.pareto_front) >= self.target_front:
            return Stop(reason=f"target front size {self.target_front} reached")
        if blown := obs.budget.exhausted():
            return Stop(reason=f"budget exhausted: {blown}")

        front = obs.pareto_front
        if front and self._stalled >= 2:
            self._stalled = 0
            return Backtrack(node_id=front[0].id,
                             rationale="stalled twice; branching from best node")

        # Explore harder while the front is empty; exploit once it is not.
        exploring = not front
        steps = 160 if exploring else 80
        temp = 0.25 if exploring else 0.05
        return ComposeAndRun(
            intent=ExperimentIntent(
                goal=obs.goal, stages=self.stages,
                replicas=self.base_replicas + (1 if exploring else 0),
                params={"mock_generate": {"diffusion_steps": steps},
                        "mock_design": {"temperature": temp}},
                parent_node=front[0].id if front else None),
            rationale=("explore: front empty" if exploring
                       else f"exploit: front has {len(front)}"))

    async def interpret(self, results, obs: CampaignObservation) -> str | None:
        if results is not None and not results.all_gates_passed:
            self._stalled += 1
        else:
            self._stalled = 0
        return None

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision:
        """Shrink BREADTH on a budget or interlock rejection; otherwise stop.

        **The chain is never truncated.** It used to be, once breadth hit 1: the tail was
        dropped to fit, which is a cost heuristic that knows nothing about what the graph can
        then MEASURE. On job 22675512 it dropped `boltz_predict` - solely because the campaign
        lists it last - and `boltz_predict` is the only producer of `complex_plddt` and
        `ligand_iptm`, two of that campaign's four objectives. The run was unwinnable from the
        moment it was admitted and said so nowhere: the admitted graph records
        `rejected: null`.

        A warning was added at the time and was not enough. Two things changed since: the
        Reviewer's coverage gate now REFUSES a Stage that cannot produce a ready objective
        (backlog A8), so a truncated chain is rejected rather than run - and that turns the
        heuristic from a quiet loss into a guaranteed round trip. Dropping a lineage is the
        correction that cannot change what a graph measures, because a lineage is a whole
        chain; at one lineage there is nothing left to give, and stopping is the honest answer.
        """
        if failure.gate in ("budget", "interlock") and isinstance(decision, ComposeAndRun):
            if decision.intent.replicas > 1:
                decision.intent.replicas -= 1
                return decision
        return Stop(reason=f"rejected at {failure.gate}: {failure.reason}")


class ReplayPolicy(BasePolicy):
    """Re-execute a recorded decision sequence. Provenance as an executable artifact."""

    name = "replay"

    def __init__(self, records: list[dict[str, Any]]):
        self.records = list(records)
        self.i = 0

    async def decide(self, obs: CampaignObservation) -> Decision:
        while self.i < len(self.records):
            rec = self.records[self.i]["decision"]
            self.i += 1
            kind = rec.get("kind")
            if kind == "compose_and_run":
                return ComposeAndRun(**rec)
            if kind == "backtrack":
                return Backtrack(**rec)
            if kind == "stop":
                return Stop(**rec)
        return Stop(reason="replay exhausted")

    async def on_rejected(self, decision, failure):
        return Stop(reason=f"replay diverged: {failure.gate}: {failure.reason}")
