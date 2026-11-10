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

import pytest

pytest.importorskip("src.aucam", reason="the aucam extra is not installed")

from src.aucam import CampaignDecision, WorkflowConfig  # noqa: E402
from src.aucam.reporter import LocalDictReporter  # noqa: E402

from impress_a.cli import load_spec  # noqa: E402
from impress_a.integrations.aucam import (  # noqa: E402
    _narrow_budget,
    _ReporterSink,
    launch_bounds,
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

    def __init__(self, signals: dict | None = None) -> None:
        super().__init__("wf-1", {}, signals if signals is not None else {})
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
    assert config.declared_spending["gpu_hours"] == offer.cost["gpu_hours"].expected
    assert config.spending_limit["gpu_hours"] == offer.cost["gpu_hours"].ceiling
    assert config.resources == {"cpus": offer.resources.cores,
                                "gpus": offer.resources.gpus}
    # `wall_hours` is declared but never limited: it is an input to AuCaM's proration, and a
    # limit on it would cancel a campaign for taking the time it said it would take.
    assert "wall_hours" in config.declared_spending
    assert "wall_hours" not in config.spending_limit


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


async def test_the_metrics_carry_measured_spending_under_the_keys_aucam_charges():
    """Without these keys AuCaM prorates our DECLARED cost, which is inflated on purpose.

    `CampaignManager._spent_so_far` reads `metrics[dim]` for each dimension in the spending
    limit before falling back to proration, and proration is the least accurate of its three
    charging methods. The figures reported are the MEASURED ones, because the declared ones
    feed gates that refuse graphs and sit above measurement deliberately - reporting those
    would hand the caller our headroom as if it were consumption (backlog G20).
    """
    reporter = _Recording()
    await make_impress_worker(SPEC, report_interval_s=0.05)(reporter, context={})

    final = reporter.reports[-1].metrics
    assert final["cpu_hours"] == final["spend_measured"]["cpu_hours"]
    assert final["cpu_hours"] != final["spend"]["cpu_hours"], (
        "the measured figure must not be the declared one - declared cost is inflated to "
        "make gate 5 refuse pessimistically, and a caller charging that is misinformed")
    assert "cpus_in_use" in final and "gpus_in_use" in final


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


async def test_the_bounds_a_caller_attaches_are_not_on_the_workflow_config():
    """`bounds` lives on `LaunchRequest`, so it cannot ride along with the config.

    Worth its own test because getting this wrong is silent: a `bounds` key passed to
    `WorkflowConfig` would be dropped by pydantic and the caller's scheduler would size every
    run at the type default forever, with nothing saying so.
    """
    offer = offer_for_spec(load_spec(SPEC))
    bounds = launch_bounds(offer)
    assert set(bounds) == {"gpu_hours", "cpu_hours"}, "wall_hours is not a billed dimension"
    for dim, (lo, hi) in bounds.items():
        assert lo <= hi and lo == offer.cost[dim].floor and hi == offer.cost[dim].ceiling
    assert "bounds" not in WorkflowConfig.model_fields


async def test_an_aucam_campaign_launches_a_whole_impress_campaign_and_charges_what_it_reported():
    """The whole integration, end to end, through AuCaM's own manager.

    Everything else in this file tests a seam. This runs the real thing: AuCaM builds its own
    spec from our `WorkflowConfig`, launches the workflow, runs its policy cycles, charges the
    spending we reported and terminates on its controller's goal - while IMPRESS-A runs its own
    cycle loop on its own engine inside.

    Two engines are live at once, which is the arrangement the adapter exists to make safe: we
    do NOT accept AuCaM's `flow`, because `WorkflowEngine.__init__` captures the loop it is
    built on and the executor must build its own through `make_engine_bounded`.

    The assertion that matters is the last one. AuCaM charges a workflow from `metrics[dim]`
    when the workflow reports it and prorates its declared cost when it does not, and our
    declared figures sit multiples above measurement on purpose - so a campaign charged by
    proration would be billed for headroom it never used (backlog G20).
    """
    from src.aucam import (
        BanditSchedulingPolicy,
        CampaignBudget,
        CampaignController,
        CampaignManager,
        CampaignSpec,
        LaunchRule,
    )

    config = workflow_config(SPEC, name="impress", report_interval_s=0.1)

    class _OneRun(CampaignController):
        def __init__(self) -> None:
            super().__init__(rules=[LaunchRule("impress")], goal_type="impress", goal_n=1)

    outcome = await CampaignManager().run(CampaignSpec(
        name="impress-under-aucam",
        budget=CampaignBudget(max_concurrent_workflows=1, max_concurrency_per_workflow=1,
                              spending={"gpu_hours": 5.0, "cpu_hours": 30.0}),
        controller=_OneRun(),
        workflows=[config],
        scheduling_policy=BanditSchedulingPolicy(reward_fn=reward_fn),
        policy_interval_s=0.1,
        shutdown_timeout_s=20.0))

    assert outcome.completed == {"impress": 1}, f"completed={outcome.completed}"
    assert not outcome.cancelled and not outcome.failed
    assert outcome.goal_reached and outcome.budget_cancels == 0
    assert outcome.exit_reason == "controller_terminate"

    # Charged from what we reported, not prorated from what we declared. The campaign's own
    # declared spend is orders of magnitude larger, so proration would be unmistakable here.
    charged = outcome.spent.get("cpu_hours", 0.0)
    declared = config.declared_spending["cpu_hours"]
    assert 0.0 <= charged < declared, (
        f"AuCaM charged {charged} cpu_hours against a declared {declared} - a figure at or "
        f"above the declared one means it prorated instead of reading our reported metrics")
