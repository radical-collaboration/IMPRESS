"""The Decision union and the observation a policy sees.

`CampaignObservation` is the SAME object passed to `ControlPolicy.decide` and returned by
the control plane's `observe()` - that symmetry is what makes control model C not a
special case (Part B doc 06).
"""
from __future__ import annotations

from typing import Any, Literal, Union

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


class ComposeAndRun(BaseModel):
    kind: Literal["compose_and_run"] = "compose_and_run"
    intent: ExperimentIntent
    rationale: str = ""


class Backtrack(BaseModel):
    kind: Literal["backtrack"] = "backtrack"
    node_id: str
    rationale: str = ""


class RequestHuman(BaseModel):
    kind: Literal["request_human"] = "request_human"
    question: str
    context: dict[str, Any] = Field(default_factory=dict)


class Stop(BaseModel):
    kind: Literal["stop"] = "stop"
    reason: str


Decision = Union[ComposeAndRun, Backtrack, RequestHuman, Stop]


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
    #: Bare tool ids. Superseded by `toolkit` below and removed in phase 11: a reasoner given
    #: only ids cannot choose by output type, cannot see a parameter's range and cannot know
    #: which parameters are frozen, so it guesses or hardcodes - which is backlog H3.
    available_tools: list[str] = Field(default_factory=list)
    #: The Toolkit as a reasoner may see it: typed ports, parameter ranges, what each
    #: parameter trades, which are frozen and why, and the toolkits' own skill documents.
    toolkit: ToolkitView | None = None
    #: The applied Spec. Carried so a Planner plans against objectives the executor has
    #: actually applied rather than against ones it imagined, and so an external caller sees
    #: the same Spec the in-process roles do (ADR 0007's parity of evidence).
    spec: Spec | None = None
    last_rejection: ValidationFailure | None = None
