"""The composed DAG - pure data. Validated as data, dispatched generically."""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from ..core.ids import counter

new_graph_id = counter("g")


class TaskNode(BaseModel):
    id: str
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    deps: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)  # port -> "dep_id.out_port"
    #: port -> an artifact from OUTSIDE this graph: a parent design being refined, or a file
    #: the Goal supplied. Without this `parent_node` only labelled lineage - "exploit a node"
    #: re-ran its recipe rather than refining its structure, which is why no campaign could
    #: reproduce the reference pipeline's partial-diffusion loop.
    seed_inputs: dict[str, Any] = Field(default_factory=dict)
    node_id: str | None = None  # design-tree parent this task belongs to
    lineage: int = 0            # replica index: one independent chain per lineage
    seed: int | None = None     # per-lineage draw; see composer._replica_seed


class TaskGraph(BaseModel):
    id: str = Field(default_factory=new_graph_id)
    nodes: dict[str, TaskNode] = Field(default_factory=dict)
    intent_goal: str = ""

    def add(self, n: TaskNode) -> TaskGraph:
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
