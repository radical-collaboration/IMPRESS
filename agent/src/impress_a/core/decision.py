"""The Decision union and the observation a policy sees.

`CampaignObservation` is the SAME object passed to `ControlPolicy.decide` and returned by
the control plane's `observe()` - that symmetry is what makes control model C not a
special case (Part B doc 06).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .budget import BudgetLedger
from .ids import counter
from .pareto import Objective
from .spec import Spec
from .toolkit import ToolkitView
from .tree import DesignNode

new_decision_id = counter("d")


class ExperimentIntent(BaseModel):
    """ABSTRACT intent. Not a DAG - turning intent into a validated graph is the
    manager's job, which keeps policies out of tool-invocation details."""

    goal: str
    toolkit_hint: str | None = None
    stages: list[str] = Field(default_factory=list)  # tool ids, in order
    params: dict[str, Any] = Field(default_factory=dict)
    parent_node: str | None = None
    replicas: int = 1


class RequestHuman(BaseModel):
    """A question a campaign cannot answer for itself.

    The one member of the deleted `Decision` union that survives, because it is not a
    decision: it is the payload of `CampaignSession.request_human`, a live operation that
    parks a campaign and records the question, and `control/plane.py` exposes it. The others -
    `ComposeAndRun`, `Backtrack`, `Stop` and the `Decision` union itself - were what a
    `decide` policy RETURNED, and in this design none of them is anything a reasoner returns:
    a Stage is what a Planner emits, a Spec revision is what a Specifier emits, stopping is
    the executor's call on the Listener's request, and branching from an earlier node is
    `SpecObjective.parent_node`.
    """

    kind: Literal["request_human"] = "request_human"
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class ValidationFailure(BaseModel):
    gate: str
    node: str | None = None
    reason: str
    detail: dict[str, Any] = Field(default_factory=dict)
    #: True when the graph is fine and only the moment is wrong - resources are
    #: contended right now. Gates 1-4 are deterministic properties of the graph and are
    #: never transient. Without this a policy answers contention by mutilating its
    #: intent (dropping replicas, truncating stages) in response to what OTHER runs are
    #: consuming, which reads as the policy quietly degrading.
    transient: bool = False


class PopulationStats(BaseModel):
    size: int = 0
    live: int = 0
    failed: int = 0
    suspect: int = 0
    diversity: float | None = None
    metric_means: dict[str, float] = Field(default_factory=dict)


class CampaignObservation(BaseModel):
    campaign_id: str
    cycle: int                 # turn of the loop
    #: Watermark into absorption order. `recent` holds what landed after the consumer's
    #: previous watermark, which is what "recent" has to mean once more than one
    #: experiment can be in flight.
    seq: int = 0
    goal: str
    objectives: list[Objective] = Field(default_factory=list)
    pareto_front: list[DesignNode] = Field(default_factory=list)
    population: PopulationStats = Field(default_factory=PopulationStats)
    recent: list[DesignNode] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    budget: BudgetLedger = Field(default_factory=BudgetLedger)
    #: The Toolkit as a reasoner may see it: typed ports, parameter ranges, what each
    #: parameter trades, which are frozen and why, and the toolkits' own skill documents.
    toolkit: ToolkitView | None = None
    #: The campaign's declared chain, in the campaign's own ORDER. `toolkit` carries the same
    #: tools but keyed and sorted by id, and order is not decoration here: a Planner wires a
    #: port to the nearest preceding producer, which is the rule the composer applies to a
    #: linear chain, and alphabetical order makes `mock_design` precede `mock_generate` - so
    #: the sequence step would be planned before the backbone it consumes. An in-process pair
    #: receives the chain through `ReasonerOptions.stages`; before this field a pair driving a
    #: campaign over a socket had no way to learn it at all, which is the parity of evidence
    #: ADR 0007 requires of every adapter.
    stages: list[str] = Field(default_factory=list)
    #: How many designs over every bounded bar the campaign asked for; 0 means one is enough.
    #: Carried for the same reason `stages` is: an external caller builds its `Goal` from this
    #: observation and from nothing else, so without this field a served campaign's Specifier
    #: would use the default while an in-process one used the spec's. For the four-arm
    #: experiment that is a difference between arms which is not the model - arm C would stop
    #: at one design while A, B and D ran to ten - which is precisely the confound
    #: `impress-a compare`'s one-variable guard exists to refuse (backlog G11).
    target_front: int = 0
    #: How the campaign is DRIVEN, carried for the same reason `target_front` is. A remote
    #: driver builds itself from this observation and from nothing else, and
    #: `cli.control_campaign` had no way to learn either number - so it drove with
    #: `max_turns=10_000` while every in-process arm used the spec's `max_cycles`. In the
    #: four-arm experiment that is arm C running until its budget or its wall clock ran out
    #: while A, B and D stopped at six cycles: a difference between arms which is not the
    #: model, which is what `impress-a compare`'s one-variable guard exists to refuse.
    #: 0 means "not declared" and leaves the driver's own default, so no existing caller moves.
    max_cycles: int = 0
    max_attempts: int = 0
    #: The applied Spec. Carried so a Planner plans against objectives the executor has
    #: actually applied rather than against ones it imagined, and so an external caller sees
    #: the same Spec the in-process roles do (ADR 0007's parity of evidence).
    spec: Spec | None = None
    #: Task ids that are still pending or deployed and whose EVERY objective is now DELETED.
    #: Computed by the executor, which is the only thing that can see both the task registry
    #: and the applied Spec. Carried here rather than behind a new protocol operation, because
    #: the observation already crosses the boundary and ADR 0007 would otherwise be in play.
    orphan_tasks: list[str] = Field(default_factory=list)
    last_rejection: ValidationFailure | None = None
