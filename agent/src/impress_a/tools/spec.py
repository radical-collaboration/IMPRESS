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


class CostModel(BaseModel):
    """Per unit of work. Keys must match budget ledger dimensions."""

    unit: str = "invocation"
    cost: dict[str, float] = Field(default_factory=dict)


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
    qc_gates: list[GateSpec] = Field(default_factory=list)
    cost_model: CostModel = Field(default_factory=CostModel)
    agent: Literal["deterministic", "llm"] = "deterministic"
    entry: str | None = None  # dotted path to the task-agent class

    @model_validator(mode="after")
    def _defaults_within_range(self) -> "ToolSpec":
        for pname, p in self.parameters.items():
            if p.default is not None and (err := p.validate_value(p.default)):
                raise ValueError(f"{self.id}.{pname}: default invalid - {err}")
        overlap = set(self.parameters) & set(self.frozen_parameters)
        if overlap:
            raise ValueError(f"{self.id}: {overlap} both varyable and frozen")
        if self.pattern is Pattern.P1 and self.resources.gpus == 0:
            raise ValueError(f"{self.id}: P1 declared but resources.gpus == 0")
        return self
