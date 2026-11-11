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
from dataclasses import asdict, dataclass, field
from typing import Any

from ..compose.graph import TaskGraph
from ..core.qc import QCReport, QCVerdict
from ..core.results import RunOutcome, RunState, TaskOutcome
from ..tools.agent import TaskRequest, TaskResult, TaskUsage
from ..tools.registry import Registry


@dataclass
class ExecutionResults:
    graph_id: str
    per_task: dict[str, TaskResult] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    #: DECLARED, summed. What the budget settles on - unchanged on purpose.
    cost: dict[str, float] = field(default_factory=dict)
    #: MEASURED, summed. For analysis, and for noticing a declared figure drifting below
    #: measurement - at which point gate 5 starts refusing work that would in fact fit.
    cost_measured: dict[str, float] = field(default_factory=dict)

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
            q.gates.extend(r.qc.gates)
            q.notes.extend(r.qc.notes)
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
                               cost=r.cost, cost_measured=r.cost_measured,
                               usage=asdict(r.usage), outputs=dict(r.outputs))
                   for tid, r in self.per_task.items()])

    def reporters_for(self, task_ids: list[str]) -> dict[str, str]:
        """metric name -> the tool that reported it.

        Later tasks win, which matches `metrics_for`: a chain's last word on a metric is the
        one the node carries, so the attribution has to agree with the value.
        """
        out: dict[str, str] = {}
        for tid in task_ids:
            if (r := self.per_task.get(tid)) is not None:
                for metric in r.metrics:
                    out[metric] = r.tool
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


def node_task(flow: Any, reg: Registry, node_id: str, tool_id: str,
              params: dict[str, Any], *, invocation: str = "",
              seed: int | None = None, dep_order: tuple[str, ...] = (),
              wiring: tuple[tuple[str, str, str], ...] = (),
              workdir: str | None = None, gpu_index: int | None = None):
    """ONE generic factory for every node in every graph.

    `wiring` is the node's typed `inputs` map, flattened to
    `(port, dep_id, out_port)` triples - the composer computed it and the validator
    type-checked it, and until now the dispatcher threw it away: inputs were keyed
    `dep0..depN` positionally, and every real adapter recovered its artifact by SCANNING
    the payloads for one whose `outputs` happened to contain the port it wanted.

    That works only while every node has exactly one upstream dependency. A node with two
    typed inputs type-checks at composition and mis-wires at runtime, silently, because
    the scan returns whichever dep is first. An Aim hierarchy with real dependencies hits
    that on its first branch - which is why this is fixed before the Runner, and before
    anything composes a branching Stage.
    """
    spec = reg.get(tool_id)
    agent_cls = reg.agent_for(tool_id)

    async def _run(*deps: Any) -> dict[str, Any]:
        agent = agent_cls(spec)
        by_dep = dict(zip(dep_order, deps, strict=False))
        # Keyed by PORT where the composer named one. The values are still the dep
        # payloads, so `_subprocess.first_dep_output` keeps working for adapters that
        # have not migrated - the keys changed, not the shape.
        inputs: dict[str, Any] = {port: by_dep[dep_id]
                                  for port, dep_id, _ in wiring if dep_id in by_dep}
        wired = {dep_id for _, dep_id, _ in wiring}
        for i, (dep_id, payload) in enumerate(zip(dep_order, deps, strict=False)):
            if dep_id not in wired:
                # An ordering-only dependency: a real edge with no typed port behind it.
                inputs[f"dep{i}"] = payload
        req = TaskRequest(tool=tool_id, params=params,
                          node_id=invocation, seed=seed, workdir=workdir,
                          inputs=inputs, gpu_index=gpu_index,
                          input_ports={port: out for port, _, out in wiring})
        res = await agent(req)
        return {"tool": res.tool, "outputs": res.outputs, "metrics": res.metrics,
                "qc": res.qc.model_dump(), "cost": res.cost,
                # Measured, beside declared. The closure crosses a process boundary, so
                # both travel as plain data.
                "usage": asdict(res.usage), "cost_measured": res.cost_measured}

    _run.__name__ = node_id   # asyncflow reads the name from __name__
    return flow.function_task(_run)


