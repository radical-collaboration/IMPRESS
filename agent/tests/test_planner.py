"""The Specifier and Planner halves, and the two things the Stage path was silently dropping.

The planner's behaviour against the *real* specs is tested in `test_real_toolkits.py`,
because backlog H3 was precisely that a reasoner's parameters never reached a real tool and a
planner exercised only on mocks is how that went unnoticed. What is here is the mechanics
that need a graph, an executor or a campaign to be visible at all:

* **Deferral** in place of a Task, which is what lets a Stage cover every ready objective
  without inventing work.
* **`replan` shrinking breadth and never the chain.** Truncating the tail is what took
  `boltz_predict` - the only producer of two of four objectives - off job 22675512.
* **Model A's four nodes**, its model seam, and the two ways it differs from D.
* **Model C's two role inboxes**, and that a caller may not declare an objective satisfied.
* **The replay halves**, which reproduce a recorded campaign's decisions but not its findings.
* **The campaign's `params` and `replicas` cap reaching a Stage.** `_apply_campaign_defaults`
  ran on the intent path only, so `submit_stage` dropped both. That is not cosmetic: `params`
  is where a campaign puts target identity, so a roles-driven Delta campaign would have run
  `boltz_predict` with an empty `ligand_smiles` - which does not fail, it models no ligand and
  the front then optimises the wrong objective (backlog A2, by a new route). `mock-stabilize`
  declares no `params` at all, which is why no existing test saw it.
"""
from __future__ import annotations

import json

import pytest

from impress_a.compose.validate import SiteCaps
from impress_a.core.data import DataRegistry
from impress_a.core.decision import CampaignObservation, ValidationFailure
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.spec import Spec
from impress_a.manager import CampaignManager
from impress_a.policy import registry as reasoners
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners import (
    AgenticPlanner,
    ExternalPlanner,
    ReplayPlanner,
    ThresholdPlanner,
)
from impress_a.policy.registry import RolePair
from impress_a.policy.specifier import SpecEvidence
from impress_a.policy.specifiers import (
    AgenticSpecifier,
    ExternalSpecifier,
    ReplaySpecifier,
    ThresholdSpecifier,
)
from impress_a.policy.specifiers.agentic import HYPOTHESIS_SCHEMA
from impress_a.policy.specifiers.replay import ReplayDiverged
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
                        stages=CHAIN,
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


# ---------------------------------------------------------------------------
# Model A's two halves: four nodes, and a model seam that is actually read.
# ---------------------------------------------------------------------------

class _Reasoner:
    """A `NodeReasoner` double. Answers from a script, or raises."""

    model_id = "test-double"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str, dict]] = []

    async def think(self, node, prompt, schema):
        self.calls.append((node, prompt, schema))
        reply = self.replies.pop(0) if self.replies else None
        if isinstance(reply, Exception):
            raise reply
        if reply is None:
            raise RuntimeError("the double ran out of scripted replies")
        return reply


def _sink():
    records: list[tuple[str, dict]] = []
    return records, lambda kind, payload: records.append((kind, payload))


async def test_model_a_registers_four_nodes():
    """Backlog H1: `_build()` registered two while the docstring described four.

    Four is a claim about the pair, so it is asserted across the pair - and against the
    compiled graphs rather than the declared tuples, because a name in a list nobody compiled
    is exactly the kind of claim this test exists to stop.
    """
    sp, pl = AgenticSpecifier(), AgenticPlanner()
    assert sp.NODES + pl.NODES == ("hypothesize", "analyze", "select_tasks", "parameterize")
    for half in (sp, pl):
        compiled = set(half.graph.get_graph().nodes) - {"__start__", "__end__"}
        assert compiled == set(half.NODES), f"{half.name}: {compiled} != {half.NODES}"


