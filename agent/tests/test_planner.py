"""Model D's Planner half, and the two things the Stage path was silently dropping.

The planner's behaviour against the *real* specs is tested in `test_real_toolkits.py`,
because backlog H3 was precisely that a reasoner's parameters never reached a real tool and a
planner exercised only on mocks is how that went unnoticed. What is here is the mechanics
that need a graph, an executor or a campaign to be visible at all:

* **Deferral** in place of a Task, which is what lets a Stage cover every ready objective
  without inventing work.
* **`replan` shrinking breadth and never the chain.** Truncating the tail is what took
  `boltz_predict` - the only producer of two of four objectives - off job 22675512.
* **The campaign's `params` and `replicas` cap reaching a Stage.** `_apply_campaign_defaults`
  ran on the intent path only, so `submit_stage` dropped both. That is not cosmetic: `params`
  is where a campaign puts target identity, so a roles-driven Delta campaign would have run
  `boltz_predict` with an empty `ligand_smiles` - which does not fail, it models no ligand and
  the front then optimises the wrong objective (backlog A2, by a new route). `mock-stabilize`
  declares no `params` at all, which is why no existing test saw it.
"""
from __future__ import annotations

import pytest

from impress_a.compose.validate import SiteCaps
from impress_a.core.decision import CampaignObservation, ValidationFailure
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.spec import Spec
from impress_a.manager import CampaignManager
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners import ThresholdPlanner
from impress_a.policy.registry import RolePair
from impress_a.policy.specifiers import ThresholdSpecifier
from impress_a.runtime.executor import CampaignExecutor, CampaignSpec
from impress_a.tools.registry import Registry
from impress_a.tools.view import view_of

pytestmark = pytest.mark.asyncio

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _ctx(reg, goal, spec, stages=CHAIN, **kw):
    obs = CampaignObservation(campaign_id="c", cycle=1, goal=goal.text,
                              objectives=list(goal.objectives), toolkit=view_of(reg, stages),
                              stages=list(stages), spec=spec, **kw)
    return PlanningContext(goal, obs)


