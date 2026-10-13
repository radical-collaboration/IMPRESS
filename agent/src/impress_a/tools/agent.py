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
from pathlib import Path
from typing import Any

from ..core.artifacts import ArtifactRef
from ..core.qc import QCReport
from . import gates
from .spec import ToolSpec


@dataclass
class TaskRequest:
    tool: str
    params: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    node_id: str | None = None
    seed: int | None = None
    #: Where this task may write. Defaults to the process CWD - see
    #: `_subprocess.workdir_for`, which is what every real adapter uses.
    workdir: str | None = None


@dataclass
class TaskResult:
    tool: str
    #: Typed, serializable handles - never raw payloads and never bare path strings.
    #: A bare string said nothing about what it was or whether the bytes behind it were
    #: still the ones the campaign reasoned about, and it could not cross a process
    #: boundary meaningfully. See `core.artifacts.ArtifactRef`.
    outputs: dict[str, ArtifactRef] = field(default_factory=dict)
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
        # A tool that declares a seed gets this lineage's draw unless the policy named
        # one explicitly. This is what makes `replicas: N` N independent samples for a
        # real stochastic tool rather than N copies of one design.
        if req.seed is not None and "seed" in self.spec.parameters \
                and "seed" not in req.params:
            resolved["seed"] = req.seed % (2 ** 31)
        return resolved

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _as_artifacts(self, outputs: dict[str, Any]) -> dict[str, ArtifactRef]:
        """Turn what `run()` returned into typed handles.

        The TYPE comes from the spec's declared output port, never from the adapter, so
        a ref cannot disagree with the contract the composer type-checked the graph
        against. An adapter returning a `Path` is declaring a file - that is the signal,
        rather than guessing from whether a string happens to exist on disk.
        """
        refs: dict[str, ArtifactRef] = {}
        for name, produced in (outputs or {}).items():
            if isinstance(produced, ArtifactRef):
                refs[name] = produced
                continue
            port = self.spec.outputs.get(name)
            if port is None:
                # Undeclared output: the composer never type-checked it and nothing
                # downstream can consume it, so dropping it silently would hide a spec
                # bug. Carry it as an untyped value instead.
                raise ValueError(
                    f"{self.spec.id}: produced undeclared output {name!r}; "
                    f"declared: {sorted(self.spec.outputs)}")
            if isinstance(produced, Path):
                refs[name] = ArtifactRef(type=port.type,
                                         path=str(produced)).hash_file()
            else:
                refs[name] = ArtifactRef(type=port.type, value=produced)
        return refs

    async def post_process(self, req: TaskRequest, raw: dict[str, Any]) -> TaskResult:
        """Extract metrics and ENFORCE QC gates. Never skippable."""
        qc = gates.evaluate(self.spec, raw)
        return TaskResult(tool=self.spec.id,
                          outputs=self._as_artifacts(raw.get("outputs", {})),
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
