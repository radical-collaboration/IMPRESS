"""`impress-a validate-tasks`, checked before it is pointed at an allocation.

The command's purpose is to justify `impress-a trust --assert`: granting a pattern trust
without the three clean runs the interlock would require is only honest if the Tasks are proven
**on this hardware, in this venv, through these adapters**. A validator nobody checked would
make that argument from a run nobody checked.

It cannot be exercised by a passing real run here - the only chain available locally is the mock
one, and a mock tool fails the real-toolkit row by design - so every row is driven against a
synthetic `ExecutionResults` instead. That is also the shape the plan asks for: green before the
tool meets hardware.
"""
from __future__ import annotations

import pytest

from impress_a.analysis.validate_tasks import MIN_OUTPUT_BYTES, Report, _check_task
from impress_a.compose.composer import Composer
from impress_a.core.artifacts import ArtifactRef
from impress_a.core.decision import ExperimentIntent
from impress_a.core.qc import GateOutcome, GateResult, QCReport, QCVerdict
from impress_a.core.types import ArtifactType
from impress_a.exec.dispatch import ExecutionResults
from impress_a.tools.agent import TaskResult, TaskUsage
from impress_a.tools.registry import Registry

REAL = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
        "boltz_predict"]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _graph(reg, stages=REAL):
    return Composer(reg).compose(
        ExperimentIntent(goal="g", stages=stages, replicas=1), "validate")


def _good(reg, tool, tmp_path, **over):
    """A result that passes every row for `tool`, so each test breaks exactly one thing."""
    spec = reg.get(tool)
    outputs = {}
    for port, port_spec in spec.outputs.items():
        f = tmp_path / f"{tool}_{port}.out"
        f.write_bytes(b"x" * (MIN_OUTPUT_BYTES + 1))
        outputs[port] = ArtifactRef(type=port_spec.type, path=str(f))
    result = TaskResult(
        tool=tool, outputs=outputs,
        metrics={m: 1.0 for m in spec.metrics},
        qc=QCReport(gates=[GateResult(gate="output_present", outcome=GateOutcome.PASS)],
                    verdict=QCVerdict.PASS),
        cost=dict(spec.cost_model.cost),
        cost_measured={d: c * 0.3 for d, c in spec.cost_model.cost.items()},
        usage=TaskUsage(wall_s=1.0, phases={"run": 1.0}))
    for key, value in over.items():
        setattr(result, key, value)
    return result


def _report(reg, tool, result, tmp_path, stages=REAL):
    graph = _graph(reg, stages)
    tid = next(t for t, n in graph.nodes.items() if n.tool == tool)
    results = ExecutionResults(graph_id=graph.id, per_task={tid: result})
    return _check_task(reg, graph.nodes[tid], tid, results)


def _rows(report):
    return {r.check: r for r in report.rows}


def _shell_code(path: str) -> str:
    """A shell script with its comments removed.

    Every one of these checks is about what a script DOES, and these scripts carry long
    comments naming the thing each check looks for - `--model`, `dragon-config`, `FAB_LIB` -
    because that is where the reasoning lives. Three tests in this repository have now caught
    their own documentation on the first run, so the stripper is shared rather than the lesson
    being relearned. Crude on purpose: a `#` inside a quoted string would be cut too, and
    nothing here depends on one.
    """
    import pathlib

    return "\n".join(line.split("#", 1)[0]
                      for line in pathlib.Path(path).read_text().splitlines())


def test_a_clean_real_task_passes_every_row(reg, tmp_path):
    """The baseline, so each test below breaks exactly one thing and the rest stay green."""
    report = _report(reg, "fastrelax", _good(reg, "fastrelax", tmp_path), tmp_path)
    bad = [r.check for r in report.rows if not r.ok]
    assert bad == [], bad
    assert report.ok


