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
from ..core.results import RunOutcome, RunState, TaskOutcome
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

    def merged_artifacts(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for r in self.per_task.values():
            out.update(r.outputs)
        return out

    def artifacts_for(self, task_ids: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for tid in task_ids:
            if (r := self.per_task.get(tid)) is not None:
                out.update(r.outputs)
        return out

    def merged_metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.per_task.values():
            out.update(r.metrics)
        return out

    def to_outcome(self, run_id: str, graph, state: RunState = RunState.DONE,
                   nodes: list[str] | None = None, signature: str = "") -> RunOutcome:
        """Project into the core-typed, serializable form a reasoner may hold.

        The projection runs here rather than in `core` because only the execution layer
        knows what an `ExecutionResults` contains - and `core` importing `exec` is the
        one direction the import contract forbids outright.
        """
        return RunOutcome(
            run_id=run_id, graph_id=self.graph_id, state=state, signature=signature,
            nodes=list(nodes or []),
            metrics=self.merged_metrics(), qc=self.merged_qc(),
            cost=dict(self.cost), failures=dict(self.failures),
            artifacts=self.merged_artifacts(),
            tasks=[TaskOutcome(task_id=tid, tool=r.tool, metrics=r.metrics, qc=r.qc,
                               cost=r.cost, outputs=dict(r.outputs))
                   for tid, r in self.per_task.items()])

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


@dataclass
class DispatchHandle:
    """Retained submission state for one in-flight graph.

    The execution-layer seam always called for these ("cancellation is why submission
    handles are retained per graph"); nothing kept one, because nothing needed one while
    every graph was awaited where it was submitted.
    """

    run_id: str
    graph_id: str
    futures: dict[str, Any] = field(default_factory=dict)
    gather: Any = None
    cancelled: bool = False


class Dispatcher:
    def __init__(self, flow, reg: Registry, backend_kind: str = "concurrent",
                 workdir: str | None = None):
        self.flow, self.reg, self.backend_kind = flow, reg, backend_kind
        # None means "whatever the process CWD is", which is what the launcher sets.
        self.workdir = workdir

    def _make_task(self, node_id: str, tool_id: str, params: dict[str, Any],
                   invocation: str = "", seed: int | None = None):
        """ONE generic factory for every node in every graph."""
        reg, spec = self.reg, self.reg.get(tool_id)
        agent_cls = reg.agent_for(tool_id)
        # Bind to a local: the closure is pickled to the process pool, and reaching
        # `self` would drag the Dispatcher - and the engine's asyncio futures - with it.
        workdir = self.workdir

        async def _run(*deps: Any) -> dict[str, Any]:
            agent = agent_cls(spec)
            req = TaskRequest(tool=tool_id, params=params,
                              node_id=invocation, seed=seed, workdir=workdir,
                              inputs={f"dep{i}": d for i, d in enumerate(deps)})
            res = await agent(req)
            return {"tool": res.tool, "outputs": res.outputs, "metrics": res.metrics,
                    "qc": res.qc.model_dump(), "cost": res.cost}

        _run.__name__ = node_id   # asyncflow reads the name from __name__
        return self.flow.function_task(_run)

    def submit(self, g: TaskGraph, run_id: str = "") -> DispatchHandle:
        """Register the whole graph and return WITHOUT awaiting it.

        Submission is where the outer loop used to lose control: it awaited the entire
        graph, so the reasoner could not be consulted again until the slowest lineage
        finished. Registration is synchronous, so by the time this returns every task is
        known to the scheduler and the caller holds a handle to the work.

        The handle is also the run's index. asyncflow tags tasks with `workflow_id` but
        exposes no way to look tasks up by it, so the caller's own table remains the only
        way to answer "what belongs to run R" - which cancellation and draining need.
        """
        invocation = run_id or g.id
        tasks = {tid: self._make_task(tid, n.tool, n.params,
                                      f"{invocation}:{tid}", n.seed)
                 for tid, n in g.nodes.items()}
        futures: dict[str, Any] = {}
        for tid in g.topo_order():                       # edges via unawaited futures
            deps = [futures[d] for d in g.nodes[tid].deps]
            futures[tid] = (tasks[tid](*deps, workflow_id=run_id) if run_id
                            else tasks[tid](*deps))
        # return_exceptions=True: one bad task must not cancel its siblings, and the
        # gather is not awaited yet, so a raising task would otherwise go unretrieved.
        gather = asyncio.gather(*futures.values(), return_exceptions=True)
        return DispatchHandle(run_id=run_id, graph_id=g.id, futures=futures,
                              gather=gather)

    async def collect(self, h: DispatchHandle) -> ExecutionResults:
        """Await a submitted graph and assemble its typed results."""
        raw = await h.gather
        out = ExecutionResults(graph_id=h.graph_id)
        for tid, r in zip(h.futures.keys(), raw):
            if isinstance(r, BaseException):
                out.failures[tid] = f"{type(r).__name__}: {r}"
                continue
            out.per_task[tid] = TaskResult(
                tool=r["tool"], outputs=r["outputs"], metrics=r["metrics"],
                qc=QCReport(**r["qc"]), cost=r["cost"])
            for d, c in r["cost"].items():
                out.cost[d] = out.cost.get(d, 0.0) + c
        return out

    def cancel(self, h: DispatchHandle) -> None:
        """Ask for a run to stop. ADVISORY - see `DispatchHandle.cancelled`.

        A task that has already started cannot be recalled: the concurrent backend calls
        `Future.cancel()`, which returns False once the callable is running, and
        asyncflow discards that answer anyway. So this reclaims queued work only, and the
        run's real outcome still has to come from `collect`.
        """
        h.cancelled = True
        for f in h.futures.values():
            f.cancel()

    async def run(self, g: TaskGraph, invocation: str = "") -> ExecutionResults:
        """Submit and await in one step - the serial path."""
        return await self.collect(self.submit(g, run_id=invocation))
