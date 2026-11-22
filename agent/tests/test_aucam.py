"""T4 - IMPRESS-A as one AuCaM workflow, driven through AuCaM's own reporter.

The same reasoning as `test_http_adapter.py`: an unbuilt adapter is a gap, and a built one
that nothing runs is worse, because it looks finished. So this drives a real campaign through
a real `WorkflowReporter` and asserts the far side sees what an enclosing campaign manager
would - no fake reporter, no stub config, because AuCaM is a declared dev dependency and a
test written against a double would not have caught the thing that actually bit: its importable
name is `src.aucam`, not `aucam`.

Skipped, not failed, when the extra is absent: the adapter is optional and nothing else in the
package imports it.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("src.aucam", reason="the aucam extra is not installed")

from src.aucam import CampaignDecision, WorkflowConfig  # noqa: E402
from src.aucam.reporter import LocalDictReporter  # noqa: E402

from impress_a.cli import load_spec  # noqa: E402
from impress_a.integrations.aucam import (  # noqa: E402
    _BILLED,
    _narrow_budget,
    _ReporterSink,
    impress_backends,
    make_impress_worker,
    reward_fn,
    workflow_config,
)
from impress_a.runtime.offer import offer_for_spec  # noqa: E402

SPEC = "campaigns/mock-stabilize.yaml"

pytestmark = pytest.mark.asyncio


class _Recording(LocalDictReporter):
    """AuCaM's own reporter, with every report kept so the cadence is observable.

    The store it writes to is last-value-wins per workflow id, which is exactly the property
    that makes the FINAL report load-bearing - so the test asserts on both: the whole
    sequence, and the one value AuCaM would actually read afterwards.
    """

    def __init__(self, signals: dict | None = None, messages: dict | None = None) -> None:
        super().__init__("wf-1", {}, signals if signals is not None else {},
                         messages=messages if messages is not None else {})
        self.reports: list = []

    async def emit(self, **kw) -> None:
        await super().emit(**kw)
        self.reports.append(self._store[self._wf_id])


def _spec_with(**kw):
    spec = load_spec(SPEC)
    for key, value in kw.items():
        setattr(spec, key, value)
    return spec


async def test_the_adapter_builds_a_workflow_config_aucam_accepts():
    """Constructed by AuCaM's own pydantic model, so its validators are the judge.

    `WorkflowConfig` refuses a config with neither `block` nor `launch_cmd`, and refuses one
    with both. Building the real thing is the only way to know we are filling it correctly.
    """
    config = workflow_config(SPEC, report_interval_s=5.0)
    assert isinstance(config, WorkflowConfig)
    assert config.block is not None and config.launch_cmd is None
    assert config.supports_pause is True
    # A caller's staleness bound has to be a multiple of our report interval, and 3x is the
    # floor AuCaM's own contract names rather than a margin.
    assert config.stale_timeout_s == 20.0

    offer = offer_for_spec(load_spec(SPEC))
    assert config.spending_limit["gpu_hours"] == offer.cost["gpu_hours"].ceiling
    assert config.resources == {"cpus": offer.resources.cores,
                                "gpus": offer.resources.gpus}
    # Run time is bounded by max_wall_time_s; AuCaM refuses wall_hours in a spending limit.
    assert "wall_hours" not in config.spending_limit
    assert config.max_wall_time_s == float(offer.resources.walltime_s_ceiling)


async def test_a_campaign_runs_as_one_aucam_workflow_and_reports_through_its_reporter():
    """One launch, many reports, and the last one is the real one.

    An AuCaM workflow is one WHOLE campaign - its own cycle loop, its own termination - so
    the reporter sees a sequence that starts before any work exists, advances as results land,
    and ends with the campaign's own stop reason.
    """
    reporter = _Recording()
    block = make_impress_worker(SPEC, report_interval_s=0.05)
    await block(reporter, context={})

    statuses = [r.metrics["status"] for r in reporter.reports]
    assert statuses[0] == "starting"
    assert statuses[-1] == "stopped"
    assert reporter.reports[-1].metrics["stop_reason"], "a caller must be told why it ended"

    # Last-value-wins: what AuCaM reads after the workflow returns is the final report.
    final = reporter._store["wf-1"]
    assert final.metrics["status"] == "stopped"
    assert final.iteration == final.metrics["cycle"]

    seqs = [r.metrics["seq"] for r in reporter.reports]
    assert seqs == sorted(seqs), f"the absorption watermark went backwards: {seqs}"


async def test_the_score_is_a_float_a_bandit_can_rank():
    """Not a dict, because no shipped AuCaM policy can rank one.

    `BanditSchedulingPolicy`'s default reward is `1.0 if returncode == 0 else 0.0` -
    throughput - and its own comment says science scores belong to the controller. So the
    scalar is progress toward the asked-for front, and `reward_fn` is what a caller passes to
    rank arms by it instead.
    """
    reporter = _Recording()
    await make_impress_worker(SPEC, report_interval_s=0.05)(reporter, context={})

    for report in reporter.reports:
        assert isinstance(report.score, float), f"score is {type(report.score)}"
        assert 0.0 <= report.score <= 1.0

    class _Result:
        returncode, final_score = 0, reporter.reports[-1].score

    assert reward_fn(_Result()) == reporter.reports[-1].score
    _Result.returncode = -1
    assert reward_fn(_Result()) == 0.0, "a cancelled campaign is no evidence for its arm"


def _digest(*, measured: dict, declared: dict):
    """The three fields `_ReporterSink._billed` reads, and nothing else."""
    return types.SimpleNamespace(spend_measured=measured, spend=declared, in_flight={})


def _billed_gpu(*, measured: dict, declared: dict) -> float:
    return _ReporterSink._billed(_digest(measured=measured, declared=declared))["gpu_hours"]


async def test_the_metrics_carry_measured_spending_under_the_keys_aucam_charges():
    """Without these keys AuCaM charges resources x run time, the least accurate estimate.

    `CampaignManager._spent_so_far` reads `metrics[dim]` for each dimension in the spending
    limit before falling back to the resources it gave us x elapsed time. The figures reported
    are the MEASURED ones, because the declared ones feed gates that refuse graphs and sit
    above measurement deliberately - reporting those would hand the caller our headroom as if
    it were consumption (backlog G20).
    """
    reporter = _Recording()
    await make_impress_worker(SPEC, report_interval_s=0.05)(reporter, context={})

    final = reporter.reports[-1].metrics
    for dim in _BILLED:
        assert dim in final, f"{dim} is billed but was not reported: {sorted(final)}"
    # `cpu_hours` is deliberately NOT billed: the campaign's CPU figure covers the agent
    # process rather than the tasks, so charging it would bill AuCaM for our own overhead.
    assert "cpu_hours" not in final, "cpu_hours is excluded from billing"
    assert "cpus_in_use" in final and "gpus_in_use" in final

    # Measured over declared, and declared only as the surrogate's fallback. Asserted on
    # `_billed` itself because the mock chain returns in microseconds and measures no GPU
    # time at all, so a run of it can only ever exercise the fallback branch.
    assert _ReporterSink._billed(_digest(measured={"gpu_hours": 0.5},
                                         declared={"gpu_hours": 9.0}))["gpu_hours"] == 0.5, (
        "the measured figure must not lose to the declared one - declared cost is inflated "
        "to make gate 5 refuse pessimistically, and a caller charging that is misinformed")
    assert _billed_gpu(measured={"gpu_hours": 0.0}, declared={"gpu_hours": 9.0}) == 9.0, (
        "a surrogate measures nothing, and a zero charge would decalibrate cost learning")
    assert _billed_gpu(measured={"gpu_hours": 0.0}, declared={}) == 0.0, (
        "a dimension that ran and cost nothing stays in the report")


def test_mock_tools_are_billed_their_declared_cost():
    """A mock tool's measurement is milliseconds of Python, not the cost it simulates.

    Wall time x GPUs, rounded to 6 decimals, is 0 on a fast machine - so the declared figure
    was billed - but 1e-6 on a slower one, which then billed a whole run as free and made
    every comparison of spending between machines meaningless.
    """
    digest = _digest(measured={"gpu_hours": 1e-06}, declared={"gpu_hours": 0.006})
    assert _ReporterSink._billed(digest, mock=True)["gpu_hours"] == 0.006
    assert _ReporterSink._billed(digest)["gpu_hours"] == 1e-06, "real tools: measured wins"
    assert _ReporterSink._billed(_digest(measured={"gpu_hours": 0.0}, declared={}),
                                 mock=True)["gpu_hours"] == 0.0


async def test_the_callers_spending_limit_becomes_the_campaigns_own_budget():
    """Narrowed from the inside, not enforced from the outside.

    A limit enforced externally can only cancel a campaign after it has overspent. The same
    number as a budget is refused by `reserve` and gate 5 BEFORE a task runs, and the campaign
    stops itself with a reason naming the dimension instead of being killed with work in
    flight. A limit wider than the campaign's own budget must not loosen it.
    """
    spec = _spec_with(budget={"gpu_hours": 2.0, "cpu_hours": 12.0})
    assert _narrow_budget(spec, {"gpu_hours": 0.25}) == ["gpu_hours 2.0 -> 0.25"]
    assert spec.budget["gpu_hours"] == 0.25
    assert spec.budget["cpu_hours"] == 12.0, "an untouched dimension must stay untouched"

    wider = _spec_with(budget={"gpu_hours": 2.0})
    assert _narrow_budget(wider, {"gpu_hours": 99.0}) == []
    assert wider.budget["gpu_hours"] == 2.0, "a caller may not raise our own ceiling"

    # `wall_hours` is not a consumable the ledger can refuse against, so it is never a budget.
    assert _narrow_budget(_spec_with(budget={}), {"wall_hours": 1.0}) == []


async def test_a_pause_from_aucam_is_translated_into_the_bridges_own_vocabulary():
    """The adapter translates transport, and the bridge owns the behaviour.

    Kept apart on purpose: `reporting.py` names no superstrate, so a second one costs an
    adapter rather than a second payload. `test_campaign.py` asserts what PAUSE then DOES -
    that admission stops and in-flight work runs on.
    """
    from impress_a.integrations.reporting import PAUSE, RESUME

    reporter = _Recording(signals={"wf-1": CampaignDecision.PAUSE})
    sink = _ReporterSink(reporter)
    assert await sink.poll() == PAUSE
    assert await sink.poll() is None, "a signal is consumed, not latched"

    reporter._signals["wf-1"] = CampaignDecision.RESUME
    assert await sink.poll() == RESUME


async def test_an_aucam_campaign_launches_a_whole_impress_campaign_and_charges_what_it_reported(
        monkeypatch):
    """The whole integration, end to end, through AuCaM's own manager.

    Everything else in this file tests a seam. This runs the real thing: AuCaM builds its own
    spec from our `WorkflowConfig`, launches the workflow, runs its policy cycles, charges the
    spending we reported and terminates on its controller's goal - while IMPRESS-A runs its own
    cycle loop inside, on AuCaM's engine (CON-1): the manager is built over
    `impress_backends()`, the worker takes `flow`, and the campaign builds no engine of its own.

    The assertion that matters is the last one. AuCaM charges a workflow from `metrics[dim]`
    when the workflow reports it and resources x run time when it does not, and our limit
    sits multiples above measurement on purpose - so a charge near it would mean AuCaM
    billed us for headroom we never used (backlog G20).
    """
    from src.aucam import (
        BanditSchedulingPolicy,
        CampaignBudget,
        CampaignController,
        CampaignManager,
        CampaignSpec,
        LaunchRule,
    )

    from impress_a.exec import backend as backend_mod

    config = workflow_config(SPEC, name="impress", report_interval_s=0.1)
    backends = await impress_backends(SPEC)
    assert [b.name for b in backends] == ["compute", "local"]

    async def no_second_engine(*a, **kw):
        raise AssertionError("the campaign built its own engine instead of using AuCaM's")
    monkeypatch.setattr(backend_mod, "make_engine_bounded", no_second_engine)

    class _OneRun(CampaignController):
        def __init__(self) -> None:
            super().__init__(rules=[LaunchRule("impress")], goal_type="impress", goal_n=1)

    try:
        outcome = await CampaignManager(backend=backends).run(CampaignSpec(
            name="impress-under-aucam",
            budget=CampaignBudget(capacity={"cpus": 1024, "gpus": 64},
                                  max_concurrent_workflows=1, max_concurrency_per_workflow=1,
                                  spending={"gpu_hours": 5.0, "cpu_hours": 30.0}),
            controller=_OneRun(),
            workflows=[config],
            scheduling_policy=BanditSchedulingPolicy(reward_fn=reward_fn),
            policy_interval_s=0.1,
            shutdown_timeout_s=20.0))
    finally:
        for b in backends:
            await b.shutdown()

    assert outcome.completed == {"impress": 1}, f"completed={outcome.completed}"
    assert not outcome.cancelled and not outcome.failed
    assert outcome.goal_reached and outcome.budget_cancels == 0
    # The controller stopped because its goal was reached, which AuCaM reports as such.
    assert outcome.exit_reason == "goals_satisfied"

    # Charged from what we reported, not estimated from the limit we were given. The limit is
    # orders of magnitude above what this run measures, so a charge near it would show.
    dim = _BILLED[0]
    charged = outcome.spent.get(dim, 0.0)
    limit = config.spending_limit[dim]
    assert 0.0 <= charged < limit, (
        f"AuCaM charged {charged} {dim} against a limit of {limit} - a figure at or "
        f"above the limit means it did not read our reported metrics")


async def test_a_worker_given_an_engine_without_our_routes_says_so_at_start():
    """AuCaM's default engine has one unnamed backend; ours routes tasks to `compute` and
    `local`. That must fail at start naming the fix, not hang or fail at the first task."""
    from radical.asyncflow import LocalExecutionBackend, WorkflowEngine

    flow = await WorkflowEngine.create(backend=await LocalExecutionBackend(name="default"))
    try:
        with pytest.raises(RuntimeError, match="impress_backends"):
            await make_impress_worker(SPEC, report_interval_s=0.05)(
                _Recording(), context={}, flow=flow)
    finally:
        await flow.shutdown()


async def test_messages_from_aucam_reach_on_message_at_launch_and_while_running():
    """A promoted model reaches the campaign two ways: the type's sticky value in
    `context["messages"]` before it starts, and a message while it runs (`PolicyResult.messages`
    -> `reporter.messages()` -> the bridge -> `on_message`)."""
    got: list = []

    def on_message(manager, name, payload):
        assert manager.executor is not None
        got.append((name, payload))

    sent = {"seq": 1, "name": "model", "payload": {"path": "/m/v3"}, "sent_at": 0.0}
    reporter = _Recording(messages={"wf-1": [sent]})
    await make_impress_worker(SPEC, report_interval_s=0.05, on_message=on_message)(
        reporter, context={"messages": {"model": {"path": "/m/v2"}}})
    assert got == [("model", {"path": "/m/v2"}), ("model", {"path": "/m/v3"})]


async def test_a_message_handler_that_raises_does_not_stop_the_campaign(caplog):
    def broken(manager, name, payload):
        raise RuntimeError("bad weights")

    reporter = _Recording(messages={"wf-1": [
        {"seq": 1, "name": "model", "payload": None, "sent_at": 0.0}]})
    await make_impress_worker(SPEC, report_interval_s=0.05, on_message=broken)(
        reporter, context={})
    assert reporter.reports[-1].metrics["status"] == "stopped"
    assert "on_message failed on 'model'" in caplog.text


async def test_messages_without_a_handler_are_logged_and_dropped(caplog):
    sink = _ReporterSink(_Recording(messages={"wf-1": [
        {"seq": 1, "name": "model", "payload": 1, "sent_at": 0.0}]}))
    assert await sink.messages() == [("model", 1)]
    assert await sink.messages() == []
    await make_impress_worker(SPEC, report_interval_s=0.05)(
        _Recording(), context={"messages": {"model": 1}})
    assert "message 'model' from the caller dropped - no on_message handler" in caplog.text
