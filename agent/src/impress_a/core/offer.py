"""What IMPRESS-A tells a caller before it is launched.

IMPRESS-A is a callable tool (decision 0001), and the class of caller that matters is one
orchestrating many heterogeneous workflows toward a higher goal. Such a caller has two
questions it must answer *before* it launches anything - what will one invocation cost, so it
can size its own budget, and which campaign goals can this workflow address, so it can decide
where to put it - and until now it could ask neither. `impress-a tools` prints four fields per
tool; `preflight` answers whether the machine can run the binaries; nothing priced a campaign,
and nothing checked a goal against a toolkit before a run.

These types are the answer, and they live in `core` for the same reason `CampaignObservation`
does: an offer crosses a process boundary. The computation is in `runtime/offer`, because its
inputs are a `Registry` and a `CampaignSpec` and only `runtime` can see both.

**An offer is DECLARED, and says so.** Every figure traces to a `cost_model` in a tool spec,
and those sit multiples above measurement deliberately, because they feed gates that *refuse*
graphs - so a conservative estimate is the correct thing for them to be and the wrong thing to
mistake for a prediction. `CostBasis` carries that statement, `CostRange` carries a floor and
a ceiling rather than a point, and `CampaignOffer.warnings` names what the figures cannot see.
The one that matters most: the estimator is **parameter-blind**, so raising a breadth knob
buys N draws and moves no priced number (backlog H10).

What an offer is NOT is a promise about science. It answers whether a goal is *measurable* by
this toolkit, never whether it is *achievable*: the scientific target - the ligand, the
contig, the input structure - lives in `CampaignSpec.params` and in nothing the toolkit
declares. `GoalOffer.not_answerable_here` says so in the payload, because a caller reading
"`complex_plddt` is producible" as "this workflow can design my binder" is the one
misunderstanding this file exists to prevent.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CostRange(BaseModel):
    """One budget dimension, as a floor and a ceiling rather than a point.

    A range because a caller can use one: an enclosing manager that expresses a request as
    bounds lets its own scheduler pick the operating point from its own learned costs, which
    will be better than anything declared here. A point estimate would throw that away and
    claim a precision the declared figures do not have.
    """

    #: The minimal producing chain at one lineage, one cycle: the least this can cost and
    #: still answer anything.
    floor: float
    #: The declared chain at the declared width, one cycle.
    expected: float
    #: The most the campaign can spend in this dimension, ever. Where the campaign declares a
    #: budget this is EXACT rather than estimated - admission reserves against
    #: `limits - spent - reserved` and refuses what does not fit, and settlement charges no
    #: more than was reserved, so spending cannot pass the limit. Without a declared budget it
    #: is `max_cycles x expected`, which is an estimate like any other.
    ceiling: float
    #: The dimension's own name, as the budget ledger and the tool specs spell it
    #: (`gpu_hours`, `cpu_hours`). No conversion is applied anywhere in this file.
    unit: str
    #: True when `ceiling` came from the campaign's own declared budget.
    bounded_by_budget: bool = False


class CostBasis(BaseModel):
    """Where the numbers came from, stated so they cannot be mistaken for measurement."""

    kind: Literal["declared_cost_model"] = "declared_cost_model"
    #: measured/declared per tool, and ONLY from a `validate-tasks` artifact a caller passed
    #: in. Empty means nobody measured anything, not that the figures agree with reality.
    measured_ratio: dict[str, float] = Field(default_factory=dict)
    measured_source: str = ""
    notes: list[str] = Field(default_factory=list)


class ChainOffer(BaseModel):
    """Which tools would run, how many times, and under what scrutiny."""

    #: The campaign's declared chain, narrowed to tools the toolkit actually has.
    declared: list[str] = Field(default_factory=list)
    #: The smallest chain that reports every declared objective's metric.
    minimal: list[str] = Field(default_factory=list)
    #: P6 tools, which are inlined by the composer and never scheduled.
    inlined: list[str] = Field(default_factory=list)
    replicas: int = 1
    concurrency: int = 1
    #: Composed, not guessed: `replicas x` the non-P6 chain.
    graph_nodes: int = 0
    #: Shape-only identity for the interlock, and whether this site already trusts it.
    pattern_signature: str = ""
    trusted: bool = False
    #: An untrusted pattern is forced through a dry run and capped at this fraction of the
    #: budget still available - so a first cycle can be refused outright at this width.
    first_cycle_dry_run: bool = True
    cost_cap_fraction: float | None = None


class ResourceOffer(BaseModel):
    """What one invocation needs at once - a ceiling, not a reservation.

    A lineage is serial, so these are upper bounds over the chain rather than sums along it.
    """

    gpus: int = 0
    cores: int = 1
    nodes: int = 1
    walltime_s_per_cycle: int = 0
    #: Including the engine's startup and teardown bounds, which are campaign-level costs a
    #: per-cycle figure cannot see - and teardown is the expensive end: one reference job sat
    #: 60 minutes in `flow.shutdown()` after its science was done.
    walltime_s_ceiling: int = 0


class AcceptanceBar(BaseModel):
    """A threshold the toolkit itself believes in, read from a tool's own acceptance gate."""

    tool: str
    metric: str
    min: float | None = None
    max: float | None = None


