"""T2 - mock campaign. A complete campaign end to end on a laptop.

Real manager, real policy, real composer, real validator, real state and provenance,
with ConcurrentExecutionBackend and mock tools. Exercises every layer above the substrate.
"""
import asyncio

import pytest

from impress_a.compose.validate import SiteCaps
from impress_a.core.artifacts import (AUTHORITY_ASSAY, Property, PropertySource,
                                      SourceKind)
from impress_a.core.decision import ExperimentIntent
from impress_a.core.pareto import Direction, Objective
from impress_a.core.qc import QCVerdict
from impress_a.control.plane import InProcessControlPlane
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.agentic import FourNodePolicy
from impress_a.policy.explicit import ReplayPolicy, ThresholdPolicy
from impress_a.policy.external import ExternalPolicy
from impress_a.policy.oracle import OraclePolicy
from impress_a.policy.wrappers import NullPolicy, RuleCorrectionsPolicy
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55),
        Objective(name="ddg", direction=Direction.MIN)]


def spec(cid, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        max_cycles=kw.pop("max_cycles", 4),
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root="/tmp/impress_a_tests", **kw)


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


@pytest.mark.parametrize("make,name", [
    (lambda: ThresholdPolicy(), "D"),
    (lambda: OraclePolicy(fallback=ThresholdPolicy()), "B"),
    (lambda: FourNodePolicy(), "A"),
])
async def test_autonomous_models_reach_termination(reg, make, name):
    mgr = CampaignManager(spec(f"t-{name}"), make(), reg)
    res = await mgr.run()
    assert res.stop_reason, "must terminate with a stated reason"
    assert len(res.tree) > 0, f"{name} produced no candidates"
    assert res.cycles <= 4


async def test_null_policy_stops_immediately(reg):
    res = await CampaignManager(spec("t-null"), NullPolicy(), reg).run()
    assert res.cycles == 0 and len(res.tree) == 0


async def test_lying_tool_is_caught_by_qc(reg):
    """mock_noodle completes successfully and reports confident `designability`
    while producing no secondary structure. Only the QC gate catches it - the
    Part A failure mode, manufactured on purpose."""
    from impress_a.compose.composer import Composer
    from impress_a.exec.backend import make_engine
    from impress_a.exec.dispatch import Dispatcher

    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=["mock_noodle"]))
    flow, _ = await make_engine("concurrent", {"workers": 1})
    try:
        res = await Dispatcher(flow, reg).run(g)
    finally:
        await flow.shutdown()
    assert not res.failures, "the tool must SUCCEED - that is what makes it silent"
    assert res.merged_metrics()["designability"] > 0.9, "and report confident numbers"
    assert res.merged_qc().verdict is QCVerdict.FAIL, "QC must catch it anyway"


async def test_guard_corrects_every_decision(reg):
    guarded = RuleCorrectionsPolicy(ThresholdPolicy(base_replicas=99),
                                    max_replicas=2, forbid_tools=("mock_noodle",))
    res = await CampaignManager(spec("t-guard"), guarded, reg).run()
    assert guarded.corrections, "guard must have corrected an over-large request"


async def test_provisional_results_are_marked_suspect(reg):
    """A novel composition pattern runs, but nothing unreviewed is quietly believed."""
    s = spec("t-suspect", max_cycles=1)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    mgr.trust.patterns.clear()
    res = await mgr.run()
    nodes = [n for n in res.tree if n.qc.verdict is not QCVerdict.FAIL]
    assert nodes and all(n.qc.verdict is QCVerdict.SUSPECT for n in nodes)


async def test_external_steering_and_post_termination_measurement(reg):
    pol = ExternalPolicy(timeout_s=8.0, on_timeout="stop")
    mgr = CampaignManager(spec("t-C", max_cycles=2), pol, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async def caller():
        for _ in range(2):
            await asyncio.sleep(0.3)
            obs = await plane.observe(cid)
            assert obs.campaign_id == cid, "caller sees the policy's own observation"
            await plane.steer(cid, {"kind": "compose_and_run", "stages": CHAIN,
                                    "replicas": 2})
        await asyncio.sleep(0.3)
        await plane.steer(cid, {"kind": "stop", "reason": "caller done"})

    t = asyncio.create_task(caller())
    res = await mgr.run()
    await t
    assert len(res.tree) > 0

    nid = next(iter(mgr.tree.nodes))
    out = await plane.ingest_measurement(cid, nid, Property(
        name="ddg", value=-5.0,
        source=PropertySource(name="robolab", kind=SourceKind.MEASURED,
                              authority=AUTHORITY_ASSAY)))
    assert out["accepted"]
    n = mgr.tree.get(nid)
    assert n.properties["ddg"].is_measured and n.properties["ddg"].value == -5.0


async def test_provenance_is_written_and_replayable(reg):
    mgr = CampaignManager(spec("t-prov"), ThresholdPolicy(), reg)
    res = await mgr.run()
    graphs = list(mgr.prov.read("graphs"))
    results = list(mgr.prov.read("results"))
    trans = list(mgr.prov.read("transitions"))
    assert graphs and results and trans
    assert any(t.get("event") == "terminated" for t in trans)
    assert all("signature" in g and "estimate" in g for g in graphs)


async def test_budget_is_charged_and_bounds_the_campaign(reg):
    s = spec("t-budget", max_cycles=10)
    s.budget = {"gpu_hours": 0.35, "cpu_hours": 3.0}
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    res = await mgr.run()
    assert mgr.budget.spent, "cost must be charged"
    assert all(mgr.budget.remaining(d) >= -1e-9 for d in mgr.budget.limits)
