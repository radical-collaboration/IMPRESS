"""The Data registry: realized data, and futures for work in flight.

What the Listener maintains. It is the half of the architecture that answers "has enough
arrived to change the Spec?", and it is deliberately *not* the campaign state: the tree, the
budget and the trust ledger stay with the executor, which is their only writer. This holds a
projection of what has landed, in the shape the Specifier's satisfaction rules ask about.

**No futures live here.** A `TaskFuture` is a record of work in flight - ids, the ports and
metrics it is expected to produce, a deadline - and not an `asyncio.Future`. That is forced:
the Listener runs in the control process while the work runs in the execution process, and an
awaitable does not cross that boundary. Completion arrives through `CampaignSession.as_completed`
and is ingested here, which is the same mechanism in-process and over a socket.

Everything is serializable for the same reason.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from .artifacts import ArtifactRef
from .results import RunOutcome
from .spec import SatisfactionRule
from .types import ArtifactType


def _now() -> datetime:
    return datetime.now(UTC)


class DatumKind(str, Enum):
    METRIC = "metric"
    ARTIFACT = "artifact"
    NODE = "node"


class RealizedDatum(BaseModel):
    """One thing that has actually arrived."""

    kind: DatumKind
    name: str = ""                       # metric name, or output port name
    node_id: str | None = None           # the DesignNode it belongs to
    value: float | None = None           # METRIC only
    ref: ArtifactRef | None = None       # ARTIFACT only
    from_run: str = ""
    from_task: str = ""
    at: datetime = Field(default_factory=_now)

    @property
    def is_finite(self) -> bool:
        return self.value is not None and math.isfinite(self.value)


class TaskFuture(BaseModel):
    """Work in flight, as the Listener can see it from another process."""

    task_id: str
    run_id: str = ""
    stage_id: str = ""
    objectives: list[str] = Field(default_factory=list)
    expected_outputs: list[ArtifactType] = Field(default_factory=list)
    expected_metrics: list[str] = Field(default_factory=list)
    deadline: datetime | None = None
    #: Set when the run this task belonged to has been collected. The future is kept rather
    #: than dropped, so "what did this campaign ever have in flight" stays answerable.
    settled: bool = False


class DataRegistry(BaseModel):
    """Realized data plus in-flight futures, and the questions a Specifier asks of them."""

    realized: list[RealizedDatum] = Field(default_factory=list)
    futures: dict[str, TaskFuture] = Field(default_factory=dict)
    #: Absorptions ingested so far. A monotone cursor the Listener can compare against, so
    #: "has anything new landed" does not require diffing the whole registry.
    seq: int = 0

    # -- writing -------------------------------------------------------------
    def expect(self, fut: TaskFuture) -> None:
        self.futures[fut.task_id] = fut

    def ingest(self, outcome: RunOutcome) -> list[RealizedDatum]:
        """Record what one finished run produced. Returns just the new data.

        Reads the run's own per-task outcomes rather than its merged view, so a metric can be
        attributed to the task that reported it - which is what makes a per-Task validation
        table and a per-stage pass rate computable from this registry later.
        """
        new: list[RealizedDatum] = []
        for node_id in outcome.nodes:
            new.append(RealizedDatum(kind=DatumKind.NODE, name=node_id, node_id=node_id,
                                     from_run=outcome.run_id))
        for task in outcome.tasks:
            for metric, value in task.metrics.items():
                new.append(RealizedDatum(
                    kind=DatumKind.METRIC, name=metric, value=value,
                    node_id=outcome.nodes[0] if len(outcome.nodes) == 1 else None,
                    from_run=outcome.run_id, from_task=task.task_id))
            for port, ref in task.outputs.items():
                new.append(RealizedDatum(
                    kind=DatumKind.ARTIFACT, name=port, ref=ref,
                    from_run=outcome.run_id, from_task=task.task_id))
            if (f := self.futures.get(task.task_id)) is not None:
                f.settled = True
        self.realized.extend(new)
        self.seq += 1
        return new

    # -- reading -------------------------------------------------------------
    def pending(self) -> list[TaskFuture]:
        return [f for f in self.futures.values() if not f.settled]

    def metrics(self, name: str) -> list[RealizedDatum]:
        return [d for d in self.realized
                if d.kind is DatumKind.METRIC and d.name == name and d.is_finite]

    def artifacts(self, port: ArtifactType | None = None) -> list[RealizedDatum]:
        out = [d for d in self.realized if d.kind is DatumKind.ARTIFACT and d.ref is not None]
        if port is None:
            return out
        return [d for d in out if d.ref is not None and d.ref.type.unifies_with(port)]

    def nodes(self) -> list[str]:
        return [d.name for d in self.realized if d.kind is DatumKind.NODE]

    def satisfies(self, rule: SatisfactionRule) -> bool:
        """Whether this rule holds against what has arrived. `n` is a threshold, not an index.

        `metric_in_range` delegates the comparison to `Objective.satisfied_by` via
        `SatisfactionRule`, so a threshold means exactly one thing to the Listener and to the
        Pareto front. Two implementations of "acceptable" is how those two quietly diverge.
        """
        if rule.kind == "count":
            return len(self.nodes()) >= rule.n
        if rule.kind == "artifact_present":
            return len(self.artifacts(rule.port)) >= rule.n
        if rule.metric is None:
            return False
        if rule.kind == "metric_present":
            return len(self.metrics(rule.metric)) >= rule.n
        if rule.kind == "metric_in_range":
            # An unbounded rule expresses no condition, so it is never satisfied - see
            # `SatisfactionRule.is_bounded`. Reading "no constraint" as "already met" would
            # finish a campaign the moment its first unbounded metric reported anything.
            obj = rule.as_objective()
            if obj is None:
                return False
            hits = [d for d in self.metrics(rule.metric) if obj.satisfied_by(d.value)]
            return len(hits) >= rule.n
        return False
