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
from .pareto import Direction, Objective
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
    #: Independent lineages per experiment, as the campaign declared them. Carried for the
    #: same reason, and because a remotely driven arm composing a different width from the
    #: in-process ones is backlog G13's confound arriving by a second route.
    replicas: int = 0
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

    def digest(self, *, status: str = "running",
               stop_reason: str = "") -> CampaignDigest:
        """Project this observation into what an outside caller is told.

        A projection of an existing operation's return value, not a new operation, so ADR
        0007 stays out of play for the same reason adding a field here does. It lives on the
        observation because only `core` knows what an observation contains - the inverse of
        `ExecutionResults.to_outcome`'s own argument for living in the execution layer.

        What it drops is the point. The full observation carries the whole `ToolkitView` -
        every `TaskCard` plus each toolkit's entire `SKILL.md` text - the applied `Spec`, and
        every `DesignNode` on the front with its properties, artifacts and QC report, rebuilt
        on every call. None of that changes from cycle to cycle, and a caller that needed the
        toolkit was told it once, at calltime, by `impress-a offer`. Sending it again every
        thirty seconds would be sending a campaign's static description as if it were news.

        Each digest also stands alone rather than extending the last one, because the stores
        a caller receives these through are last-value-wins per workflow: only the final one
        is guaranteed to be read, so none of them may be a delta.
        """
        front_satisfying = sum(
            1 for n in self.pareto_front
            if all(o.satisfied_by(n.metric(o.name)) for o in self.objectives
                   if o.min is not None or o.max is not None))
        best: dict[str, float] = {}
        for o in self.objectives:
            values = [v for n in self.pareto_front if (v := n.metric(o.name)) is not None]
            if values:
                best[o.name] = min(values) if o.direction is Direction.MIN else max(values)
        return CampaignDigest(
            campaign_id=self.campaign_id, cycle=self.cycle, seq=self.seq,
            status=status, stop_reason=stop_reason,
            front_size=len(self.pareto_front),
            front_satisfying=front_satisfying,
            target_front=self.target_front,
            best=best,
            population=self.population,
            spend=dict(self.budget.spent),
            spend_measured=dict(self.budget.spent_measured),
            limits=dict(self.budget.limits),
            remaining={d: self.budget.remaining(d) for d in self.budget.limits},
            in_flight={d: self.budget.reserved(d) for d in self.budget.limits},
            orphan_tasks=len(self.orphan_tasks),
            last_rejection_gate=(self.last_rejection.gate if self.last_rejection else ""),
            last_rejection_reason=(self.last_rejection.reason if self.last_rejection else ""),
            front_node_ids=[n.id for n in self.pareto_front],
        )


class CampaignDigest(BaseModel):
    """What a campaign tells a caller outside its own process, once per absorbed cycle.

    Transport-neutral on purpose: it names no enclosing manager's vocabulary, so the same
    digest serves an in-process sink, an HTTP poller and a subprocess reporting over Redis,
    and adding a second superstrate costs an adapter rather than a second payload.

    Two spending figures, under distinct names, because they are genuinely two numbers.
    `spend` is DECLARED - what `reserve` and `settle` work in, and what gate 5 refuses
    against, so it is correctly pessimistic. `spend_measured` is what the tools measured. A
    caller charging its own budget wants the measured one; a caller asking why a campaign
    stopped wants the declared one, because that is what the ledger ran out of.
    """

    campaign_id: str
    cycle: int = 0
    #: Absorption watermark. Monotone, and the signal that something new has landed - which
    #: is why a bridge reports on it advancing rather than on `cycle`, incremented at
    #: DISPATCH and so counting submissions rather than results.
    seq: int = 0
    status: str = "running"          # starting | running | stopped | aborted
    stop_reason: str = ""
    front_size: int = 0
    #: Front members satisfying every BOUNDED objective - what `target_front` counts toward.
    #: An unbounded objective is excluded because it can never be unsatisfied, only
    #: unmeasured, so counting it would make every front member look like a success.
    front_satisfying: int = 0
    target_front: int = 0
    #: objective name -> the best value on the front, by that objective's own direction.
    best: dict[str, float] = Field(default_factory=dict)
    population: PopulationStats = Field(default_factory=PopulationStats)
    spend: dict[str, float] = Field(default_factory=dict)
    spend_measured: dict[str, float] = Field(default_factory=dict)
    limits: dict[str, float] = Field(default_factory=dict)
    remaining: dict[str, float] = Field(default_factory=dict)
    in_flight: dict[str, float] = Field(default_factory=dict)
    orphan_tasks: int = 0
    #: A refusal a caller should be able to see without reading provenance.
    last_rejection_gate: str = ""
    last_rejection_reason: str = ""
    #: Kept so a caller can fetch the artifacts later through the control plane; the nodes
    #: themselves are deliberately absent.
    front_node_ids: list[str] = Field(default_factory=list)

    @property
    def progress(self) -> float:
        """Fraction of the asked-for front that is satisfied, in [0, 1].

        The one scalar a caller can rank arms by. Degenerate where a campaign declares no
        bounded objective - nothing can ever be satisfied, so this is 0.0 until the front is
        non-empty and then 1.0 - and that is stated rather than smoothed over, because the
        fix is for the caller to give its objectives thresholds.
        """
        if self.target_front <= 0:
            return 1.0 if self.front_satisfying else 0.0
        return min(1.0, self.front_satisfying / self.target_front)