def test_validate_tasks_fails_a_task_that_omits_a_declared_metric(reg, tmp_path):
    """A declared metric that does not arrive is an INTEGRITY failure.

    This is the row that catches the thing the gates cannot: `metrics_reported` only names the
    metrics someone remembered to list in a gate, while this reads `ToolSpec.metrics` - every
    metric the tool CLAIMS to report. `interaction_energy` was declared by nothing and
    computed by nothing for the whole life of the project.
    """
    result = _good(reg, "fastrelax", tmp_path)
    del result.metrics["interaction_energy"]
    report = _report(reg, "fastrelax", result, tmp_path)

    row = _rows(report)["metrics_declared_and_finite"]
    assert not row.ok and row.role == "integrity"
    assert "interaction_energy" in row.detail
    assert not report.ok


def test_a_metric_that_is_not_finite_fails_too(reg, tmp_path):
    """`inf` and `nan` pass a presence check and poison every figure downstream.

    A mean over a column containing one `nan` is `nan`, and the harness would publish it.
    """
    for value in (float("inf"), float("nan")):
        result = _good(reg, "fastrelax", tmp_path)
        result.metrics["fa_rep"] = value
        report = _report(reg, "fastrelax", result, tmp_path)
        assert not _rows(report)["metrics_declared_and_finite"].ok, value


def test_validate_tasks_fails_a_task_whose_declared_output_port_is_missing(reg, tmp_path):
    """A port the spec declares and the adapter did not produce.

    Nothing downstream could consume it, and the composer type-checked a graph that depends on
    it - so this is the tool breaking its own contract rather than a bad design.
    """
    result = _good(reg, "rfd3_design", tmp_path)
    result.outputs = {}
    report = _report(reg, "rfd3_design", result, tmp_path)

    assert not _rows(report)["output[backbone]"].ok
    assert "not produced" in _rows(report)["output[backbone]"].detail
    assert not report.ok


def test_an_output_of_the_wrong_declared_type_fails(reg, tmp_path):
    """A handle cannot disagree with what the composer type-checked.

    The type comes from the spec's declared port, so this should be impossible through
    `_as_artifacts` - which is why checking it costs nothing and why a tool that found a way
    to do it is worth knowing about before an allocation.
    """
    result = _good(reg, "rfd3_design", tmp_path)
    result.outputs["backbone"] = ArtifactRef(
        type=ArtifactType.METRIC_SET, path=str(tmp_path / "rfd3_design_backbone.out"))
    report = _report(reg, "rfd3_design", result, tmp_path)

    row = _rows(report)["output[backbone]"]
    assert not row.ok and "declared Backbone" in row.detail


def test_a_trivially_small_output_fails_even_though_the_port_is_there(reg, tmp_path):
    """The `*.cif.gz` trajectory bug, in the form a size check can catch.

    That one selected the wrong file of the right extension - a 1.7 MB trajectory beside a
    19 KB design - and the size check here catches its sibling: a tool that writes a header
    and dies leaves a file too, and `output_present` is satisfied by its existence.
    """
    stub = tmp_path / "stub.pdb"
    stub.write_bytes(b"HEADER\n")
    result = _good(reg, "rfd3_design", tmp_path)
    result.outputs["backbone"] = ArtifactRef(type=ArtifactType.BACKBONE, path=str(stub))
    report = _report(reg, "rfd3_design", result, tmp_path)

    row = _rows(report)["output[backbone]"]
    assert not row.ok and "bytes" in row.detail

    missing = _good(reg, "rfd3_design", tmp_path)
    missing.outputs["backbone"] = ArtifactRef(type=ArtifactType.BACKBONE,
                                              path=str(tmp_path / "nope.pdb"))
    assert not _rows(_report(reg, "rfd3_design", missing, tmp_path))["output[backbone]"].ok


