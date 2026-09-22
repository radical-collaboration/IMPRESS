"""The append-only design tree.

Nodes are never mutated or deleted; status changes and superseding measurements are new
records. That is what makes backtracking non-destructive (Part B doc 03) and what lets a
terminated campaign keep receiving assay results (doc 09).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Iterator

from pydantic import BaseModel, Field

from .artifacts import ArtifactRef, Property
from .ids import counter
from .qc import QCReport


class NodeStatus(str, Enum):
    LIVE = "live"
    PRUNED = "pruned"
    FAILED = "failed"
    PROMOTED = "promoted"


new_node_id = counter("n")


class DesignNode(BaseModel):
    id: str = Field(default_factory=new_node_id)
    parent: str | None = None
    cycle: int = 0
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)
    properties: dict[str, Property] = Field(default_factory=dict)
    qc: QCReport = Field(default_factory=QCReport)
    produced_by: str | None = None      # GraphId
    decision: str | None = None          # DecisionId
    status: NodeStatus = NodeStatus.LIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def metric(self, name: str) -> float | None:
        p = self.properties.get(name)
        return p.value if p and isinstance(p.value, (int, float)) else None


class CampaignTree(BaseModel):
    """Append-only. `nodes` is insertion-ordered; status changes append new records."""

    nodes: dict[str, DesignNode] = Field(default_factory=dict)
    _order: list[str] = []

    def add(self, node: DesignNode) -> str:
        self.nodes[node.id] = node
        return node.id

    def get(self, nid: str) -> DesignNode:
        return self.nodes[nid]

    def children(self, nid: str) -> list[DesignNode]:
        return [n for n in self.nodes.values() if n.parent == nid]

    def lineage(self, nid: str) -> list[DesignNode]:
        out: list[DesignNode] = []
        cur: str | None = nid
        while cur is not None:
            n = self.nodes[cur]
            out.append(n)
            cur = n.parent
        return list(reversed(out))

    def live(self) -> list[DesignNode]:
        return [n for n in self.nodes.values()
                if n.status is NodeStatus.LIVE and n.qc.eligible_for_front]

    def set_status(self, nid: str, status: NodeStatus) -> None:
        self.nodes[nid].status = status

    def branch_from(self, nid: str) -> DesignNode:
        """Non-destructive backtrack: a NEW node parented on an earlier one.

        The abandoned branch is untouched - the policy may be wrong, and a later cycle
        may want to return to it.
        """
        src = self.nodes[nid]
        return DesignNode(parent=nid, cycle=src.cycle, artifacts=dict(src.artifacts))

    def ingest_measurement(self, nid: str, prop: Property) -> bool:
        """Out-of-band measurement arrival (P8). Supersedes, never deletes."""
        node = self.nodes[nid]
        existing = node.properties.get(prop.name)
        if existing is not None and not prop.outranks(existing):
            return False
        if existing is not None:
            existing.superseded_by = f"{prop.source.name}@{prop.observed_at.isoformat()}"
            node.properties[f"{prop.name}__superseded"] = existing
        node.properties[prop.name] = prop
        return True

    def __iter__(self) -> Iterator[DesignNode]:  # type: ignore[override]
        return iter(self.nodes.values())

    def __len__(self) -> int:
        return len(self.nodes)
