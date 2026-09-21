"""The Decision union and the observation a policy sees.

`CampaignObservation` is the SAME object passed to `ControlPolicy.decide` and returned by
the control plane's `observe()` - that symmetry is what makes control model C not a
special case (Part B doc 06).
"""
from __future__ import annotations

import itertools
from typing import Any, Literal, Union

from pydantic import BaseModel, Field

from .budget import BudgetLedger
from .pareto import Objective
from .tree import DesignNode

_dids = itertools.count(1)


def new_decision_id() -> str:
    return f"d{next(_dids):06d}"


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


class PopulationStats(BaseModel):
    size: int = 0
    live: int = 0
    failed: int = 0
    suspect: int = 0
    diversity: float | None = None
    metric_means: dict[str, float] = Field(default_factory=dict)


class CampaignObservation(BaseModel):
    campaign_id: str
    cycle: int
    goal: str
    objectives: list[Objective] = Field(default_factory=list)
    pareto_front: list[DesignNode] = Field(default_factory=list)
    population: PopulationStats = Field(default_factory=PopulationStats)
    recent: list[DesignNode] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    budget: BudgetLedger = Field(default_factory=BudgetLedger)
    available_tools: list[str] = Field(default_factory=list)
    last_rejection: ValidationFailure | None = None
