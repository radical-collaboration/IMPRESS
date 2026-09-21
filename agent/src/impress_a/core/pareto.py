"""Multi-objective ranking.

Constraints prune; directions rank. A candidate violating a hard constraint leaves the
live set regardless of how well it scores elsewhere - that is how Part A's QC thresholds
become policy rather than advice.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .tree import DesignNode


class Direction(str, Enum):
    MIN = "minimize"
    MAX = "maximize"


class Objective(BaseModel):
    name: str
    direction: Direction
    min: float | None = None
    max: float | None = None

    def satisfied_by(self, v: float | None) -> bool:
        if v is None:
            return False
        if self.min is not None and v < self.min:
            return False
        if self.max is not None and v > self.max:
            return False
        return True


def _dominates(a: DesignNode, b: DesignNode, objs: list[Objective]) -> bool:
    better_somewhere = False
    for o in objs:
        va, vb = a.metric(o.name), b.metric(o.name)
        if va is None or vb is None:
            return False
        if o.direction is Direction.MIN:
            if va > vb:
                return False
            if va < vb:
                better_somewhere = True
        else:
            if va < vb:
                return False
            if va > vb:
                better_somewhere = True
    return better_somewhere


def feasible(nodes: list[DesignNode], objs: list[Objective]) -> list[DesignNode]:
    """Hard-constraint filter. QC-failed nodes are already excluded upstream."""
    out = []
    for n in nodes:
        if not n.qc.eligible_for_front:
            continue
        if all(o.satisfied_by(n.metric(o.name)) for o in objs
               if o.min is not None or o.max is not None):
            out.append(n)
    return out


def pareto_front(nodes: list[DesignNode], objs: list[Objective]) -> list[DesignNode]:
    """Nondominated set over the feasible nodes.

    Not monotonic once measurements arrive (decision 0012): a node promoted on an
    optimistic prediction can be demoted by its own assay.
    """
    cand = feasible(nodes, objs)
    return [a for a in cand if not any(_dominates(b, a, objs) for b in cand if b is not a)]
