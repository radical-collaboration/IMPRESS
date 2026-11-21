"""A campaign that cannot reach its goal with the tools it can see, and one that is merely quiet.

Two measurements, one rule: **the planner's output is checked against what the campaign
declared, and a shortfall is reported rather than inferred to be intentional.** They are
different reports, and finding out which was which is what this module is shaped around.

* **Refused at startup.** No tools at all, or a declared stage no toolkit provides. Downstream,
  with `Registry.search_paths()` returning `[]`, a campaign ran to `exit=goals_satisfied`,
  published a model and promoted it on a corpus of `score: 0.0, best: {}` rows -- the only
  signal anywhere was `planned nothing at cycle 0` at INFO and every workflow exited `rc=0`. A
  mistyped stage id was no better: three cycles, then `CampaignAborted`, naming neither the
  stage nor the tool.

* **Reported, and deliberately NOT refused.** A stage the campaign declares that *this* plan
  does not reach. The refusal was written first and withdrawn after it broke five tests in
  `test_planner.py`, one of them named `test_the_chain_is_the_subset_the_objectives_need`:
  selection is by output type, not by position in a declared list, and planning a stage no
  objective needs "would be work nobody asked for". The stage list is a **vocabulary**, not a
  manifest. So only the silence was wrong, and the last two tests here are what keeps the fix
  from growing back into the refusal.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from impress_a.compose.validate import SiteCaps
from impress_a.core.pareto import Direction, Objective
from impress_a.manager import CampaignManager, ToolVocabularyRefused
from impress_a.policy.planners import ThresholdPlanner
from impress_a.policy.registry import RolePair
from impress_a.policy.specifiers import ThresholdSpecifier
from impress_a.runtime.executor import CampaignSpec
from impress_a.tools.registry import Registry

pytestmark = pytest.mark.asyncio

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
#: `sc_rmsd` and `iptm` are produced upstream of `mock_score`, which is the only producer of
#: `ddg`/`clashscore` -- so these two objectives reach three of the four declared stages. That
#: gap is the subject of the last two tests, not a mistake here.
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _campaign(cid, tmp_path, **kw):
    kw.setdefault("stages", CHAIN)
    kw.setdefault("objectives", OBJS)
    return CampaignSpec(campaign_id=cid, goal="stabilize",
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root=str(tmp_path / "runs"),
                        trust_root=str(tmp_path / "trust"), **kw)


def _pair(spec):
    return RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=list(spec.stages)))


def _prov(spec, name) -> list[dict]:
    path = Path(spec.root) / spec.campaign_id / "provenance" / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# refused, before an engine exists
# ---------------------------------------------------------------------------


async def test_a_campaign_with_no_tools_at_all_is_refused_at_startup(tmp_path):
    """Item 30. The failure was not that it crashed -- it is that it SUCCEEDED."""
    spec = _campaign("t-empty", tmp_path, max_cycles=1)

    with pytest.raises(ToolVocabularyRefused) as caught:
        await CampaignManager(spec, _pair(spec), Registry()).run()

    why = str(caught.value)
    assert "t-empty" in why
    assert "no tools" in why
    assert "report success having done nothing" in why, (
        "the message should say what the old behaviour was, because that is why it is fatal"
    )


async def test_the_refusal_says_where_it_looked_and_which_roots_were_absent(tmp_path,
                                                                           monkeypatch):
    """"Nothing resolved" and "nothing was there" are different mistakes.

    The default root is relative to `tools/registry.py`, so it exists in a source checkout and
    is absent from a wheel install -- which is how a deployment gets an empty registry with no
    hint at all. A refusal that printed only the surviving roots could not say that.

    Driven through the mistyped-stage refusal rather than the empty one, and the first draft of
    this test got that wrong: pointing `$IMPRESS_A_TOOLKITS` at a directory that does not
    exist does **not** empty the registry, because the default root is still found. Both
    refusals build the same "where" clause, and only one of them is reachable from a source
    checkout -- which is itself the thing the clause exists to tell a reader.
    """
    ghost = tmp_path / "not-a-toolkit-root"
    monkeypatch.setenv("IMPRESS_A_TOOLKITS", str(ghost))
    reg = Registry()
    reg.load(None)
    spec = _campaign("t-where", tmp_path, max_cycles=1,
                     stages=["mock_generate", "a_tool_that_does_not_exist"])

    assert any(str(ghost) == str(p) for p in reg.attempted), reg.attempted
    assert not any(str(ghost) == str(p) for p in reg.searched), reg.searched
    assert reg.specs, "the default root is still searched, which is this test's whole premise"

    with pytest.raises(ToolVocabularyRefused) as caught:
        await CampaignManager(spec, _pair(spec), reg).run()

    why = str(caught.value)
    assert str(ghost) in why
    assert "does not exist" in why
    assert "IMPRESS_A_TOOLKITS" in why


async def test_a_root_searched_twice_is_named_as_such(tmp_path, monkeypatch, reg):
    """The duplicate-root hazard, which otherwise leaves no trace but a confusing message.

    An explicit root that is also in `$IMPRESS_A_TOOLKITS` is searched twice, and the second
    pass raises `duplicate tool id` for every spec in it -- which disables that toolkit
    all-or-nothing, with one line in `errors` and no refusal. It is easy to do from a test
    harness or a launcher script, and the message is the only place it can be noticed.
    """
    root = Registry.search_paths(None)[-1]
    monkeypatch.setenv("IMPRESS_A_TOOLKITS", str(root))
    doubled = Registry().load(root)
    spec = _campaign("t-dupe", tmp_path, max_cycles=1,
                     stages=[*CHAIN, "a_tool_that_does_not_exist"])

    with pytest.raises(ToolVocabularyRefused) as caught:
        await CampaignManager(spec, _pair(spec), doubled).run()

    why = str(caught.value)
    assert "searched more than once" in why, why
    assert "duplicate tool id" in why


async def test_a_declared_stage_no_toolkit_provides_is_refused_by_name(tmp_path, reg):
    """One mistyped character, and it used to cost three cycles to not find out.

    `CampaignAborted: 3 consecutive all-failed runs` named neither the stage nor the tool; on
    an allocation each of those cycles is queue time.
    """
    spec = _campaign("t-typo", tmp_path, max_cycles=1,
                     stages=["mock_generate", "mock_desgin", "mock_fold"])

    with pytest.raises(ToolVocabularyRefused) as caught:
        await CampaignManager(spec, _pair(spec), reg).run()

    why = str(caught.value)
    assert "mock_desgin" in why
    assert "1 stage(s)" in why
    assert "mock_generate" not in why.split("provides:")[1].split(".")[0], (
        "only the unprovided stages belong in the list"
    )


async def test_nothing_is_published_or_recorded_by_a_refused_campaign(tmp_path):
    """The refusal is not `goals_satisfied`, and it happens before an engine is built.

    That ordering is the economics of it: discovering this at cycle 0 costs a Dragon runtime
    and a worker pool, and discovering it at cycle 3 costs an allocation.
    """
    spec = _campaign("t-nothing", tmp_path, max_cycles=1)

    with pytest.raises(ToolVocabularyRefused):
        await CampaignManager(spec, _pair(spec), Registry()).run()

    assert _prov(spec, "campaign") == [], (
        "a campaign record was written for a campaign that never started"
    )
    assert _prov(spec, "graphs") == []
    assert _prov(spec, "results") == []


# ---------------------------------------------------------------------------
# reported, and NOT refused
# ---------------------------------------------------------------------------


async def test_a_declared_stage_this_plan_does_not_reach_is_recorded_not_refused(tmp_path,
                                                                                reg):
    """Item 42, and the shape the measurement forced.

    `mock_score` is the only producer of `ddg`/`clashscore`, and neither objective is declared,
    so the plan is three of the four declared stages. That is this package's own documented
    behaviour -- selection by output type, not by position in a declared list -- so the
    campaign must still run. What was wrong is that it ran and said nothing: a nine-stage
    campaign downstream submitted two tasks, reported `2/2 tasks ok`, `qc=pass` and `every
    spec objective satisfied`, and mentioned the other seven nowhere.

    Asserted on `stages.jsonl` rather than on a log record, because provenance is what is
    still there after the allocation ends.
    """
    spec = _campaign("t-quiet", tmp_path, max_cycles=1)
    result = await CampaignManager(spec, _pair(spec), reg).run()

    assert result.cycles >= 1, result.stop_reason
    assert "vocabulary" not in result.stop_reason, (
        "the sub-chain was refused; selection by output type is intended behaviour"
    )

    events = [e for e in _prov(spec, "stages") if e.get("event") == "stages_not_planned"]
    assert events, "the shortfall was not recorded anywhere"
    detail = events[0]["detail"]
    assert detail["not_planned"] == ["mock_score"], detail
    assert detail["declared"] == CHAIN
    assert "mock_score" not in detail["planned"]


async def test_a_plan_that_reaches_every_declared_stage_records_nothing(tmp_path, reg):
    """Otherwise the record is noise, and a noisy record is one nobody reads.

    Declaring `ddg` pulls `mock_score` in, which is the same assertion
    `test_the_chain_is_the_subset_the_objectives_need` makes from the planner's side -- here
    through a whole campaign, so it covers the executor's comparison as well as the planner's
    selection.
    """
    spec = _campaign("t-full", tmp_path, max_cycles=1,
                     objectives=[*OBJS, Objective(name="ddg", direction=Direction.MIN)])
    result = await CampaignManager(spec, _pair(spec), reg).run()

    assert result.cycles >= 1, result.stop_reason
    assert [e for e in _prov(spec, "stages") if e.get("event") == "stages_not_planned"] == []


async def test_a_campaign_that_declares_no_stages_is_not_held_to_a_list(tmp_path, reg):
    """`stages:` is optional, and an absent declaration cannot be contradicted.

    Without this the check would fire on every campaign that lets its policy choose the chain,
    which is every campaign written before `stages` existed.
    """
    spec = _campaign("t-nostages", tmp_path, max_cycles=1, stages=[])
    pair = RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=list(CHAIN)))
    result = await CampaignManager(spec, pair, reg).run()

    assert result.cycles >= 1, result.stop_reason
    assert [e for e in _prov(spec, "stages") if e.get("event") == "stages_not_planned"] == []
