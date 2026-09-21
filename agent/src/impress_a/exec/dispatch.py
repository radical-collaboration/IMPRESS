"""Generic DAG dispatch to asyncflow.

VALIDATED BY SPIKE (asyncflow 0.5.1, rhapsody 0.5.0): a DAG described as *data* is
dispatched with ONE generic factory - no code generation, no AST work. Dependencies are
expressed by passing UNAWAITED futures as call arguments; asyncflow's scheduler resolves
order from its own dependency-count structure.

Two asyncflow idioms, both needed and not interchangeable:
  * dependency-as-argument -> expresses EDGES
  * asyncio.gather         -> awaits INDEPENDENT work (P2 replica fan-out)

GOTCHA: asyncflow takes the task name from `fn.__name__`; the decorator accepts no
`name=` kwarg. Set `__name__` before decorating.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..compose.graph import TaskGraph
from ..core.qc import QCReport, QCVerdict
from ..tools.agent import TaskRequest, TaskResult
from ..tools.registry import Registry


@dataclass
class ExecutionResults:
    graph_id: str
    per_task: dict[str, TaskResult] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    cost: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def all_gates_passed(self) -> bool:
        return self.ok and all(r.qc.verdict is QCVerdict.PASS for r in self.per_task.values())

    def lineages(self, g) -> dict[int, list[str]]:
        """Task ids grouped by replica lineage - one design candidate per lineage."""
        out: dict[int, list[str]] = {}
        for tid, node in g.nodes.items():
            out.setdefault(node.lineage, []).append(tid)
        return out

    def metrics_for(self, task_ids: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for tid in task_ids:
            if (r := self.per_task.get(tid)) is not None:
                out.update(r.metrics)
        return out

    def qc_for(self, task_ids: list[str]) -> QCReport:
        q = QCReport()
        for tid in task_ids:
            r = self.per_task.get(tid)
            if r is None:
                q.verdict = QCVerdict.FAIL
                q.notes.append(f"{tid}: no result")
                continue
            q.gates.extend(r.qc.gates); q.notes.extend(r.qc.notes)
            if r.qc.verdict is QCVerdict.FAIL:
                q.verdict = QCVerdict.FAIL
            elif r.qc.verdict is QCVerdict.SUSPECT and q.verdict is not QCVerdict.FAIL:
                q.verdict = QCVerdict.SUSPECT
        return q

    def merged_metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.per_task.values():
            out.update(r.metrics)
        return out

    def merged_qc(self) -> QCReport:
        q = QCReport()
        for r in self.per_task.values():
            q.gates.extend(r.qc.gates)
            q.notes.extend(r.qc.notes)
            if r.qc.verdict is QCVerdict.FAIL:
                q.verdict = QCVerdict.FAIL
            elif r.qc.verdict is QCVerdict.SUSPECT and q.verdict is not QCVerdict.FAIL:
                q.verdict = QCVerdict.SUSPECT
        return q


class Dispatcher:
    def __init__(self, flow, reg: Registry, backend_kind: str = "concurrent"):
        self.flow, self.reg, self.backend_kind = flow, reg, backend_kind

    def _make_task(self, node_id: str, tool_id: str, params: dict[str, Any],
                   invocation: str = ""):
        """ONE generic factory for every node in every graph."""
        reg, spec = self.reg, self.reg.get(tool_id)
        agent_cls = reg.agent_for(tool_id)

        async def _run(*deps: Any) -> dict[str, Any]:
            agent = agent_cls(spec)
            req = TaskRequest(tool=tool_id, params=params,
                              node_id=invocation,
                              inputs={f"dep{i}": d for i, d in enumerate(deps)})
            res = await agent(req)
            return {"tool": res.tool, "outputs": res.outputs, "metrics": res.metrics,
                    "qc": res.qc.model_dump(), "cost": res.cost}

        _run.__name__ = node_id   # asyncflow reads the name from __name__
        return self.flow.function_task(_run)

    async def run(self, g: TaskGraph, invocation: str = "") -> ExecutionResults:
        tasks = {tid: self._make_task(tid, n.tool, n.params,
                                      f"{invocation}:{tid}")
                 for tid, n in g.nodes.items()}
        futures: dict[str, Any] = {}
        for tid in g.topo_order():                       # edges via unawaited futures
            futures[tid] = tasks[tid](*[futures[d] for d in g.nodes[tid].deps])

        out = ExecutionResults(graph_id=g.id)
        raw = await asyncio.gather(*futures.values(), return_exceptions=True)
        for tid, r in zip(futures.keys(), raw):
            if isinstance(r, BaseException):
                out.failures[tid] = f"{type(r).__name__}: {r}"
                continue
            out.per_task[tid] = TaskResult(
                tool=r["tool"], outputs=r["outputs"], metrics=r["metrics"],
                qc=QCReport(**r["qc"]), cost=r["cost"])
            for d, c in r["cost"].items():
                out.cost[d] = out.cost.get(d, 0.0) + c
        return out
