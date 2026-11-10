"""What a reasoner leaves on disk, and the one parameter it may not touch.

Two changes, one subject: making a control model's own behaviour *measurable*, which is the
precondition for putting reasoners on the mock lab's axis and for scoring an arm on Delta.

**The sink had writers and no subscriber.** `policy/reasoning.ask` has recorded a transcript
since it was written, `reasoning.degraded` has recorded a fallback, and the external halves
have recorded their directives - all through `ReasonerOptions.sink`, which
`cli.build_roles` never passed. So a live campaign left no prompt, no reply, no model id, no
timing and no degraded event, and `analysis/compare_arms` - which reads `degraded_events` to
void an arm and `elapsed_s` for the decision-layer share - could never fire either check. The
gap survived because every test asserted at the HALF (`OracleSpecifier(sink=...)` built by
hand) and none at the seam where the sink is actually assembled. These assert at the seam.

**And a live planner could turn the experiment's independent variable down.**
`OraclePlanner` shows a model every tunable parameter with its range and its `trades`
sentence, which for `mock_rfd3_design.difficulty` reads "how hard this campaign is", 0.0 to
1.0 - and `_apply_campaign_defaults` lets a policy win on any key it set. `operator_only` is
the third state between varyable and frozen: the campaign's to set, a reasoner's to leave
alone. It is enforced in exactly one place, `tools/view.card_for`, so what is tested here is
that the one place is enough - that gate 3 still admits the campaign's own value, and that
every reader of the card refuses a reasoner's.
"""
from __future__ import annotations

import json

import pytest

from impress_a.cli import ReasonerSink, build_roles
from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import CampaignObservation, ExperimentIntent
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.spec import Spec
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy import reasoning
from impress_a.policy import registry as reasoners
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners._knobs import tunable
from impress_a.policy.planners.oracle import OraclePlanner
from impress_a.tools.registry import Registry
from impress_a.tools.spec import ParameterSpec, ToolSpec
from impress_a.tools.view import card_for, view_of