def test_validate_tasks_separates_acceptance_from_integrity(reg, tmp_path):
    """A weak design is not a broken Task, and the exit code must say so (decision 0013).

    A validation pass that demanded good designs would refuse a working chain on its first
    mediocre draw - and then `impress-a trust --assert` could never cite a clean run, so the
    experiment could not start.
    """
    result = _good(reg, "fastrelax", tmp_path)
    result.qc = QCReport(
        gates=[GateResult(gate="metric_in_range[interaction_energy]",
                          outcome=GateOutcome.FAIL, role="acceptance")],
        verdict=QCVerdict.FAIL)
    report = _report(reg, "fastrelax", result, tmp_path)

    assert not _rows(report)["acceptance_gates"].ok
    assert _rows(report)["integrity_gates"].ok
    assert report.ok, "an acceptance failure must not fail the validation run"

    broke = _good(reg, "fastrelax", tmp_path)
    broke.qc = QCReport(gates=[GateResult(gate="metrics_reported",
                                          outcome=GateOutcome.FAIL, role="integrity")],
                        verdict=QCVerdict.FAIL)
    assert not _report(reg, "fastrelax", broke, tmp_path).ok


def test_validate_tasks_flags_a_declared_walltime_below_measurement(reg, tmp_path):
    """The smoke is where a too-small walltime is learned; in a campaign it is a hang.

    `import pyrosetta` took 471 s off HDD-backed Lustre against packmin's 300 s budget, and
    what that looked like from outside was a task that never finished - a timeout names a
    budget, not a cause. The phase breakdown is the other half of this and has its own row.
    """
    declared = reg.get("fastrelax").resources.walltime_s
    result = _good(reg, "fastrelax", tmp_path,
                   usage=TaskUsage(wall_s=declared + 1.0, phases={"run": declared + 1.0}))
    report = _report(reg, "fastrelax", result, tmp_path)

    row = _rows(report)["walltime_covers_measurement"]
    assert not row.ok and f"{declared:.0f}s" in row.detail


def test_a_task_with_no_phase_breakdown_fails(reg, tmp_path):
    """Without it, import time cannot be separated from work.

    That distinction cost an allocation to learn and a second one to diagnose: 290 s of import
    and 290 s of work are the same number in a timeout message.
    """
    result = _good(reg, "fastrelax", tmp_path, usage=TaskUsage(wall_s=1.0, phases={}))
    assert not _rows(_report(reg, "fastrelax", result, tmp_path))["phases_recorded"].ok


def test_a_cost_declared_below_measurement_fails(reg, tmp_path):
    """Above 1.0, gate 5 and the untrusted cap refuse work that would in fact fit.

    The declared figures sit 2.25x-69x above measurement on purpose (backlog A11), so a ratio
    over 1.0 is not a tuning opportunity - it means a gate has started lying in the direction
    that costs a campaign its chain.
    """
    spec = reg.get("fastrelax")
    result = _good(reg, "fastrelax", tmp_path,
                   cost_measured={d: c * 1.5 for d, c in spec.cost_model.cost.items()})
    report = _report(reg, "fastrelax", result, tmp_path)

    row = next(r for r in report.rows if r.check.startswith("cost_ratio"))
    assert not row.ok and "1.50" in row.detail
    assert report.cost_ratio == {"cpu_hours": 1.5}


def test_validate_tasks_refuses_a_mock_tool(reg, tmp_path):
    """Per Task, where gate 6 checks per campaign - and here it matters more.

    A validation run that executed mocks would certify them as proven, and
    `impress-a trust --assert` cites that run as its reason. The mock chain would then be
    asserted-trusted on a GPU allocation, which is the failure gate 6 exists to stop, arrived
    at through the tool meant to prevent it.
    """
    mock_chain = ["mock_generate", "mock_design"]
    report = _report(reg, "mock_generate", _good(reg, "mock_generate", tmp_path),
                     tmp_path, stages=mock_chain)

    row = _rows(report)["real_toolkit"]
    assert not row.ok and row.role == "integrity"
    assert not report.ok