def results_from(graph_id: str, payloads: dict[str, Any]) -> ExecutionResults:
    """Assemble typed results from `{node_id: payload-or-exception}`.

    One assembly implementation, shared by the Dispatcher and the Runner. Two would be two
    places for the declared/measured cost split to drift, and the `strict=True` zip that feeds
    this is where a misattribution would otherwise hide.
    """
    out = ExecutionResults(graph_id=graph_id)
    for tid, r in payloads.items():
        if isinstance(r, BaseException):
            out.failures[tid] = f"{type(r).__name__}: {r}"
            continue
        out.per_task[tid] = TaskResult(
            tool=r["tool"], outputs=r["outputs"], metrics=r["metrics"],
            qc=QCReport(**r["qc"]), cost=r["cost"],
            usage=TaskUsage(**r.get("usage", {})),
            cost_measured=r.get("cost_measured", {}))
        # `out.cost` aggregates the DECLARED figure, deliberately unchanged: it is what the
        # budget settles on, and redefining it here would change what admission refuses for
        # every campaign at once (backlog A11).
        for d, c in r["cost"].items():
            out.cost[d] = out.cost.get(d, 0.0) + c
        for d, c in (r.get("cost_measured") or {}).items():
            out.cost_measured[d] = out.cost_measured.get(d, 0.0) + c
    return out


class Dispatcher:
    def __init__(self, flow, reg: Registry, backend_kind: str = "concurrent",
                 workdir: str | None = None, gpus_per_node: int = 1):
        self.flow, self.reg, self.backend_kind = flow, reg, backend_kind
        #: Devices available per node, from the campaign's `SiteCaps`. 1 means "do not pin",
        #: which is also the honest answer for a laptop.
        self.gpus_per_node = gpus_per_node
        # None means "whatever the process CWD is", which is what the launcher sets.
        self.workdir = workdir

    def _gpu_for(self, lineage: int) -> int | None:
        """One lineage, one GPU - round-robin across the devices the site declares.

        The reference pipeline assigns a device per pipeline the same way, and backlog A10
        recorded that IMPRESS-A did not assign one at all: several concurrent GPU tasks could
        land on the same device while others sat idle, which is consistent with GPU-busy
        measuring at most 17% while three of four GPUs never held work.
        """
        if self.gpus_per_node <= 1:
            return None
        return lineage % self.gpus_per_node

    def _make_task(self, node_id: str, tool_id: str, params: dict[str, Any],
                   invocation: str = "", seed: int | None = None,
                   dep_order: tuple[str, ...] = (),
                   wiring: tuple[tuple[str, str, str], ...] = (),
                   gpu_index: int | None = None):
        return node_task(self.flow, self.reg, node_id, tool_id, params,
                         invocation=invocation, seed=seed, dep_order=dep_order,
                         wiring=wiring, workdir=self.workdir, gpu_index=gpu_index)


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
        tasks = {tid: self._make_task(
                     tid, n.tool, n.params, f"{invocation}:{tid}", n.seed,
                     dep_order=tuple(n.deps),
                     wiring=tuple((port, *ref.split(".", 1)) if "." in ref
                                  else (port, ref, "")
                                  for port, ref in n.inputs.items()),
                     gpu_index=self._gpu_for(n.lineage))
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
        # Zip against `futures`, which is built in topo order - the same order `gather` was
        # given. Zipping against `graph.nodes` (insertion order) misattributes every payload
        # for anything wider than one lineage, because Kahn's algorithm emits roots first.
        return results_from(h.graph_id, dict(zip(h.futures.keys(), raw, strict=True)))

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