class RootPort(BaseModel):
    """A required input no tool in the chain produces - so the caller must supply it."""

    tool: str
    port: str
    type: str


class OperatorParam(BaseModel):
    """A parameter a campaign may set and a reasoner may not, with the spec's own reason."""

    tool: str
    name: str
    reason: str


class GoalOffer(BaseModel):
    """Which goals this toolkit can address, and - the load-bearing half - which it cannot."""

    #: Every metric some enabled tool declares it reports. The vocabulary a caller's own goal
    #: metric has to be drawn from for anything to measure it.
    addressable_metrics: list[str] = Field(default_factory=list)
    #: metric -> the tools reporting it, earliest in the declared chain first.
    producers: dict[str, list[str]] = Field(default_factory=dict)
    #: Of the campaign's own declared objectives, which can be measured and which cannot.
    #: The same predicate the Specifier's `unproducible` and the executor's coverage check
    #: apply per cycle - asked once, before anything runs.
    producible_objectives: list[str] = Field(default_factory=list)
    unproducible_objectives: list[str] = Field(default_factory=list)
    acceptance_thresholds: list[AcceptanceBar] = Field(default_factory=list)
    #: Only integrity failures count against a pattern's trust (decision 0013); an acceptance
    #: failure still FAILs the node. A caller choosing a threshold should know which it gets.
    integrity_gated_metrics: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    #: An objective with a `min` or a `max` can be satisfied, and so can end a campaign. One
    #: with only a direction can be RANKED but never satisfied - only unmeasured - because
    #: satisfaction is a bound test and direction does not bound anything. A caller that wants
    #: a stopping condition has to give its objective a threshold, and this split is where it
    #: can see whether it did.
    bounded_objectives: list[str] = Field(default_factory=list)
    unbounded_objectives: list[str] = Field(default_factory=list)
    producible_artifact_types: list[str] = Field(default_factory=list)
    #: The non-identity unification rules, so a caller sees that a Complex satisfies a
    #: requirement for a Backbone.
    unifications: list[tuple[str, str]] = Field(default_factory=list)
    unsatisfied_root_ports: list[RootPort] = Field(default_factory=list)
    operator_only_parameters: list[OperatorParam] = Field(default_factory=list)
    not_answerable_here: list[str] = Field(default_factory=list)


class CampaignOffer(BaseModel):
    """Everything IMPRESS-A can tell a caller about an invocation it has not yet made."""

    campaign_id: str
    goal_text: str
    offered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    toolkits: list[str] = Field(default_factory=list)
    chain: ChainOffer = Field(default_factory=ChainOffer)
    #: Every dimension the chain's cost models or the campaign's budget names, plus
    #: `wall_hours`.
    cost: dict[str, CostRange] = Field(default_factory=dict)
    resources: ResourceOffer = Field(default_factory=ResourceOffer)
    #: The bounds the campaign drives its own loop by: max_cycles, max_runs, max_attempts,
    #: target_front, stagnation_limit.
    loop: dict[str, int] = Field(default_factory=dict)
    #: How often a running campaign will report, if a caller attaches a sink. Declared here
    #: because a caller's own staleness bound has to be a multiple of it.
    report_interval_s: float = 30.0
    supports_pause: bool = True
    #: Pause gates ADMISSION. In-flight runs are allowed to finish, because cancellation is
    #: advisory and a reclaimed GPU is not something this system can promise - so a paused
    #: campaign keeps spending for up to one cycle.
    pause_semantics: Literal["admission_only"] = "admission_only"
    #: The campaign's own declared budget, verbatim. A caller's limit, if it sets one, should
    #: narrow this rather than be enforced from outside: inside the campaign it becomes the
    #: thing gate 5 and the interlock refuse work against, before a task runs.
    own_budget: dict[str, float] = Field(default_factory=dict)
    goals: GoalOffer = Field(default_factory=GoalOffer)
    basis: CostBasis = Field(default_factory=CostBasis)
    #: What these figures cannot see. Not decoration: each entry is a recorded defect, and a
    #: caller sizing a budget without reading them will be wrong in a direction this file
    #: could have named.
    warnings: list[str] = Field(default_factory=list)

    def bounds(self) -> dict[str, tuple[float, float]]:
        """Every dimension as `(floor, ceiling)`, for a caller that sizes from ranges."""
        return {dim: (r.floor, r.ceiling) for dim, r in self.cost.items()}