async def _plan(reg, objectives=None, stages=CHAIN, **kw):
    goal = Goal(text="stabilize", objectives=list(objectives or OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    planner = ThresholdPlanner(stages=stages, **kw)
    return planner, spec, await planner.plan(spec, _ctx(reg, goal, spec, stages))


async def test_an_objective_no_enabled_task_reports_is_deferred_not_dropped(reg):
    """A Deferral is an answer; a silent omission is the thing the coverage gate refuses.

    The Planner cannot know whether a metric will ever be producible - the Specifier's
    `unproducible`/`failed` is where that judgement lives - so what it owes the Reviewer is
    the fact that it could not plan this one, and what it is waiting on.
    """
    objs = [*OBJS, Objective(name="nonexistent_metric", direction=Direction.MAX, min=1.0)]
    _, spec, stage = await _plan(reg, objs)

    assert [d.objective for d in stage.deferrals] == [
        next(o.id for o in spec.ready() if o.targets == ["nonexistent_metric"])]
    assert "nonexistent_metric" in stage.deferrals[0].reason
    assert stage.covered == {o.id for o in spec.ready()}, \
        "every ready objective answered, by a Task or by a Deferral"


async def test_the_chain_is_the_subset_the_objectives_need(reg):
    """Selection by output type, not by position in a declared list.

    `mock_score` is the only producer of `ddg`/`clashscore`; with neither declared, nothing
    in the chain needs it and planning it would be work nobody asked for.
    """
    _, _, stage = await _plan(reg)
    assert [t.tool for t in stage.runs if t.lineage == 0] == [
        "mock_generate", "mock_design", "mock_fold"], (
        "mock_score produces no declared objective's metric and nothing depends on it")

    objs = [*OBJS, Objective(name="ddg", direction=Direction.MIN)]
    _, _, wider = await _plan(reg, objs)
    assert [t.tool for t in wider.runs if t.lineage == 0] == CHAIN


async def test_replan_shrinks_breadth_and_never_the_chain(reg):
    """Job 22675512's defect, refused by construction.

    A budget rejection says "not right now", not "measure less". Dropping a lineage removes a
    complete independent chain, so it cannot change what the Stage can measure; dropping the
    tail removed the only producer of two of four objectives and the run was unwinnable from
    that moment, recording `rejected: null`.
    """
    planner, spec, stage = await _plan(reg, base_replicas=3)
    goal = Goal(text="stabilize", objectives=list(OBJS))
    ctx = _ctx(reg, goal, spec)
    tools = {t.tool for t in stage.runs}

    assert stage.lineages == 3
    first = await planner.replan(
        stage, ValidationFailure(gate="budget", transient=True, reason="no room"), spec, ctx)
    assert first.lineages == 2
    assert {t.tool for t in first.runs} == tools, "the chain must be untouched"
    assert first.attempt == stage.attempt + 1

    second = await planner.replan(
        first, ValidationFailure(gate="interlock", reason="untrusted cap"), spec, ctx)
    assert second.lineages == 1
    assert await planner.replan(
        second, ValidationFailure(gate="budget", reason="still no room"), spec, ctx) is None, \
        "at one lineage there is nothing left to shrink"


async def test_replan_gives_up_on_a_structural_rejection(reg):
    """`coverage` and `type` are properties of the graph, not of the moment.

    A rule-driven planner that reshaped a graph a gate called wrong would be guessing, and
    `BasePlanner` records why "shrink and retry" is the wrong reflex: both shipped policies
    answered a budget rejection by truncating their stage list, which is a cost heuristic
    that knows nothing about what the graph can then measure.
    """
    planner, spec, stage = await _plan(reg, base_replicas=3)
    goal = Goal(text="stabilize", objectives=list(OBJS))
    for gate in ("coverage", "type", "parameter", "resource"):
        assert await planner.replan(stage, ValidationFailure(gate=gate, reason="wrong"),
                                    spec, _ctx(reg, goal, spec)) is None, gate


async def test_a_planner_with_no_enabled_tool_plans_nothing(reg):
    """A chain naming tools the campaign did not enable is not a chain.

    The alternative - falling back to every tool in the `ToolkitView` - would hand a campaign
    the whole registry, `mock_noodle` included: a tool that completes successfully, reports a
    confident `designability` and produces no secondary structure.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    planner = ThresholdPlanner(stages=["no_such_tool"])
    assert await planner.plan(spec, _ctx(reg, goal, spec, ["no_such_tool"])) is None


async def test_an_empty_spec_is_not_planned(reg):
    """Nothing ready is not a reason to plan something."""
    planner = ThresholdPlanner(stages=CHAIN)
    goal = Goal(text="stabilize", objectives=list(OBJS))
    assert await planner.plan(Spec(), _ctx(reg, goal, Spec())) is None


# ---------------------------------------------------------------------------
# What the Stage path was dropping.
# ---------------------------------------------------------------------------

def _campaign(cid, tmp_path, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        control="roles", stages=CHAIN,
                        root=str(tmp_path / "runs"),
                        trust_root=str(tmp_path / "trust"), **kw)


async def _run(spec, reg):
    pair = RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=list(spec.stages)))
    return await CampaignManager(spec, pair, reg).run()


async def test_the_campaigns_params_reach_a_stages_tasks(reg, tmp_path):
    """`params` is target identity, and the Stage path never applied it.

    On the intent path `_apply_campaign_defaults` merges it; `submit_stage` had no equivalent,
    so a roles-driven real campaign would run `boltz_predict` with an empty `ligand_smiles` -
    which models no ligand rather than failing. Merged in the executor rather than in the
    Planner for the recorded reason: the ligand and the contig are campaign configuration, not
    search strategy, and a reasoner that had to learn a tool's parameter names to run a
    campaign correctly is one more place for a real campaign to execute what it did not
    declare.

    Asserted directly on the merge rather than through a campaign, because the mock tools
    only *seed* their draw on their parameters - a campaign would prove the value changed the
    result without proving which value arrived.
    """
    spec = _campaign("t-params", tmp_path, max_cycles=1,
                     params={"mock_fold": {"recycles": 7}, "mock_generate": {"num_designs": 9}})
    ex = CampaignExecutor(spec, None, reg)
    planner, sspec, stage = await _plan(reg, base_replicas=2)
    for task in stage.runs:                       # the Planner asked for nothing here
        assert task.params == {}
    stage.tasks[0].params = {"num_designs": 2}    # ...except on one task, deliberately

    ex._apply_campaign_params(stage)

    by_tool = {}
    for task in stage.runs:
        by_tool.setdefault(task.tool, []).append(task.params)
    assert all(p == {"recycles": 7} for p in by_tool["mock_fold"]), by_tool["mock_fold"]
    assert by_tool["mock_generate"][0] == {"num_designs": 2}, \
        "the Planner wins on a key it set - this supplies defaults, it does not override"
    assert by_tool["mock_generate"][1] == {"num_designs": 9}, \
        "and every other lineage still gets the campaign's value"


async def test_the_replica_cap_binds_a_stage_too(reg, tmp_path):
    """`replicas` is the campaign's cap on breadth, and a Stage asking wider is trimmed.

    How wide a campaign may go is the campaign's call; how wide to go within that is the
    Planner's. Trimming drops whole lineages, never the tail of a chain - a lineage is a
    complete chain, so removing one cannot change what the Stage can measure - and it is
    recorded in `stages` provenance, because a Stage that ran narrower than planned should
    say so.
    """
    spec = _campaign("t-cap", tmp_path, max_cycles=1, replicas=1)
    res = await _run(spec, reg)
    assert res.cycles >= 1, res.stop_reason
    # One lineage admitted means one DesignNode per run, not the planner's two.
    assert len(res.tree.nodes) == 1, \
        f"replicas: 1 must cap the planner's {ThresholdPlanner().base_replicas} lineages"
