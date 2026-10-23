"""What a finished run looks like to whoever asked for it.

`ExecutionResults` lives in `exec/` and holds whatever the adapters returned. A policy may
not import `exec` (ADR 0010), which is why `interpret` has always taken its results
argument unannotated - the honest type was out of reach. `RunOutcome` is that type: a
projection of `ExecutionResults` into `core`, carrying only what a reasoner needs to
decide what to do next.

A PROJECTION, never a replacement. `ExecutionResults` stays the in-process type; narrowing
it away would break every caller that legitimately works inside the execution layer.

Everything here is serializable on purpose. The reasoner is meant to be able to live in
another process, and a type that only works when both ends share memory would quietly
make that impossible.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from .artifacts import ArtifactRef
from .qc import QCReport, QCVerdict


class RunState(str, Enum):
    ADMITTED = "admitted"      # passed every gate, budget reserved, not yet dispatched
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (RunState.DONE, RunState.FAILED, RunState.CANCELLED)


class TaskOutcome(BaseModel):
    """One task within a run. Outputs are typed references, never payloads."""

    task_id: str
    tool: str
    metrics: dict[str, float] = Field(default_factory=dict)
    qc: QCReport = Field(default_factory=QCReport)
    cost: dict[str, float] = Field(default_factory=dict)
    outputs: dict[str, ArtifactRef] = Field(default_factory=dict)


class RunOutcome(BaseModel):
    """One finished experiment."""

    run_id: str
    graph_id: str = ""
    state: RunState = RunState.DONE
    signature: str = ""
    #: DesignNode ids this run produced - one per replica lineage.
    nodes: list[str] = Field(default_factory=list)
    #: Port -> handle, merged across the run's tasks. What a reasoner asks for when it
    #: wants the thing a run produced rather than the numbers about it.
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    qc: QCReport = Field(default_factory=QCReport)
    cost: dict[str, float] = Field(default_factory=dict)
    failures: dict[str, str] = Field(default_factory=dict)
    tasks: list[TaskOutcome] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def all_gates_passed(self) -> bool:
        return self.ok and all(t.qc.verdict is QCVerdict.PASS for t in self.tasks)

    def merged_metrics(self) -> dict[str, float]:
        return dict(self.metrics)


class RunStatus(BaseModel):
    """Where a run has got to. Cheap to ask for and safe to ask for repeatedly."""

    run_id: str
    state: RunState
    graph_id: str = ""
    signature: str = ""
    trusted: bool = False
    turn: int = 0
    estimate: dict[str, float] = Field(default_factory=dict)
