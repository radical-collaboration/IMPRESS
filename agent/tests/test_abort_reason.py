"""What the abort message says, which until now was a count and nothing else.

`CampaignAborted: 3 consecutive all-failed runs` was the entire diagnosis a campaign offered
when it gave up. The information was never missing: `_record_evidence` has the run's
`ExecutionResults` in hand, and `results.failures` already holds `"{type}: {message}"` keyed by
node id. It simply was not carried the last few lines to the one string an operator reads.

**It cost four runs to find a one-character mistake**, downstream, with `--heartbeat 1` and no
useful output at any level: a relative `input_spec_path` resolved against the campaign file's
directory. On a laptop that is minutes; on an allocation each retry is queue time.

Driven against synthetic `ExecutionResults` rather than a campaign, deliberately. Three of the
four cases below -- a dependent task failed by its upstream, an integrity gate with no exception
at all, and the unreachable branch -- are states a local mock run reaches rarely or never, and a
test that could only produce the easy one would be asserting the easy one.
"""
from __future__ import annotations

from impress_a.compose.composer import Composer
from impress_a.core.decision import ExperimentIntent
from impress_a.core.qc import GateOutcome, GateResult, QCReport, QCVerdict
from impress_a.exec.dispatch import ExecutionResults
from impress_a.runtime.executor import why_run_failed
from impress_a.tools.agent import TaskResult, TaskUsage
from impress_a.tools.registry import Registry

STAGES = ["rfd3_design", "ligandmpnn_design", "packmin", "boltz_predict"]


def _graph():
    return Composer(Registry().load()).compose(
        ExperimentIntent(goal="g", stages=STAGES, replicas=1), "abort")


def _ids(graph) -> dict[str, str]:
    """tool -> node id, so a test can name a stage without hard-coding `l0_s2_...`."""
    return {node.tool: tid for tid, node in graph.nodes.items()}


def _result(tool: str, *gates: GateResult) -> TaskResult:
    return TaskResult(tool=tool, outputs={}, metrics={},
                      qc=QCReport(gates=list(gates),
                                  verdict=QCVerdict.FAIL if gates else QCVerdict.PASS),
                      cost={}, cost_measured={}, usage=TaskUsage(wall_s=1.0))


def test_the_message_names_the_task_the_tool_and_the_reason():
    """The whole point of the change, on item 41's own evidence.

    A `FileNotFoundError` from a tool adapter used to leave only a count. The path in the
    message is what turns four runs into one.
    """
    graph = _graph()
    tid = _ids(graph)["rfd3_design"]
    results = ExecutionResults(
        graph_id=graph.id,
        failures={tid: "FileNotFoundError: [Errno 2] No such file or directory: 'in.json'"})

    why = why_run_failed(graph, results)
    assert tid in why
    assert "rfd3_design" in why
    assert "FileNotFoundError" in why
    assert "in.json" in why


def test_the_cause_is_named_rather_than_the_tasks_its_failure_took_down():
    """A dependent task is failed by asyncflow the moment its upstream raises.

    So a four-stage graph whose second stage fails reports two failures, and the one that
    arrives *second* in the dict is the only one that says anything. Naming "the first entry"
    would be right only while the dict happens to be ordered the convenient way.
    """
    graph = _graph()
    ids = _ids(graph)
    results = ExecutionResults(graph_id=graph.id, failures={
        ids["boltz_predict"]: ("DependencyFailureError: Cannot execute "
                               f"'{ids['boltz_predict']}' due to dependency failure"),
        ids["packmin"]: "RuntimeError: rosetta scripts exited 1",
    })

    why = why_run_failed(graph, results)
    assert "packmin" in why and "rosetta scripts exited 1" in why
    assert "DependencyFailureError" not in why, (
        "the consequence was reported instead of the cause"
    )


def test_a_graph_whose_every_failure_is_a_dependency_failure_says_so():
    """Rather than reporting a `DependencyFailureError` as if it were a diagnosis.

    It happens when the failing upstream is not in this run -- a stage executed separately, or
    a task abandoned at collect -- and the honest answer is that the cause is elsewhere.
    """
    graph = _graph()
    ids = _ids(graph)
    results = ExecutionResults(graph_id=graph.id, failures={
        ids["boltz_predict"]: "DependencyFailureError: due to dependency failure"})

    why = why_run_failed(graph, results)
    assert "upstream of this run" in why
    assert "boltz_predict" in why


def test_an_integrity_failure_with_no_exception_still_names_its_gate():
    """The case that had no message at all, and it is a shipped lab arm.

    `_record_evidence` counts a run as failed when any task raised **or** any integrity gate
    failed, and in the second case `results.failures` is empty. The `hopeless` arm of the mock
    lab aborts exactly this way -- `has_secondary_structure` under its floor, nothing raised --
    so the campaign reported a count for a failure it could describe precisely.
    """
    graph = _graph()
    tid = _ids(graph)["rfd3_design"]
    gate = GateResult(gate="has_secondary_structure", outcome=GateOutcome.FAIL,
                      observed=0.21, threshold=0.3, role="integrity",
                      detail="ss_fraction=0.21 < 0.3 (likely disordered)")
    results = ExecutionResults(graph_id=graph.id,
                               per_task={tid: _result("rfd3_design", gate)})

    why = why_run_failed(graph, results)
    assert "no task raised" in why
    assert "has_secondary_structure" in why
    assert "0.21" in why and "0.3" in why
    assert "rfd3_design" in why


def test_an_acceptance_failure_alone_is_not_what_this_reports():
    """Decision 0013's split, kept intact in the diagnosis.

    An acceptance shortfall does not make a run count as failed, so if the message ever named
    one it would be describing something that did not cause the abort.
    """
    graph = _graph()
    tid = _ids(graph)["rfd3_design"]
    gate = GateResult(gate="metric_in_range[ss_fraction]", outcome=GateOutcome.FAIL,
                      observed=0.45, threshold=[0.5, None], role="acceptance")
    results = ExecutionResults(graph_id=graph.id,
                               per_task={tid: _result("rfd3_design", gate)})

    why = why_run_failed(graph, results)
    assert "metric_in_range" not in why
    assert "unreachable" in why, why


def test_the_reason_is_one_line_because_one_report_matches_per_line():
    """`analysis/mock_lab.py`'s `ABORT_RE` is anchored with `$`.

    A multi-line task message would silently throw away everything after the first newline in
    the one report that reads this string, and a tool's own error is often multi-line.
    """
    graph = _graph()
    tid = _ids(graph)["rfd3_design"]
    results = ExecutionResults(graph_id=graph.id, failures={
        tid: "RuntimeError: line one\nline two\n  line three " + "x" * 600})

    why = why_run_failed(graph, results)
    assert "\n" not in why
    assert "line one line two line three" in why
    assert len(why) < 600, "a long message must be truncated, not carried whole"
    assert why.endswith("…")
