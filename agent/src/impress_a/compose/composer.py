"""Turn an abstract ExperimentIntent into a concrete typed DAG.

The composer is the only component that knows how to wire tools together. Policies emit
intent; the composer emits graphs. That separation is what keeps policies swappable.
"""
from __future__ import annotations

from ..core.decision import ExperimentIntent
from ..core.types import Pattern
from ..tools.registry import Registry
from .graph import TaskGraph, TaskNode


class Composer:
    def __init__(self, reg: Registry):
        self.reg = reg

    def compose(self, intent: ExperimentIntent) -> TaskGraph:
        """Build `intent.replicas` INDEPENDENT chains through the declared stages.

        A replica is a whole lineage, not a fan-out at stage 0 that funnels back into a
        single downstream node - that would make N candidates collapse into one.

        P6 tools are INLINED, never added as scheduled nodes (Part B doc 05 gate 4).
        """
        g = TaskGraph(intent_goal=intent.goal)
        stages = [t for t in intent.stages
                  if self.reg.get(t).pattern is not Pattern.P6]
        for r in range(max(1, intent.replicas)):
            prev: str | None = None
            for i, tool_id in enumerate(stages):
                spec = self.reg.get(tool_id)
                tid = f"r{r}_s{i}_{tool_id}"
                inputs: dict[str, str] = {}
                deps: list[str] = []
                if prev is not None:
                    deps = [prev]
                    src_spec = self.reg.get(g.nodes[prev].tool)
                    for port, ps in spec.inputs.items():
                        match = next((op for op, os_ in src_spec.outputs.items()
                                      if os_.type.unifies_with(ps.type)), None)
                        if match:
                            inputs[port] = f"{prev}.{match}"
                g.add(TaskNode(id=tid, tool=tool_id,
                               params=dict(intent.params.get(tool_id, {})),
                               deps=deps, inputs=inputs,
                               node_id=intent.parent_node, lineage=r))
                prev = tid
        return g
