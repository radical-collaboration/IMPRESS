"""Task agents: pre-process -> parameterize -> execute -> post-process.

This is where Part A's silent-failure defence lives. The policy may reason loosely, but
the boundary at which a tool's output enters campaign state is always guarded by code
that knows that tool's specific failure modes.

`execute()` is deliberately not overridden by tool adapters - pattern dispatch belongs to
the execution layer, and an adapter scheduling its own work would bypass the P6-inline
and P4-ledger rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.qc import QCReport
from . import gates
from .spec import ToolSpec


@dataclass
class TaskRequest:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    node_id: str | None = None


@dataclass
class TaskResult:
    tool: str
    outputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    qc: QCReport = field(default_factory=QCReport)
    cost: dict[str, float] = field(default_factory=dict)


class TaskAgent:
    """Base class. Subclasses override pre_process/parameterize/run/post_process."""

    def __init__(self, spec: ToolSpec):
        self.spec = spec

    # -- phases ------------------------------------------------------------
    async def pre_process(self, req: TaskRequest) -> TaskRequest:
        return req

    def parameterize(self, req: TaskRequest) -> dict[str, Any]:
        """Resolve declared defaults, reject out-of-range and frozen parameters."""
        resolved = {k: p.default for k, p in self.spec.parameters.items()
                    if p.default is not None}
        for k, v in req.params.items():
            if k in self.spec.frozen_parameters:
                raise ValueError(
                    f"{self.spec.id}.{k} is frozen: {self.spec.frozen_parameters[k]}")
            if k not in self.spec.parameters:
                raise ValueError(f"{self.spec.id}: unknown parameter {k!r}")
            if err := self.spec.parameters[k].validate_value(v):
                raise ValueError(f"{self.spec.id}.{k}: {err}")
            resolved[k] = v
        return resolved

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def post_process(self, req: TaskRequest, raw: dict[str, Any]) -> TaskResult:
        """Extract metrics and ENFORCE QC gates. Never skippable."""
        qc = QCReport()
        for g in self.spec.qc_gates:
            qc.add(gates.get(g.id)(raw, g.params))
        return TaskResult(tool=self.spec.id,
                          outputs=raw.get("outputs", {}),
                          metrics=raw.get("metrics", {}),
                          qc=qc,
                          cost=dict(self.spec.cost_model.cost))

    # -- driver ------------------------------------------------------------
    async def __call__(self, req: TaskRequest) -> TaskResult:
        req = await self.pre_process(req)
        params = self.parameterize(req)
        raw = await self.run(req, params)
        return await self.post_process(req, raw)

    async def dry_run(self, req: TaskRequest) -> None:
        """Prove parameterization works WITHOUT executing (composition gate)."""
        req = await self.pre_process(req)
        self.parameterize(req)


class EchoTaskAgent(TaskAgent):
    """Fallback agent used when a spec declares no entry point."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        return {"result": f"{self.spec.id}", "outputs": {}, "metrics": {}}
