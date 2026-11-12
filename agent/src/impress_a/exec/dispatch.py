"""The node factory and result assembly every Stage shares.

`node_task` turns one graph node into engine work; `results_from` turns a Stage's payloads back
into typed `ExecutionResults`. The Stage itself - one asyncflow block per graph - is
`exec/stage.py`. This module used to hold the `Dispatcher` too, which registered a graph's tasks
on the engine directly; Stages as blocks replaced both it and the IMPRESS-pipeline Runner.

Two asyncflow idioms, both needed and not interchangeable:
  * dependency-as-argument -> expresses EDGES
  * asyncio.gather         -> awaits INDEPENDENT work (P2 replica fan-out)

GOTCHA: asyncflow takes the task name from `fn.__name__`; the decorator accepts no
`name=` kwarg. Set `__name__` before decorating.
"""
from __future__ import annotations

import asyncio
import contextvars
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.qc import QCReport, QCVerdict
from ..core.results import RunOutcome, RunState, TaskOutcome
from ..tools._subprocess import LAUNCHER
from ..tools.agent import TaskRequest, TaskResult, TaskUsage
from ..tools.registry import Registry
from .backend import LOCAL
from .launch import Launcher
from .resources import Placement, placement_for


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


def node_task(flow: Any, reg: Registry, node_id: str, tool_id: str,
              params: dict[str, Any], *, invocation: str = "",
              seed: int | None = None, dep_order: tuple[str, ...] = (),
              wiring: tuple[tuple[str, str, str], ...] = (),
              workdir: str | None = None, placement: Placement | None = None,
              workflow_id: str | None = None,
              seed_inputs: dict[str, Any] | None = None,
              launchers: list[Launcher] | None = None,
              slots: asyncio.Semaphore | None = None):
    """ONE generic factory for every node in every graph.

    **A node is two kinds of engine work.** The adapter - pre-process, parameterize, run,
    post-process and the QC gates - is a function task on the `local` route: a thread in this
    process, so it can be handed the campaign's own objects and nothing about it is pickled.
    Every command the adapter starts through `run_cmd` is a separate executable task on the
    `compute` route, placed by `placement` (`exec/launch.py`). So the backend schedules the
    binaries, with their GPU and thread share, rather than a Python callable that hides them.

    `wiring` is the node's typed `inputs` map, flattened to `(port, dep_id, out_port)`
    triples - the composer computed it and the validator type-checked it. A node with two
    typed inputs gets the right artifact on each; keying them positionally used to mis-wire
    exactly that case, silently.
    """
    spec = reg.get(tool_id)
    agent_cls = reg.agent_for(tool_id)
    placement = placement or placement_for(spec.resources, "concurrent", threads=1)
    # Built here, on the engine loop, rather than inside `_run`: `_run` executes on a `local`
    # thread under its own `asyncio.run`, and commands must be submitted on the loop the engine
    # was built on - in THIS context, which inside a Stage block is the block's, so its
    # commands become block members (`exec/launch.py`). `launchers` is how the Stage reaches
    # them to cancel.
    launcher = Launcher(flow, flow.loop, invocation or node_id, placement,
                        workflow_id=workflow_id, context=contextvars.copy_context(),
                        slots=slots)
    if launchers is not None:
        launchers.append(launcher)

    async def _run(*deps: Any) -> dict[str, Any]:
        agent = agent_cls(spec)
        by_dep = dict(zip(dep_order, deps, strict=False))
        # Keyed by PORT where the composer named one, which is what `input_ref` resolves
        # against. The values are the dep payloads, unchanged.
        inputs: dict[str, Any] = {port: by_dep[dep_id]
                                  for port, dep_id, _ in wiring if dep_id in by_dep}
        wired = {dep_id for _, dep_id, _ in wiring}
        for i, (dep_id, payload) in enumerate(zip(dep_order, deps, strict=False)):
            if dep_id not in wired:
                # An ordering-only dependency: a real edge with no typed port behind it.
                inputs[f"dep{i}"] = payload
        req = TaskRequest(tool=tool_id, params=params,
                          node_id=invocation, seed=seed, workdir=workdir,
                          inputs=inputs, gpu_index=placement.gpu_index,
                          seed_inputs=dict(seed_inputs or {}),
                          input_ports={port: out for port, _, out in wiring})
        token = LAUNCHER.set(launcher)
        launcher.entered()
        try:
            res = await agent(req)
        finally:
            LAUNCHER.reset(token)
            launcher.left()
        usage = res.usage
        if launcher.commands:
            # Time a command spent waiting for the backend is the backend's, not the tool's:
            # counting it would read a saturated pool as a slow tool, and `cost_measured`
            # exists to notice declared figures drifting below what tools really take.
            usage.phases["queued"] = round(launcher.queued_s, 6)
            usage.wall_s = round(max(0.0, usage.wall_s - launcher.queued_s), 6)
            res.cost_measured = usage.as_cost(spec.resources.gpus, spec.resources.cores)
        usage.commands = list(launcher.records)
        usage.cuda_visible_devices = ("" if placement.gpu_index is None
                                      else str(placement.gpu_index))
        return {"tool": res.tool, "outputs": res.outputs, "metrics": res.metrics,
                "qc": res.qc.model_dump(), "cost": res.cost,
                # Measured, beside declared.
                "usage": asdict(res.usage), "cost_measured": res.cost_measured}

    _run.__name__ = node_id   # asyncflow reads the name from __name__
    return flow.function_task(_run, backend=LOCAL)


def results_from(graph_id: str, payloads: dict[str, Any]) -> ExecutionResults:
    """Assemble typed results from `{node_id: payload-or-exception}`.

    One assembly implementation, so the declared/measured cost split has one place to live.
    The payloads must be keyed by the node that produced them - `exec/stage.py` builds them
    with a `strict=True` zip in topo order, which is where a misattribution would otherwise
    hide.
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


def host_for(lineage: int, gpus_per_node: int, hosts: tuple[str, ...]) -> str | None:
    """The node a lineage's GPU lives on, round-robin over (host, GPU) slots.

    `None` - let the backend choose - on a single host, which is every campaign run so far:
    naming the only host constrains nothing and costs a policy field.
    """
    if len(hosts) <= 1:
        return None
    slot = lineage % (len(hosts) * max(1, gpus_per_node))
    return hosts[slot // max(1, gpus_per_node)]


def gpu_for(lineage: int, gpus_per_node: int) -> int | None:
    """One lineage, one GPU - round-robin across the devices the site declares.

    Backlog A10 is the standing proof of what happens when nothing answers it: concurrent GPU
    tasks were not pinned at all, so several could land on one device while others sat idle -
    consistent with GPU-busy measuring at most 17% while three of four GPUs never held work.

    1 means "do not pin", which is also the honest answer for a laptop.
    """
    if gpus_per_node <= 1:
        return None
    return lineage % gpus_per_node
