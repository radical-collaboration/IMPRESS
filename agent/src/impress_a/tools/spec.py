"""ToolSpec - the single source of truth about a tool.

Read by four consumers: composer, validator, budget guard, task agent. Declarative so it
is reviewable by a scientist in a pull request and importable without pulling a heavy
dependency (Part C decision 0011).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..core.types import ArtifactType, Pattern


class ResourceShape(BaseModel):
    nodes: int = 1
    gpus: int = 0
    cores: int = 1
    ranks: int = 1
    walltime_s: int = 60


class ParameterSpec(BaseModel):
    type: Literal["int", "float", "str", "bool"]
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: list[Any] | None = None
    trades: str = ""
    #: Non-empty = the reason a REASONER may not propose this parameter, although the
    #: campaign may still declare it. The third state between varyable and
    #: `frozen_parameters`, and the two existing ones could not express it:
    #:
    #: * varyable - the campaign sets it, and so may a Planner. The refinement knobs.
    #: * `frozen_parameters` - nobody sets it; gate 3 refuses a graph carrying it, so a
    #:   campaign cannot declare it either.
    #: * `operator_only` - the campaign's to set, a reasoner's to leave alone.
    #:
    #: It exists because `mock_rfd3_design.difficulty` is the mock lab's independent
    #: VARIABLE, and `OraclePlanner` shows a live model every tunable parameter with its
    #: range and its `trades` sentence - "how hard this campaign is", 0.0 to 1.0. A model
    #: asked to satisfy the objectives would turn it down, `_apply_campaign_defaults` would
    #: let it ("the policy always wins on any key it did set"), and the hard arm of the
    #: experiment would quietly become the easy one. The same shape covers any campaign
    #: configuration a reasoner should not re-litigate - a ligand, an input path, a contig -
    #: which is the distinction `_apply_campaign_defaults` already draws in prose: "a policy
    #: chooses how to explore, not what molecule the campaign is about".
    #:
    #: Enforced once, in `tools/view.card_for`, by reporting it under `TaskCard.frozen`
    #: instead of `TaskCard.parameters`. Everything downstream already honours that:
    #: `_knobs.tunable` skips it, `OraclePlanner` leaves it out of the prompt and refuses a
    #: reply naming it. Gate 3 reads `frozen_parameters`, which this is not, so the campaign
    #: path is untouched.
    operator_only: str = ""

    def validate_value(self, v: Any) -> str | None:
        """Return an error string, or None if acceptable."""
        if self.type == "int" and not isinstance(v, int):
            return f"expected int, got {type(v).__name__}"
        if self.type == "float" and not isinstance(v, (int, float)):
            return f"expected float, got {type(v).__name__}"
        if self.choices is not None and v not in self.choices:
            return f"{v!r} not in {self.choices}"
        if isinstance(v, (int, float)):
            if self.min is not None and v < self.min:
                return f"{v} < min {self.min}"
            if self.max is not None and v > self.max:
                return f"{v} > max {self.max}"
        return None


class PortSpec(BaseModel):
    type: ArtifactType
    required: bool = True


class GateSpec(BaseModel):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)
    role: Literal["integrity", "acceptance"] = "integrity"   # see core/qc.GateResult.role


class CostModel(BaseModel):
    """Per unit of work. Keys must match budget ledger dimensions."""

    unit: str = "invocation"
    cost: dict[str, float] = Field(default_factory=dict)
    #: Consumption per SECOND, for open-ended work - the outline's "burn rate". Distinct from
    #: `cost`, which is per invocation: a tool that runs until told to stop has no per-call
    #: figure, and a tool that runs to completion has no meaningful rate.
    burn: dict[str, float] = Field(default_factory=dict)
    #: The most one invocation may ever commit, per dimension. The effective commitment is the
    #: SMALLER of this and any workflow maximum the campaign declared, which is what the
    #: outline means by "the smaller value of the optionally configured workflow maximum and
    #: the per-stage hard limit".
    max_commitment: dict[str, float] = Field(default_factory=dict)


class GPUPortability(BaseModel):
    cuda: str = "proven"       # proven | plausible | unproven | n/a
    hip: str = "unproven"
    sycl_xpu: str = "unproven"

    def runs_on(self, api: str) -> bool:
        return getattr(self, api, "unproven") in ("proven", "plausible", "n/a")


class ToolSpec(BaseModel):
    id: str
    toolkit: str
    version: str = "0"
    pattern: Pattern
    inputs: dict[str, PortSpec] = Field(default_factory=dict)
    outputs: dict[str, PortSpec] = Field(default_factory=dict)
    resources: ResourceShape = Field(default_factory=ResourceShape)
    gpu_portability: GPUPortability = Field(default_factory=GPUPortability)
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    frozen_parameters: dict[str, str] = Field(default_factory=dict)  # name -> reason
    # The metric names this tool's agent reports. Declared, not inferred: the composer has
    # no other way to know what a graph can measure, and inferring it from `qc_gates` reads
    # a tool that emits a metric it does not gate as producing nothing. That inference was
    # tried first and warned falsely on the mock campaign, whose tools emit ddg/iptm/
    # sc_rmsd and gate on none of them. Used by
    # `runtime/executor._objectives_without_a_producer` to say when an admitted graph
    # cannot inform an objective it was composed for.
    metrics: list[str] = Field(default_factory=list)
    qc_gates: list[GateSpec] = Field(default_factory=list)
    cost_model: CostModel = Field(default_factory=CostModel)
    agent: Literal["deterministic", "llm"] = "deterministic"
    entry: str | None = None  # dotted path to the task-agent class

    @model_validator(mode="after")
    def _defaults_within_range(self) -> ToolSpec:
        for pname, p in self.parameters.items():
            if p.default is not None and (err := p.validate_value(p.default)):
                raise ValueError(f"{self.id}.{pname}: default invalid - {err}")
        overlap = set(self.parameters) & set(self.frozen_parameters)
        if overlap:
            raise ValueError(f"{self.id}: {overlap} both varyable and frozen")
        for dim, cap in self.cost_model.max_commitment.items():
            declared = self.cost_model.cost.get(dim)
            if declared is not None and cap < declared:
                raise ValueError(
                    f"{self.id}: max_commitment {dim}={cap} is below its own declared cost "
                    f"{declared} - a cap a single invocation cannot satisfy refuses every "
                    f"graph containing this tool")
        if self.pattern is Pattern.P1 and self.resources.gpus == 0:
            raise ValueError(f"{self.id}: P1 declared but resources.gpus == 0")
        # An acceptance threshold must not be the only thing that notices a value is
        # missing: that is how a fabricated 0.0 passed for a measurement (decision 0013).
        reported = {m for g in self.qc_gates
                    if g.id == "metrics_reported" and g.role == "integrity"
                    for m in g.params.get("metrics", [])}
        for g in self.qc_gates:
            if g.role == "acceptance" and g.id == "metric_in_range" \
                    and g.params.get("metric") not in reported:
                raise ValueError(
                    f"{self.id}: acceptance gate on {g.params.get('metric')!r} needs an "
                    "integrity metrics_reported gate naming it")
        return self