def test_a_task_that_never_ran_reports_only_that(reg, tmp_path):
    """Everything else is meaningless, so nothing else is claimed.

    A report listing eight passing rows for a task that failed to start would be worse than
    useless: it would read as evidence.
    """
    graph = _graph(reg)
    tid = next(t for t, n in graph.nodes.items() if n.tool == "ligandmpnn_design")
    results = ExecutionResults(graph_id=graph.id,
                              failures={tid: "ModuleNotFoundError: ml_collections"})
    report = _check_task(reg, graph.nodes[tid], tid, results)

    assert [r.check for r in report.rows] == ["ran"]
    assert "ml_collections" in report.rows[0].detail
    assert not report.ok


def test_the_report_names_every_failing_row_in_its_table(reg, tmp_path):
    """The table is what an operator reads before deciding to assert trust.

    A summary that said `FAIL` without saying which check failed would send them to the JSON,
    and the JSON is the thing nobody opens on a login node at the end of a queue wait.
    """
    result = _good(reg, "fastrelax", tmp_path)
    del result.metrics["interaction_energy"]
    report = Report(campaign_id="c", tasks=[_report(reg, "fastrelax", result, tmp_path)])

    table = report.table()
    assert "FAIL" in table
    assert "metrics_declared_and_finite" in table
    assert "interaction_energy" in table
    assert not report.ok


def test_a_campaign_with_no_chain_is_an_error_not_an_empty_pass(reg):
    """An empty report is not a clean one.

    `Report.ok` requires at least one Task, because a spec with no `stages` would otherwise
    validate successfully and be cited as the reason trust was asserted.
    """
    assert not Report(campaign_id="c").ok
    assert not Report(campaign_id="c", errors=["no stages"]).ok


# ---------------------------------------------------------------------------
# The launchers. Checked because a launcher bug costs an allocation to find.
# ---------------------------------------------------------------------------

def test_the_launcher_accepts_exactly_two_commands():
    """`IMPRESS_A_COMMAND` is a switch, so an unknown value must fail at submit time.

    A typo that fell through to the `run` branch would spend a validation allocation on a
    campaign - and a campaign whose chain has not been validated is the thing step 1 exists
    to prevent.
    """
    launcher = _shell_code("scripts/delta_gpu_run.sh")
    assert 'IMPRESS_A_COMMAND="${IMPRESS_A_COMMAND:-run}"' in launcher, \
        "the default must be `run`, so an existing submission is unaffected"
    assert "validate-tasks)" in launcher and "run)" in launcher
    assert "ERROR: IMPRESS_A_COMMAND must be" in launcher, \
        "an unknown command must fail rather than fall through to a campaign"
    assert '--model' not in launcher.split("validate-tasks)")[1].split(";;")[0], \
        "a validation pass has no reasoner, so passing a model would be meaningless"
    assert 'RUNNER_ARGS=( validate-tasks "${CAMPAIGN}" --out "${WORKDIR}/validation" )' \
        in launcher


def test_the_validate_tasks_launcher_delegates_rather_than_duplicating():
    """One copy of the Dragon bring-up, because the second copy is the one that rots.

    Everything that makes a Delta job work here was bought one burned allocation at a time -
    the Cray PE module-name case, the FAB_LIB autodetect, `dragon-config -c` before `add`, the
    `-w ssh`/`-t tcp`/`--network-config` combination, SLURM_OVERLAP, the EXIT trap. A launcher
    that reimplemented any of it would be a launcher that runs less often than the one it
    copied from.
    """
    wrapper = _shell_code("scripts/delta_validate_tasks.sh")
    assert "export IMPRESS_A_COMMAND=validate-tasks" in wrapper
    assert 'exec "${HERE}/delta_gpu_run.sh" "$@"' in wrapper
    for borrowed in ("dragon-config", "FAB_LIB", "network-config", "SLURM_OVERLAP",
                     "#SBATCH"):
        assert borrowed not in wrapper, (
            f"the wrapper reimplements {borrowed!r}; it must delegate, and --nodes/--time/"
            f"--partition belong on the sbatch line where they are visible")
