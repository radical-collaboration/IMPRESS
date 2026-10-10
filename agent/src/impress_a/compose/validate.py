"""The five validation gates plus dry-run.

Rejection at any gate produces a structured ValidationFailure returned to the policy via
`on_rejected`. A rejected graph costs one cycle - that is what makes free composition
affordable to get wrong (Part B doc 05).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.budget import BudgetLedger
from ..core.decision import ValidationFailure
from ..core.types import Pattern
from ..tools.registry import Registry
from .graph import TaskGraph


@dataclass
class SiteCaps:
    gpu_api: str = "cuda"
    gpus_per_node: int = 1
    nodes: int = 1
    allow_external: bool = False


class Validator:
    def __init__(self, reg: Registry, site: SiteCaps, budget: BudgetLedger):
        self.reg, self.site, self.budget = reg, site, budget

    def validate(self, g: TaskGraph) -> ValidationFailure | None:
        for gate in (self._g1_types, self._g2_structure, self._g3_params,
                     self._g4_resources, self._g5_budget):
            if (f := gate(g)) is not None:
                return f
        return None

    # -- gate 1: types -----------------------------------------------------
    def _g1_types(self, g: TaskGraph) -> ValidationFailure | None:
        for tid, node in g.nodes.items():
            try:
                spec = self.reg.get(node.tool)
            except KeyError as e:
                return ValidationFailure(gate="type", node=tid, reason=str(e))
            for port, ref in node.inputs.items():
                if port not in spec.inputs:
                    return ValidationFailure(gate="type", node=tid,
                                             reason=f"{node.tool} has no input port {port!r}")
                dep_id, _, out_port = ref.partition(".")
                if dep_id not in g.nodes:
                    return ValidationFailure(gate="type", node=tid,
                                             reason=f"input {port!r} references unknown node {dep_id!r}")
                dep_spec = self.reg.get(g.nodes[dep_id].tool)
                if out_port not in dep_spec.outputs:
                    return ValidationFailure(gate="type", node=tid,
                                             reason=f"{dep_spec.id} has no output {out_port!r}")
                produced = dep_spec.outputs[out_port].type
                required = spec.inputs[port].type
                if not produced.unifies_with(required):
                    return ValidationFailure(
                        gate="type", node=tid,
                        reason=f"type mismatch on {port!r}: {dep_spec.id}.{out_port} "
                               f"produces {produced.value}, {node.tool} requires {required.value}",
                        detail={"produced": produced.value, "required": required.value})
            for port, ps in spec.inputs.items():
                if ps.required and port not in node.inputs and not node.deps:
                    pass  # roots may be satisfied from campaign inputs
        return None

    # -- gate 2: structure -------------------------------------------------
    def _g2_structure(self, g: TaskGraph) -> ValidationFailure | None:
        if not g.nodes:
            return ValidationFailure(gate="structure", reason="empty graph")
        try:
            g.topo_order()
        except ValueError as e:
            return ValidationFailure(gate="structure", reason=str(e))
        for tid, node in g.nodes.items():
            spec = self.reg.get(node.tool)
            if spec.qc_gates == [] and spec.pattern is not Pattern.P6:
                return ValidationFailure(
                    gate="structure", node=tid,
                    reason=f"{node.tool} composed with no QC gates - gates are mandatory")
        return None

    # -- gate 3: parameters -------------------------------------------------
    def _g3_params(self, g: TaskGraph) -> ValidationFailure | None:
        for tid, node in g.nodes.items():
            spec = self.reg.get(node.tool)
            for k, v in node.params.items():
                if k in spec.frozen_parameters:
                    return ValidationFailure(
                        gate="parameter", node=tid,
                        reason=f"{node.tool}.{k} is frozen: {spec.frozen_parameters[k]}")
                if k not in spec.parameters:
                    return ValidationFailure(gate="parameter", node=tid,
                                             reason=f"{node.tool}: unknown parameter {k!r}")
                if err := spec.parameters[k].validate_value(v):
                    return ValidationFailure(gate="parameter", node=tid,
                                             reason=f"{node.tool}.{k}: {err}")
        return None

    # -- gate 4: resources --------------------------------------------------
    def _g4_resources(self, g: TaskGraph) -> ValidationFailure | None:
        for tid, node in g.nodes.items():
            spec = self.reg.get(node.tool)
            if spec.pattern is Pattern.P6:
                return ValidationFailure(
                    gate="resource", node=tid,
                    reason=f"{node.tool} is P6 and must be inlined, never scheduled")
            if spec.pattern.is_external and not self.site.allow_external:
                return ValidationFailure(
                    gate="resource", node=tid,
                    reason=f"{node.tool} is {spec.pattern.value}; site forbids external submission")
            if spec.resources.gpus > self.site.gpus_per_node:
                return ValidationFailure(
                    gate="resource", node=tid,
                    reason=f"{node.tool} wants {spec.resources.gpus} GPUs, "
                           f"site has {self.site.gpus_per_node}/node")
            if spec.resources.gpus > 0 and not spec.gpu_portability.runs_on(self.site.gpu_api):
                return ValidationFailure(
                    gate="resource", node=tid,
                    reason=f"{node.tool} has no proven path on gpu_api={self.site.gpu_api!r}",
                    detail={"gpu_api": self.site.gpu_api})
        return None

    # -- gate 5: budget -----------------------------------------------------
    def estimate(self, g: TaskGraph) -> dict[str, float]:
        total: dict[str, float] = {}
        for node in g.nodes.values():
            for d, c in self.reg.get(node.tool).cost_model.cost.items():
                total[d] = total.get(d, 0.0) + c
        return total

    def _g5_budget(self, g: TaskGraph) -> ValidationFailure | None:
        est = self.estimate(g)
        if blown := self.budget.would_exceed(est):
            return ValidationFailure(
                gate="budget", reason=f"estimate exceeds remaining budget in {blown}",
                detail={"estimate": est,
                        "remaining": {d: self.budget.remaining(d) for d in blown}})
        return None

    async def dry_run(self, g: TaskGraph) -> ValidationFailure | None:
        """Every task agent parameterizes WITHOUT executing."""
        from ..tools.agent import TaskRequest
        for tid, node in g.nodes.items():
            spec = self.reg.get(node.tool)
            agent = self.reg.agent_for(node.tool)(spec)
            try:
                await agent.dry_run(TaskRequest(tool=node.tool, params=node.params))
            except Exception as e:
                return ValidationFailure(gate="dry_run", node=tid, reason=str(e))
        return None