async def test_each_node_reads_the_reasoner_and_checks_its_reply(reg):
    """The seam H1 records as dead, exercised - including the correction.

    `self.reasoner` was stored and never read, so there was no schema, no retry and no
    corrective feedback, while the specification asks for all three. A reply naming a strategy
    that does not exist must be rejected and the model told why, which is the precedent Part B
    doc 02 criticised: an exact string match meant a model answering correctly in other words
    was treated as having failed, and no feedback was ever sent back.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    reasoner = _Reasoner(
        {"strategy": "sideways", "hypothesis": "not a strategy"},   # rejected
        {"strategy": "explore", "hypothesis": "front is empty"})    # accepted on retry
    records, sink = _sink()
    sp = AgenticSpecifier(reasoner=reasoner, sink=sink)
    spec = await sp.initial_spec(goal)
    ev = SpecEvidence(_ctx(reg, goal, spec).observation, DataRegistry())

    rev = await sp.revise(spec, ev)

    assert [c[0] for c in reasoner.calls] == ["hypothesize", "hypothesize"], \
        "one call, then one retry - bounded, not until it works"
    assert "rejected" in reasoner.calls[1][1], \
        "the second prompt must carry what was wrong with the first"
    assert reasoner.calls[0][2] is HYPOTHESIS_SCHEMA, "the schema is passed, not only inlined"
    assert rev.is_empty, "explore adds no objective: inventing work from no evidence"
    assert not [r for r in records if r[0] == "transitions"], \
        "a reply accepted on retry is not a degraded decision"


async def test_a_refusing_reasoner_degrades_loudly_and_still_decides(reg):
    """The failure that matters: the exception swallowed and the campaign continuing.

    That is the precedent's behaviour, and it makes a degraded arm indistinguishable from a
    working one - which the four-arm experiment voids an arm for. So exhausting the attempts
    falls back to the rule cascade AND writes a `reasoner_degraded` transition, named the same
    way model B's `oracle_degraded` is, so one query finds every degraded decision in a
    campaign whatever model made it.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    reasoner = _Reasoner(RuntimeError("503 from the endpoint"),
                         RuntimeError("503 from the endpoint"))
    records, sink = _sink()
    sp = AgenticSpecifier(reasoner=reasoner, sink=sink)
    spec = await sp.initial_spec(goal)
    ev = SpecEvidence(_ctx(reg, goal, spec).observation, DataRegistry())

    rev = await sp.revise(spec, ev)

    assert len(reasoner.calls) == 2, "two attempts, then give up"
    events = [r[1] for r in records if r[0] == "transitions"]
    assert [e["event"] for e in events] == ["reasoner_degraded"]
    assert events[0]["node"] == "hypothesize" and "503" in events[0]["error"]
    assert rev.is_empty, "and it still answers - the rule cascade's answer"
    assert sp.notes, "the analysis is recorded whether a model or a rule produced it"


async def test_the_planner_half_asks_the_reasoner_how_wide_to_draw(reg):
    """Node 2a is a decision with its own input and output, so it has its own call.

    And the answer is bounded by the planner's own ceiling: a model asking for sixty lineages
    is answered with `max_lineages`, not with sixty, because a reasoner is under no obligation
    to honour anyone's budget and the campaign's `replicas` cap binds later in the executor.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    reasoner = _Reasoner({"strategy": "explore", "lineages": 60, "rationale": "wide"})
    pl = AgenticPlanner(stages=CHAIN, reasoner=reasoner, max_lineages=4)

    stage = await pl.plan(spec, _ctx(reg, goal, spec))

    assert [c[0] for c in reasoner.calls] == ["select_tasks"]
    assert stage.lineages == 4, f"capped at max_lineages, got {stage.lineages}"


async def test_model_a_moves_a_diversity_knob_where_d_moves_none(reg):
    """One of the two named differences between A and D, asserted rather than described.

    A sets every tunable knob from its strategy; D leaves parameters alone while exploring and
    touches only quality knobs when refining. `temperature` trades "diversity vs recovery" -
    a different draw at the same cost - so it is the cheapest thing a planner can vary and the
    clearest place the two models part company.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    a = await AgenticPlanner(stages=CHAIN).plan(spec, _ctx(reg, goal, spec))
    d = await ThresholdPlanner(stages=CHAIN).plan(spec, _ctx(reg, goal, spec))

    a_design = next(t.params for t in a.runs if t.tool == "mock_design")
    assert a_design["temperature"] == 0.35, (
        "FourNodePolicy's own exploring value, as a fraction of the declared 0-1 range")
    assert all(t.params == {} for t in d.runs), \
        "D asks for nothing while exploring; the declared defaults are the right first draw"


