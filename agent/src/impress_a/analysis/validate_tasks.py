"""Per-Task validation on real hardware. The gate the trust assertion rests on.

`impress-a trust --assert` grants a pattern trust without the three clean runs the interlock
would otherwise require, on the grounds that the Tasks are proven in
`examples/small_molecule_binding`. That argument is only honest if the Tasks are proven **on
this hardware, in this venv, through these adapters** - otherwise it asserts trust in code
nobody has run. This is what re-proves them, and it is deliberately the only check shaped like
all four defects that reached real hardware:

Four defects reached real hardware, and each was invisible to a dry run. This is what each
one needed, which is why the checks are what they are:

* the `*.cif.gz` glob selected a diffusion **trajectory** - same extension, and `denoised`
  sorts first - so a dry run saw a type-correct graph. Needs: the declared output port, on
  disk, with a size.
* LigandMPNN died in `run.py`'s module-level imports, first on a missing `ml_collections` and
  then on `np.int`. A dry run saw a tool that exists. Needs: a tool that **ran**.
* `import pyrosetta` took **471 s** off HDD-backed Lustre against a 300 s budget, so packmin
  could not finish starting. A dry run saw nothing. Needs: the `[phase]` breakdown, so import
  time is separable from work.
* the `cost_model` figures were 6-69x over measurement, so gate 5 truncated a chain. A dry run
  saw an affordable estimate. Needs: measured against declared, per dimension.

**"Checked against the binary" is not "executed."** That is the pattern this project keeps
paying for, and the reason this runs the chain rather than inspecting it.

Integrity rows fail the run; acceptance rows are reported and do not, because a weak design is
not a broken Task (decision 0013). A tool from the `mock` toolkit fails whatever it produces -
per Task, where gate 6 checks per campaign.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..compose.composer import Composer
from ..core.decision import ExperimentIntent
from ..core.qc import GateOutcome
from ..exec.backend import make_engine_bounded
from ..exec.dispatch import Dispatcher
from ..exec.resources import thread_share
from ..tools.registry import Registry

log = logging.getLogger(__name__)

#: An output file smaller than this is treated as empty. Not zero: a tool that writes a header
#: and dies leaves a few bytes, and the `*.cif.gz` trajectory bug is the reminder that a file's
#: existence says nothing about whether it is the right file. 512 bytes is below any real
#: structure and above any plausible stub.
MIN_OUTPUT_BYTES = 512


@dataclass
class Row:
    """One check on one Task."""

    check: str
    ok: bool
    role: str = "integrity"        # integrity | acceptance
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return not self.ok and self.role == "integrity"


@dataclass
class TaskReport:
    tool: str
    task_id: str
    rows: list[Row] = field(default_factory=list)
    wall_s: float = 0.0
    phases: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    cost_ratio: dict[str, float] = field(default_factory=dict)

    def add(self, check: str, ok: bool, detail: str = "",
            role: str = "integrity") -> None:
        self.rows.append(Row(check=check, ok=ok, role=role, detail=detail))

    @property
    def ok(self) -> bool:
        """Integrity only. An acceptance failure is a weak design, not a broken Task."""
        return not any(r.blocking for r in self.rows)


@dataclass
class Report:
    campaign_id: str
    tasks: list[TaskReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.tasks) and all(t.ok for t in self.tasks)

    def table(self) -> str:
        """One line per Task, then one line per failing row. Printed by the CLI."""
        width = max([len(t.tool) for t in self.tasks] + [4])
        out = [f"{'tool'.ljust(width)}  {'wall':>8}  {'rows':>7}  status"]
        for t in self.tasks:
            bad = [r for r in t.rows if not r.ok]
            passed = len(t.rows) - len(bad)
            out.append(f"{t.tool.ljust(width)}  {t.wall_s:8.1f}  "
                       f"{passed:3d}/{len(t.rows):<3d}  "
                       f"{'ok' if t.ok else 'FAIL'}")
            for r in bad:
                out.append(f"{'':{width}}    [{r.role[:4]}] {r.check}: {r.detail}")
        for err in self.errors:
            out.append(f"ERROR: {err}")
        return "\n".join(out)


async def validate_tasks(spec: Any, reg: Registry | None = None,
                         out_dir: Path | None = None) -> Report:
    """Execute each Task in the spec's chain once, in dependency order, and check it.

    One width-1 graph through the ordinary `Dispatcher` on the campaign's own backend, so each
    Task runs exactly as a campaign would run it - same composer, same wiring, same adapters,
    same resource translation. A bespoke harness here would validate the harness.
    """
    reg = reg or Registry().load()
    report = Report(campaign_id=spec.campaign_id)
    chain = list(spec.stages)
    if not chain:
        report.errors.append(
            "the campaign declares no `stages`, so there is no chain to validate")
        return report

    graph = Composer(reg, seed_salt=spec.seed_salt).compose(
        ExperimentIntent(goal=spec.goal, stages=chain, params=dict(spec.params),
                         replicas=1),
        run_label="validate")

    flow, _backend = await make_engine_bounded(
        spec.backend, spec.backend_config, spec.backend_startup_timeout_s,
        spec.backend_startup_heartbeat_s,
        work_dir=str(out_dir or Path(spec.root) / spec.campaign_id))
    try:
        # One chain, one lineage: the thread share is the whole cgroup halved, as for a
        # campaign of one pipeline.
        dispatcher = Dispatcher(flow, reg, spec.backend,
                                gpus_per_node=spec.site.gpus_per_node,
                                threads=thread_share(None, 1, 1))
        results = await dispatcher.collect(dispatcher.submit(graph, run_id="validate"))
    finally:
        await flow.shutdown()

    for tid in graph.topo_order():
        node = graph.nodes[tid]
        report.tasks.append(_check_task(reg, node, tid, results))

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "validate_tasks.json").write_text(
            json.dumps(asdict(report), indent=2, default=str) + "\n")
        (out_dir / "validate_tasks.txt").write_text(report.table() + "\n")
    return report


def _check_task(reg: Registry, node: Any, tid: str, results: Any) -> TaskReport:
    """Every row for one Task."""
    spec = reg.get(node.tool)
    r = TaskReport(tool=node.tool, task_id=tid)

    # 1. It ran at all. Everything below is meaningless otherwise, so nothing else is added.
    if tid in results.failures:
        r.add("ran", False, f"failed: {results.failures[tid]}")
        return r
    result = results.per_task.get(tid)
    if result is None:
        r.add("ran", False, "no result and no failure recorded - the task never reported")
        return r
    r.add("ran", True)

    # 2. Not a mock. Per Task, where gate 6 checks per campaign: a validation run that
    #    executed mocks would certify them as proven and the trust assertion would cite it.
    r.add("real_toolkit", spec.toolkit != "mock",
          f"toolkit is {spec.toolkit!r}; a mock tool completes with invented output")

    # 3. The phase breakdown. Without it a timeout names a budget, not a cause - which is
    #    exactly what a 471 s `import pyrosetta` against a 300 s budget looked like.
    usage = result.usage
    r.wall_s = float(getattr(usage, "wall_s", 0.0) or 0.0)
    r.phases = dict(getattr(usage, "phases", {}) or {})
    r.add("phases_recorded", bool(r.phases),
          "no per-phase timing, so import time cannot be separated from work")

    # 4. Declared output ports, on disk, with a size. The `*.cif.gz` trajectory bug is why
    #    a port's presence is not enough: same extension, wrong file, type-correct graph.
    for port, port_spec in spec.outputs.items():
        ref = result.outputs.get(port)
        if ref is None:
            r.add(f"output[{port}]", False, "declared output port not produced")
            continue
        if ref.type != port_spec.type:
            r.add(f"output[{port}]", False,
                  f"declared {port_spec.type.value}, produced {ref.type.value}")
            continue
        if ref.path is None:
            # An in-memory artifact (a MetricSet) has no file, and that is legitimate.
            r.add(f"output[{port}]", ref.value is not None,
                  "neither a path nor a value")
            continue
        path = Path(ref.path)
        if not path.is_file():
            r.add(f"output[{port}]", False, f"{path} does not exist")
            continue
        size = path.stat().st_size
        r.add(f"output[{port}]", size >= MIN_OUTPUT_BYTES,
              f"{path.name} is {size} bytes (< {MIN_OUTPUT_BYTES}); a tool that writes a "
              f"header and dies leaves a file too")

    # 5. Declared metrics, reported and FINITE. A fabricated 0.0 is what this forbids, and
    #    an inf or a nan passes a presence check while poisoning every figure downstream.
    r.metrics = dict(result.metrics)
    missing = [m for m in spec.metrics
               if not isinstance(result.metrics.get(m), (int, float))
               or not math.isfinite(result.metrics[m])]
    r.add("metrics_declared_and_finite", not missing,
          f"not reported or not finite: {missing}")

    # 6. Gates, split by role. Decision 0013: a weak design is not a broken Task.
    failed = [g for g in result.qc.gates if g.outcome is GateOutcome.FAIL]
    integrity = [g.gate for g in failed if g.role == "integrity"]
    acceptance = [g.gate for g in failed if g.role != "integrity"]
    r.add("integrity_gates", not integrity, f"failed: {integrity}")
    r.add("acceptance_gates", not acceptance, f"fell short: {acceptance}",
          role="acceptance")

    # 7. Measured wall time against the declared budget. The smoke is where a too-small
    #    walltime is learned; in a campaign it presents as a hang.
    declared = float(spec.resources.walltime_s or 0)
    r.add("walltime_covers_measurement", declared == 0 or r.wall_s <= declared,
          f"took {r.wall_s:.1f}s against a declared {declared:.0f}s")

    # 8. Measured against declared cost. Above 1.0 a declared figure sits BELOW measurement,
    #    and gate 5 plus the untrusted cap then refuse work that would in fact fit.
    for dim, estimated in (result.cost or {}).items():
        measured = float((result.cost_measured or {}).get(dim, 0.0))
        if estimated <= 0:
            continue
        ratio = measured / estimated
        r.cost_ratio[dim] = round(ratio, 4)
        r.add(f"cost_ratio[{dim}]", ratio <= 1.0,
              f"measured/declared = {ratio:.2f}; a declared figure below measurement makes "
              f"gate 5 refuse work that fits")
    return r


__all__ = ["MIN_OUTPUT_BYTES", "Report", "Row", "TaskReport", "validate_tasks"]