# Only some of these are coroutines; the rest are pure projections of a ToolSpec.
pytestmark = pytest.mark.asyncio

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
SMB = ["mock_rfd3_design", "mock_mpnn_design", "mock_packmin", "mock_fastrelax",
       "mock_filter_shape", "mock_boltz_predict"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _obs(reg, stages):
    return CampaignObservation(
        campaign_id="c", cycle=1, goal="bind", objectives=list(OBJS),
        toolkit=view_of(reg, stages), stages=list(stages))


#: An empty Spec is enough for `_prompt`: it reads the open objectives and the toolkit, and
#: what is under test is which PARAMETERS the tool cards carry into it.
_EMPTY_SPEC = Spec()


def _spec(cid, tmp_path, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        max_cycles=kw.pop("max_cycles", 2),
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root=str(tmp_path), stages=list(CHAIN), **kw)


# -- operator_only ------------------------------------------------------------------------

def _tool(**param_kw) -> ToolSpec:
    return ToolSpec(id="t", toolkit="mock", pattern="P2",
                    parameters={"steps": ParameterSpec(type="int", default=10, min=1,
                                                       max=100, trades="quality vs time"),
                                "dial": ParameterSpec(type="float", default=0.25, min=0.0,
                                                      max=1.0, **param_kw)},
                    qc_gates=[{"id": "output_present", "params": {"key": "result"}}])


def test_an_operator_only_parameter_reaches_the_card_as_frozen_with_its_reason():
    card = card_for(_tool(trades="how hard this is", operator_only="the condition itself"))
    assert "dial" not in card.parameters, "a reasoner must not see it as proposable"
    assert card.frozen["dial"] == "the condition itself", "and it is told why, not just no"
    assert "steps" in card.parameters, "the refinement knobs are untouched"


def test_a_plain_parameter_is_unaffected():
    """The default is off, so no existing spec moves."""
    card = card_for(_tool(trades="how hard this is"))
    assert "dial" in card.parameters and "dial" not in card.frozen


def test_no_planner_may_propose_an_operator_only_parameter():
    """`tunable` is the one test every planner's knob logic runs, and it reads `frozen`."""
    card = card_for(_tool(trades="quality vs time", operator_only="the condition itself"))
    assert tunable(card.parameters["steps"], card.frozen, "steps") is True
    # Deliberately a `quality` trades sentence: without `operator_only` this parameter
    # would be exactly the kind model A reaches for first.
    spec = _tool(trades="quality vs time", operator_only="x")
    assert "dial" not in card_for(spec).parameters


def test_model_bs_prompt_omits_it_and_its_schema_check_refuses_a_reply_naming_it(reg):
    """The refusal existed already - what is new is that `difficulty` now reaches it.

    Both halves of the defence matter. The prompt not naming it is what stops a cooperative
    model reaching for it; the check is what stops one that reaches anyway. It is a schema
    failure rather than a gate rejection on purpose: `reasoning.ask` appends the reason to
    the prompt and asks again, so a model is told while it can still fix it, rather than
    discovering it a cycle later as a refused graph.
    """
    obs = _obs(reg, SMB)
    planner = OraclePlanner(oracle=None, stages=list(SMB))
    ctx = PlanningContext(Goal(text="bind", objectives=list(OBJS)), obs)

    prompt = planner._prompt(_EMPTY_SPEC, ctx, list(SMB))
    assert "difficulty" not in prompt, "a model shown the dial will reach for it"
    assert "diffusion_steps" in prompt, "and must still be shown the knobs it may move"

    check = planner._validator(list(SMB), ctx)
    check({"stages": list(SMB), "replicas": 1,
           "params": {"mock_rfd3_design": {"diffusion_steps": 120}}})
    with pytest.raises(ValueError, match="frozen"):
        check({"stages": list(SMB), "replicas": 1,
               "params": {"mock_rfd3_design": {"difficulty": 0.0}}})


def test_the_surrogates_dial_is_operator_only_and_the_campaign_still_sets_it(reg, tmp_path):
    """The whole point of the design, in one test.

    The lab declares `difficulty` in its campaign `params:` and must keep working; a
    reasoner must not be able to name it. Those two go through different code paths - gate 3
    reads `ToolSpec.frozen_parameters`, every reasoner reads `TaskCard.frozen` - and this
    asserts the split holds rather than trusting that it does.
    """
    card = view_of(reg, SMB).tools["mock_rfd3_design"]
    assert "difficulty" in card.frozen, "a reasoner may not propose the experiment's dial"
    assert "difficulty" not in card.parameters

    spec = reg.get("mock_rfd3_design")
    assert "difficulty" in spec.parameters, "but it is still a declared parameter"
    assert "difficulty" not in spec.frozen_parameters, "not frozen - gate 3 must admit it"

    intent = ExperimentIntent(goal="bind", stages=list(SMB), replicas=1,
                              params={"mock_rfd3_design": {"difficulty": 0.55}})
    graph = Composer(reg).compose(intent, "r0001")
    caps = SiteCaps(gpu_api="cuda", gpus_per_node=1)
    budget = BudgetLedger(limits={"gpu_hours": 10.0, "cpu_hours": 50.0})
    failure = Validator(reg, caps, budget, tool_delivery="mock").validate(graph)
    assert failure is None, f"the campaign's own value must still compose: {failure}"


# -- what a decision record now carries ----------------------------------------------------

class _Answering:
    """A reasoner that satisfies every schema it is shown, by reading the schema.

    Keyed off the node rather than a scripted list, because model A's two live nodes are
    asked a varying number of times depending on how the campaign goes and a script that
    runs out turns a wiring test into a flakiness test.
    """

    model_id = "fake-1"

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def think(self, node, prompt, schema):
        self.prompt_tokens += 10
        self.completion_tokens += 3
        return {"strategy": "explore", "hypothesis": "nothing is limiting it yet",
                "lineages": 1, "rationale": "a reason"}


class _Counting:
    """A reasoner that answers, and keeps the token counters a live client keeps."""

    model_id = "fake-1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def think(self, node, prompt, schema):
        self.prompt_tokens += 10
        self.completion_tokens += 3
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


async def test_a_decision_record_carries_its_time_and_its_tokens():
    records = []
    r = _Counting([{"a": 1}])
    out = await reasoning.ask(r, "n", "p", {"a": "int"}, required=("a",),
                              sink=lambda k, v: records.append((k, v)), cycle=3)
    assert out == {"a": 1}
    (kind, rec), = records
    assert kind == "decisions"
    assert rec["node"] == "n" and rec["cycle"] == 3 and rec["ok"] is True
    assert rec["model_id"] == "fake-1"
    assert rec["elapsed_s"] >= 0.0, "the key compare_arms has always read and never found"
    # Deltas, not totals: two calls on one client must not each report the running sum.
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 3


async def test_a_rejected_attempt_is_recorded_too():
    """It used to reach a `log.warning` and nothing else, so a decision that cost two round
    trips and one that cost one were the same single row. The corrective-retry path has
    never been seen against a live endpoint; a path that leaves no record cannot be
    checked."""
    records = []
    r = _Counting([{"wrong": 1}, {"a": 2}])
    out = await reasoning.ask(r, "n", "p", {"a": "int"}, required=("a",),
                              sink=lambda k, v: records.append((k, v)))
    assert out == {"a": 2}
    assert [rec["ok"] for _, rec in records] == [False, True]
    assert [rec["attempt"] for _, rec in records] == [0, 1]
    assert "missing" in records[0][1]["error"]
    assert sum(rec["completion_tokens"] for _, rec in records) == 6, "both calls counted"


async def test_a_reasoner_with_no_counters_omits_them_rather_than_reporting_zero():
    """The adapters' own rule: a number nobody measured is absent, never 0. A rehearsal makes
    no network call, and a zero token count would read as a free live call."""
    class Bare:
        model_id = "rehearsal"

        async def think(self, node, prompt, schema):
            return {"a": 1}

    records = []
    await reasoning.ask(Bare(), "n", "p", {"a": "int"}, required=("a",),
                        sink=lambda k, v: records.append((k, v)))
    (_, rec), = records
    assert "prompt_tokens" not in rec and "completion_tokens" not in rec


async def test_a_sink_that_raises_does_not_take_the_campaign_with_it():
    """The sink is the embedder's. Losing a transcript row is a bad day; losing the cycle
    that produced it is a worse one."""
    def broken(kind, record):
        raise RuntimeError("disk full")

    assert await reasoning.ask(_Counting([{"a": 1}]), "n", "p", {"a": "int"},
                               required=("a",), sink=broken) == {"a": 1}


# -- the seam: sink -> manager -> provenance ----------------------------------------------

def test_build_roles_hands_back_a_sink_to_bind():
    """The assertion whose absence let the gap live: at the seam, not at the half."""
    pair = build_roles("B", CampaignSpec(campaign_id="x", goal="g", objectives=OBJS,
                                         stages=list(CHAIN)))
    assert isinstance(pair.reasoner_sink, ReasonerSink)


def test_an_unbound_sink_counts_rather_than_raises():
    sink = ReasonerSink()
    sink("decisions", {"node": "n"})
    assert sink.dropped == 1 and sink.written == 0


async def test_a_campaign_writes_its_reasoners_decisions_to_provenance(reg, tmp_path):
    """End to end on the real executor: a half calls `ask`, `ask` calls the sink, the sink
    calls the manager, and the executor appends to `provenance/decisions.jsonl`.

    Model A with an injected reasoner, because A's `hypothesize` and `select_tasks` are the
    two nodes that call a model - and because with no profile named A runs its rule cascades
    and would write nothing at all, which is the state every campaign has been in.
    """
    sink = ReasonerSink()
    # Answers BOTH of model A's schemas - `hypothesize` wants a hypothesis, `select_tasks`
    # wants a lineage count - so the path under test is the one where a model answered,
    # not the degraded one.
    opts = reasoners.ReasonerOptions(stages=list(CHAIN), sink=sink, max_cycles=1,
                                     reasoner=_Answering())
    pair = reasoners.build_roles("A", "A", opts)
    mgr = CampaignManager(_spec("t-sink", tmp_path, max_cycles=1), pair, reg)
    sink.bind(mgr)
    await mgr.run()

    path = tmp_path / "t-sink" / "provenance" / "decisions.jsonl"
    assert path.exists(), "nothing recorded what the reasoner was asked or answered"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # Two shapes share this file: `reasoning.ask`'s transcript, keyed by `node`, and each
    # agentic half's own summary of what it concluded, keyed by `policy`. Only the first
    # says a model was called, which is what is under test here.
    asked = [r for r in rows if "node" in r]
    assert asked, "nothing recorded what the reasoner was asked or answered"
    assert {r["node"] for r in asked} <= {"hypothesize", "select_tasks"}
    for r in asked:
        assert r["model_id"] == "fake-1", "which model answered must be on the record"
        assert "elapsed_s" in r and "prompt" in r and "ts" in r
    # More written than rows here, and that is right: `reasoner_degraded` goes to
    # `transitions`, so the sink's count spans both files.
    assert sink.written >= len(rows) and sink.dropped == 0


async def test_a_reasoner_may_not_write_the_campaigns_findings(reg, tmp_path):
    """`record_reasoning` takes two kinds. A reasoner that could append to `results` would be
    writing the campaign's own findings, which is exactly what `compare_arms` refuses to
    score from."""
    mgr = CampaignManager(_spec("t-kinds", tmp_path), reasoners.build_roles("D"), reg)
    mgr.record_reasoning("decisions", {"node": "n"})
    mgr.record_reasoning("transitions", {"event": "reasoner_degraded"})
    with pytest.raises(ValueError, match="executor"):
        mgr.record_reasoning("results", {"node": "n", "metrics": {"iptm": 0.99}})


async def test_a_degraded_turn_now_reaches_transitions(reg, tmp_path):
    """The pre-registration voids an arm shown to have degraded, and `compare_arms` counts
    `reasoner_degraded` out of `transitions.jsonl`. Nothing has ever written one there, so
    the rule could not fire on the laptop or on Delta."""
    sink = ReasonerSink()
    opts = reasoners.ReasonerOptions(
        stages=list(CHAIN), sink=sink, max_cycles=1,
        reasoner=_Counting([RuntimeError("503 from the endpoint")] * 40))
    pair = reasoners.build_roles("A", "A", opts)
    mgr = CampaignManager(_spec("t-degraded", tmp_path, max_cycles=1), pair, reg)
    sink.bind(mgr)
    await mgr.run()

    trans = (tmp_path / "t-degraded" / "provenance" / "transitions.jsonl").read_text()
    events = [json.loads(line) for line in trans.splitlines() if line.strip()]
    degraded = [e for e in events if e.get("event") == "reasoner_degraded"]
    assert degraded, ("an arm that fell back to its rule cascade was indistinguishable "
                      "from one that never needed to")
    assert degraded[0]["fallback"] and degraded[0]["error"]


async def test_with_no_reasoner_nothing_claims_a_model_answered(reg, tmp_path):
    """The guard on the change rather than on the feature.

    With no profile named, model A runs its rule cascades - and those still record what they
    concluded, which they always did. What must NOT appear is a row carrying a `model_id`,
    because that is the record a reader would take as evidence that a frontier model drove
    the arm. On the sibling example's job 23219379 that ambiguity let 144 degraded turns read
    as a frontier-model result for a full day.
    """
    sink = ReasonerSink()
    pair = reasoners.build_roles("A", "A", reasoners.ReasonerOptions(
        stages=list(CHAIN), sink=sink, max_cycles=1))
    mgr = CampaignManager(_spec("t-nocall", tmp_path, max_cycles=1), pair, reg)
    sink.bind(mgr)
    res = await mgr.run()
    assert res.stop_reason
    path = tmp_path / "t-nocall" / "provenance" / "decisions.jsonl"
    rows = ([json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if path.exists() else [])
    assert not [r for r in rows if "model_id" in r], "no model was called; none may be named"