async def test_model_a_retires_an_objective_the_toolkit_cannot_measure(reg):
    """The other named difference between A and D.

    D leaves such an objective OPEN and names it, so its Spec can never complete while one
    exists - which is the honest answer when the campaign was asked for something this
    Toolkit cannot deliver. A retires it, so its Spec can complete on the rest. Both are
    defensible and they are not the same campaign, so the difference is asserted rather than
    left to be discovered in a yield figure. On the real six-stage chain every declared
    objective is producible, so this branch does not fire in the four-arm experiment.
    """
    objs = [*OBJS, Objective(name="nonexistent_metric", direction=Direction.MAX, min=1.0)]
    goal = Goal(text="stabilize", objectives=objs)

    a = AgenticSpecifier()
    spec_a = await a.initial_spec(goal)
    ev_a = SpecEvidence(_ctx(reg, goal, spec_a).observation, DataRegistry())
    rev_a = await a.revise(spec_a, ev_a)
    retired = [spec_a.objectives[o].targets for o in rev_a.deleted]
    assert retired == [["nonexistent_metric"]], f"A retired {retired}"

    d = ThresholdSpecifier()
    spec_d = await d.initial_spec(goal)
    ev_d = SpecEvidence(_ctx(reg, goal, spec_d).observation, DataRegistry())
    assert (await d.revise(spec_d, ev_d)).deleted == [], \
        "D deletes nothing: it names the objective and leaves it open"
    assert [spec_d.objectives[o].targets for o in d.unproducible(spec_d, ev_d)] == \
        [["nonexistent_metric"]], "...and it does name it"


# ---------------------------------------------------------------------------
# Model C: two inboxes behind one `steer`, and the fallback that must not be silent.
# ---------------------------------------------------------------------------

async def test_steer_routes_by_role(reg):
    """One `steer` operation, two halves, routed by a key inside the directive.

    Decision 0002 ruled that model C *is* the headless mode rather than a mode any model can
    run in, so the role split must not make it two modes; and ADR 0007 forbids an adapter
    carrying an operation the core protocol lacks, so `steer_specifier` would have had to be
    added to the protocol and every adapter to express what one field expresses. A directive
    with no `role` goes to the planner, which is what every existing caller sends.
    """
    pair = reasoners.build_roles("C")
    pair.steer({"role": "specifier", "kind": "revise"})
    pair.steer({"role": "planner", "stages": CHAIN})
    pair.steer({"stages": CHAIN})

    assert pair.specifier.inbox.qsize() == 1
    assert pair.planner.inbox.qsize() == 2, "an unaddressed directive goes to the planner"

    with pytest.raises(ValueError, match="unknown role"):
        pair.steer({"role": "reviewer"})
    with pytest.raises(ValueError, match="takes no external directives"):
        reasoners.build_roles("D").steer({"role": "planner"})


