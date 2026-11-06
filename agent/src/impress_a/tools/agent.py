"""Task agents: pre-process -> parameterize -> execute -> post-process.

This is where Part A's silent-failure defence lives. The policy may reason loosely, but
the boundary at which a tool's output enters campaign state is always guarded by code
that knows that tool's specific failure modes.

`execute()` is deliberately not overridden by tool adapters - pattern dispatch belongs to
the execution layer, and an adapter scheduling its own work would bypass the P6-inline
and P4-ledger rules.
"""
from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    #: Upstream payloads, keyed by this tool's own declared input PORT where the composer
    #: wired one, and by `dep{i}` for an ordering-only edge with no typed port behind it.
    inputs: dict[str, Any] = field(default_factory=dict)
    #: port -> the UPSTREAM output port it was wired to. The composer computed this and the
    #: validator type-checked it; without it an adapter has to guess which of a dep's outputs
    #: it was handed, which is what the scanning helper did.
    input_ports: dict[str, str] = field(default_factory=dict)
    node_id: str | None = None
    seed: int | None = None
    #: Where this task may write. Defaults to the process CWD - see
    #: `_subprocess.workdir_for`, which is what every real adapter uses.
    workdir: str | None = None

    def input_ref(self, port: str) -> Any:
        """The artifact wired to one of this tool's declared input ports.

        Resolves BY PORT rather than by scanning, so a node with two typed inputs gets the
        right artifact on each. Returns `None` when nothing was wired, which a required port
        should never see: gate 1 refuses a graph whose required input has no producer.
        """
        payload = self.inputs.get(port)
        if not isinstance(payload, dict):
            return payload
        outputs = payload.get("outputs") or {}
        out_port = self.input_ports.get(port)
        if out_port and out_port in outputs:
            return outputs[out_port]
        # No recorded upstream port. A single-output producer is unambiguous; more than one
        # is a composer bug rather than something to guess at.
        return next(iter(outputs.values())) if len(outputs) == 1 else None


@dataclass
class TaskUsage:
    """What one task actually consumed. Measured, not declared.

    Backlog G8: `TaskResult.cost` has always been `dict(self.spec.cost_model.cost)` - a copy
    of the spec - and the job ledger recorded that same figure, so every cost number in the
    system was the admission estimate repeated back. Nothing timed a task. The consequences
    were measurable anyway, from outside: GPU-busy at most 17% of billed GPU time, CPU
    efficiency around 42%, three of four GPUs never holding work.

    Kept SEPARATE from `cost` rather than replacing it, which is the whole design decision
    here. The declared figure feeds gate 5 and the untrusted-pattern cap, and those REFUSE
    graphs - so it must stay conservative (every one is >=2.25x the worst task observed, on
    purpose) and must not drift toward measurement. Two numbers recorded beats one number
    quietly redefined.
    """

    started_at: str = ""
    finished_at: str = ""
    wall_s: float = 0.0
    #: Per-phase, so import time is separable from work. `import pyrosetta` alone took 471s
    #: off HDD-backed Lustre against a 300s budget - and a timeout names a budget, not a
    #: cause.
    phases: dict[str, float] = field(default_factory=dict)
    host: str = ""
    pid: int = 0
    cuda_visible_devices: str = ""

    def as_cost(self, gpus: int, cores: int) -> dict[str, float]:
        """Measured wall time projected onto the budget's own dimensions."""
        hours = self.wall_s / 3600.0
        out: dict[str, float] = {"wall_s": self.wall_s}
        if gpus:
            out["gpu_hours"] = round(hours * gpus, 6)
        if cores:
            out["cpu_hours"] = round(hours * cores, 6)
        return out


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
    #: DECLARED, from the spec. What the budget reserves and settles on - see `TaskUsage`.
    cost: dict[str, float] = field(default_factory=dict)
    #: MEASURED. For analysis, and for noticing that a declared figure has drifted below
    #: measurement, at which point gate 5 would start refusing real work.
    usage: TaskUsage = field(default_factory=TaskUsage)
    cost_measured: dict[str, float] = field(default_factory=dict)


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

    async def post_process(self, req: TaskRequest, raw: dict[str, Any],
                           usage: TaskUsage | None = None) -> TaskResult:
        """Extract metrics and ENFORCE QC gates. Never skippable."""
        qc = gates.evaluate(self.spec, raw)
        usage = usage or TaskUsage()
        return TaskResult(tool=self.spec.id,
                          outputs=self._as_artifacts(raw.get("outputs", {})),
                          metrics=raw.get("metrics", {}),
                          qc=qc,
                          cost=dict(self.spec.cost_model.cost),
                          usage=usage,
                          cost_measured=usage.as_cost(self.spec.resources.gpus,
                                                      self.spec.resources.cores))

    # -- driver ------------------------------------------------------------
    async def __call__(self, req: TaskRequest) -> TaskResult:
        """The four phases, timed.

        Timed HERE rather than around the whole dispatch, so the number is the agent's own
        work and not the backend's queue wait - the Deployer's `deployed_at` brackets that,
        and the two have to be distinguishable or "the task was slow" and "the task waited"
        read the same.
        """
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        phases: dict[str, float] = {}

        def _mark(name: str, since: float) -> float:
            now = time.monotonic()
            phases[name] = round(now - since, 6)
            return now

        mark = t0
        req = await self.pre_process(req)
        mark = _mark("pre_process", mark)
        params = self.parameterize(req)
        mark = _mark("parameterize", mark)
        raw = await self.run(req, params)
        mark = _mark("run", mark)

        usage = TaskUsage(
            started_at=started.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            wall_s=round(time.monotonic() - t0, 6),
            phases=phases,
            host=socket.gethostname(),
            pid=os.getpid(),
            cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES", ""))
        result = await self.post_process(req, raw, usage)
        # post_process runs the gates, which is work too; fold it in so `wall_s` covers the
        # whole call rather than everything but the last phase.
        usage.phases["post_process"] = round(time.monotonic() - mark, 6)
        usage.wall_s = round(time.monotonic() - t0, 6)
        result.cost_measured = usage.as_cost(self.spec.resources.gpus,
                                             self.spec.resources.cores)
        return result

    async def dry_run(self, req: TaskRequest) -> None:
        """Prove parameterization works WITHOUT executing (composition gate)."""
        req = await self.pre_process(req)
        self.parameterize(req)


class EchoTaskAgent(TaskAgent):
    """Fallback agent used when a spec declares no entry point."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        return {"result": f"{self.spec.id}", "outputs": {}, "metrics": {}}
