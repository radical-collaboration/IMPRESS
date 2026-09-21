"""The composed DAG - pure data. Validated as data, dispatched generically."""
from __future__ import annotations

import hashlib
import itertools
from typing import Any

from pydantic import BaseModel, Field

_gids = itertools.count(1)


def new_graph_id() -> str:
    return f"g{next(_gids):06d}"


class TaskNode(BaseModel):
    id: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    deps: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)  # port -> "dep_id.out_port"
    node_id: str | None = None  # design-tree parent this task belongs to
    lineage: int = 0            # replica index: one independent chain per lineage


class TaskGraph(BaseModel):
    id: str = Field(default_factory=new_graph_id)
    nodes: dict[str, TaskNode] = Field(default_factory=dict)
    intent_goal: str = ""

    def add(self, n: TaskNode) -> "TaskGraph":
        self.nodes[n.id] = n
        return self

    def topo_order(self) -> list[str]:
        """Kahn. Raises on a cycle - gate 2 relies on this."""
        indeg = {k: len(v.deps) for k, v in self.nodes.items()}
        ready = [k for k, d in indeg.items() if d == 0]
        out: list[str] = []
        while ready:
            n = ready.pop(0)
            out.append(n)
            for m, node in self.nodes.items():
                if n in node.deps:
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        ready.append(m)
        if len(out) != len(self.nodes):
            raise ValueError(f"cycle in graph {self.id}")
        return out

    def pattern_signature(self) -> str:
        """Identity for the interlock: SHAPE ONLY - tool ids plus typed edges.

        Parameter values are excluded deliberately, otherwise every parameter change
        would reset a pattern's accumulated trust.
        """
        parts = sorted(
            f"{n.tool}<-{','.join(sorted(self.nodes[d].tool for d in n.deps))}"
            for n in self.nodes.values()
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