async def test_a_caller_may_not_declare_an_objective_satisfied(reg):
    """The one thing external control does not get.

    Satisfaction is a finding computed from realized data, and a caller able to assert it
    could end a campaign by saying the work was done - the same line decision 0013 draws for a
    task agent, which may author a protocol and may not score one. Refused with its reason,
    not ignored: a caller whose directive was dropped has been told it was accepted.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    sp = ExternalSpecifier(timeout_s=0.05)
    spec = await sp.initial_spec(goal)
    ev = SpecEvidence(_ctx(reg, goal, spec).observation, DataRegistry())
    oid = next(iter(spec.objectives))

    sp.steer({"role": "specifier", "kind": "satisfied"})
    assert (await sp.revise(spec, ev)).is_empty
    assert "may not declare an objective satisfied" in sp.refusals[0]

    sp.steer({"role": "specifier", "objectives": [{"targets": ["iptm"], "min": 0.9}]})
    rev = await sp.revise(spec, ev)
    assert [o.targets for o in rev.new_objectives] == [["iptm"]], "adding is allowed"

    sp.steer({"role": "specifier", "delete": ["no-such-objective"]})
    assert (await sp.revise(spec, ev)).is_empty
    assert "no such objective" in sp.refusals[-1]

    sp.steer({"role": "specifier", "delete": [oid]})
    assert (await sp.revise(spec, ev)).deleted == [oid], "deleting a real one is allowed"


async def test_model_c_stops_rather_than_falling_back_unless_asked(reg):
    """A fallen-back C arm is byte-for-byte a D campaign, and invisible in the campaign log.

    So `stop` is the default here, a fallback must be declared to exist at all, and taking
    one writes a `caller_timeout` transition naming it. The four-arm design calls this one of
    its two dangerous failure modes; this is the structural half of excluding it.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    records, sink = _sink()

    silent = ExternalPlanner(stages=CHAIN, timeout_s=0.05, sink=sink)
    assert silent.on_timeout == "stop", "the default must be the safe one"
    assert await silent.plan(spec, _ctx(reg, goal, spec)) is None
    timeouts = [r[1] for r in records if r[1].get("event") == "caller_timeout"]
    assert timeouts and timeouts[0]["policy"] == "stop"
    assert timeouts[0]["fallback"] is None

    with pytest.raises(ValueError, match="needs a declared fallback"):
        ExternalPlanner(stages=CHAIN, on_timeout="fallback")

    records.clear()
    falling = ExternalPlanner(stages=CHAIN, timeout_s=0.05, on_timeout="fallback",
                              fallback=ThresholdPlanner(stages=CHAIN), sink=sink)
    stage = await falling.plan(spec, _ctx(reg, goal, spec))
    assert stage is not None, "a declared fallback does plan"
    named = [r[1] for r in records if r[1].get("event") == "caller_timeout"]
    assert named[0]["fallback"] == "threshold-plan", \
        "which planner answered must be in the record, not inferable from the yield"


async def test_an_external_directive_gets_no_privilege_but_a_fair_turn(reg):
    """The caller chooses the work; the gates still judge it, and a rejection comes back.

    `on_rejected` was the only place `ExternalPolicy` gave the caller a second turn, and the
    role split must keep that: a directive refused at a gate is information the caller needs,
    and a planner that answered a rejection itself would be deciding on the caller's behalf.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    records, sink = _sink()
    pl = ExternalPlanner(stages=CHAIN, timeout_s=0.05, sink=sink)

    pl.steer({"stages": ["mock_generate", "mock_design", "mock_fold"], "replicas": 2,
              "params": {"mock_fold": {"recycles": 11}}})
    stage = await pl.plan(spec, _ctx(reg, goal, spec))
    assert [t.tool for t in stage.runs if t.lineage == 0] == [
        "mock_generate", "mock_design", "mock_fold"], "the caller's chain"
    assert stage.lineages == 2
    assert next(t.params for t in stage.runs if t.tool == "mock_fold") == {"recycles": 11}

    pl.steer({"stages": CHAIN, "replicas": 1})
    nxt = await pl.replan(stage, ValidationFailure(gate="budget", reason="no room"),
                          spec, _ctx(reg, goal, spec))
    assert nxt.lineages == 1 and nxt.attempt == stage.attempt + 1
    assert [r[1]["gate"] for r in records if r[1].get("event") == "directive_rejected"] \
        == ["budget"], "the caller is told why, on the record"

    pl.steer({"stages": CHAIN, "replicaz": 4})
    assert await pl.plan(spec, _ctx(reg, goal, spec)) is None, \
        "an unknown key is refused, not ignored: a typo silently dropped reads as accepted"


# ---------------------------------------------------------------------------
# The replay halves: a recorded campaign's decisions, re-executed.
# ---------------------------------------------------------------------------

async def _recorded(reg, tmp_path, **kw):
    """Run one campaign for real, then hand back its `specs`/`stages` records."""
    spec = _campaign("t-record", tmp_path, max_cycles=4, **kw)
    res = await _run(spec, reg)
    prov = tmp_path / "runs" / spec.campaign_id / "provenance"
    read = lambda name: [json.loads(line) for line                      # noqa: E731
                         in (prov / name).read_text().splitlines() if line.strip()]
    return res, read("specs.jsonl"), read("stages.jsonl")


async def test_replay_reproduces_a_recorded_campaign_including_its_parameters(reg, tmp_path):
    """The whole point, and the reason `mappings` had to be recorded.

    A Stage is a durable artifact now, so the replay re-deploys the recorded task mappings
    verbatim - tools, lineages, wiring, seeds and **parameters**. Before `mappings` was in
    `stages` provenance, a replay re-ran the same chain with different numbers and called it
    the same experiment: `graphs` records `{node: tool}` and nothing else, so the parameter
    vector a Planner chose was recorded nowhere at all.

    Asserted on the metrics, which is the only end-to-end evidence: the mock tools seed their
    draws on their parameters and their inputs, so identical metrics mean identical
    parameters, identical seeds and identical wiring.
    """
    original, specs, stages = await _recorded(reg, tmp_path)
    assert original.cycles >= 2, "a one-cycle recording would prove little"

    replayed = _campaign("t-replayed", tmp_path, max_cycles=4)
    pair = RolePair(ReplaySpecifier(specs), ReplayPlanner(stages))
    result = await CampaignManager(replayed, pair, reg).run()

    def shape(res):
        return sorted(sorted((k, round(p.value, 6)) for k, p in n.properties.items())
                      for n in res.tree.nodes.values())

    assert shape(result) == shape(original), \
        "every node's metrics must match: the mock tools seed on params, inputs and node id"
    assert result.cycles == original.cycles
    assert result.stop_reason == original.stop_reason


async def test_replay_does_not_replay_a_finding(reg, tmp_path):
    """A recorded `status_changes` is evidence from another campaign's draws.

    Satisfaction is computed from realized data - `BaseSpecifier.satisfied` does it, and this
    half inherits that - so replaying a recorded one would let a replay whose draws came out
    worse end claiming work it never did. What is replayed is what the Specifier *authored*.
    """
    _, specs, _ = await _recorded(reg, tmp_path)
    recorded_changes = [r for r in specs if r.get("status_changes")]
    assert recorded_changes, "precondition: the recording contains a satisfaction finding"

    sp = ReplaySpecifier(specs)
    spec = await sp.initial_spec(Goal(text="x", objectives=list(OBJS)))
    ev = SpecEvidence(_ctx(reg, Goal(text="x", objectives=list(OBJS)), spec).observation,
                      DataRegistry())
    for _ in range(len(specs)):
        assert (await sp.revise(spec, ev)).status_changes == {}, \
            "no revision this half emits may carry a status change"


async def test_replay_refuses_a_record_whose_parameters_were_never_written(reg, tmp_path):
    """An old recording cannot be replayed faithfully, and must say so.

    A `stages` record from before `mappings` existed names the tools and nothing else. Running
    it would produce a campaign that looks like a replay, and is a fresh plan of the same
    chain - which is worse than refusing, because the figure it produces is comparable to
    nothing.
    """
    _, _, stages = await _recorded(reg, tmp_path)
    old = [{k: v for k, v in r.items() if k != "mappings"} for r in stages]
    goal = Goal(text="x", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)

    with pytest.raises(ReplayDiverged, match="carries no `mappings`"):
        await ReplayPlanner(old).plan(spec, _ctx(reg, goal, spec))


async def test_replay_gives_up_rather_than_improvising(reg, tmp_path):
    """A recorded Stage refused where the original was admitted is the finding.

    It means the replaying campaign differs - budget, trust, site caps, the gates - and that
    is the most informative thing a replay can report. Improvising a smaller Stage would
    report a replay of something that was never recorded.
    """
    _, _, stages = await _recorded(reg, tmp_path)
    goal = Goal(text="x", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    pl = ReplayPlanner(stages)
    stage = await pl.plan(spec, _ctx(reg, goal, spec))

    assert await pl.replan(stage, ValidationFailure(gate="budget", reason="no room"),
                           spec, _ctx(reg, goal, spec)) is None


async def test_both_replay_halves_refuse_to_be_built_without_records(reg):
    """`--model replay` with no `--replay-from` is an operator error, reported as one.

    `build_policy` used to call `cls()`, so this died on a positional argument named
    `records` that no flag set. A replay with no records is a different campaign, not a
    degraded one.
    """
    for half in (ReplaySpecifier, ReplayPlanner):
        with pytest.raises(ValueError, match="replay-from"):
            half(None)
    with pytest.raises(ValueError, match="no `initial` event"):
        await ReplaySpecifier([{"event": "revision", "generation": 2}]).initial_spec(
            Goal(text="x"))
