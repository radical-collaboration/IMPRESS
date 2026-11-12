"""Model B: the two schemas, the live client, and the profiles that name a model.

Backlog H2 was that `--model B` ran the deterministic stand-in and nothing constructed a
client, so the one model whose whole premise is "ask a frontier model" had never asked one.
What is asserted here is the part that can be asserted with no key and no network - which is
most of it, because the dangerous failures are not in the HTTP:

* **The rehearsal returned the mock chain whatever the campaign declared**, and `_build_b` did
  not forward `o.stages`. Against the six-stage Delta chain that is a campaign which validates
  the real toolkits and then executes mocks, reported as a model-B result with plausible
  metrics and `6/6 tasks ok` - the single most dangerous failure the four-arm design names.
* **Its stopping conditions were hardcoded** at `cycle >= 4` and `front >= 3`, so a four-hour
  arm would have stopped itself in twenty minutes. Same defect as X1, different route.
* **A reply was brace-sliced out of the text**, so a prose answer containing two braces
  produced a decision from whatever was between them.
* **A model's reply can name a tool, a metric or a node that does not exist**, and each one is
  a rejection a cycle later rather than at the point the model could have been told.

The live client is exercised against a fake `AsyncOpenAI` rather than a real endpoint: what is
worth testing is the retry policy, the `Retry-After` honouring, the reasoning carried back and
the refusals named, and none of those need a network.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from impress_a.core.artifacts import Property, PropertySource
from impress_a.core.data import DataRegistry
from impress_a.core.decision import CampaignObservation, ValidationFailure
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.tree import DesignNode
from impress_a.policy import registry as reasoners
from impress_a.policy.llm import (
    LLMError,
    ModelProfile,
    OpenAICompatOracle,
    build_oracle,
    load_profiles,
)
from impress_a.policy.oracle import RehearsalOracle
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners.oracle import STAGE_SCHEMA, OraclePlanner
from impress_a.policy.specifier import SpecEvidence
from impress_a.policy.specifiers import ThresholdSpecifier
from impress_a.policy.specifiers.oracle import SPEC_SCHEMA, OracleSpecifier
from impress_a.tools.registry import Registry
from impress_a.tools.view import view_of

pytestmark = pytest.mark.asyncio

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
REAL_CHAIN = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
              "boltz_predict"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]
REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _node(**metrics):
    node = DesignNode()
    for name, value in metrics.items():
        node.properties[name] = Property(name=name, value=value,
                                         source=PropertySource(name="t"))
    return node


def _obs(reg, stages=CHAIN, front=(), objectives=None):
    return CampaignObservation(
        campaign_id="c", cycle=1, goal="stabilize",
        objectives=list(objectives or OBJS), toolkit=view_of(reg, stages),
        stages=list(stages), pareto_front=list(front))


def tmp_profiles(doc: str) -> pathlib.Path:
    """A models.yaml holding `doc` (JSON is valid YAML), in a fresh temporary directory."""
    import tempfile
    path = pathlib.Path(tempfile.mkdtemp()) / "models.yaml"
    path.write_text(doc)
    return path


def _no_openai() -> bool:
    import importlib.util
    return importlib.util.find_spec("openai") is None


def _sink():
    records: list[tuple[str, dict]] = []
    return records, lambda kind, payload: records.append((kind, payload))


# ---------------------------------------------------------------------------
# The two schemas, and what each half refuses.
# ---------------------------------------------------------------------------

async def test_the_two_schemas_do_not_overlap():
    """One call answered both questions, so no transcript could say which half was good.

    `DECISION_SCHEMA` asked for a kind, a stage list, a replica count, a params dict, a node
    to branch from and a reason - in one object. The Spec half now answers in metrics and
    thresholds and the Stage half in tools, breadth and parameters, and the four-arm design's
    whole claim is that those two seams are separately attributable.
    """
    assert set(SPEC_SCHEMA) & set(STAGE_SCHEMA) == {"rationale"}, \
        "only the rationale is asked of both; anything else means one half decides twice"
    assert not {"stages", "replicas", "params"} & set(SPEC_SCHEMA), \
        "the Specifier must not name a tool, a width or a parameter"
    assert not {"metric", "min", "max"} & set(STAGE_SCHEMA), \
        "the Planner must not move a threshold it is judged against"


async def test_the_rehearsal_derives_its_chain_from_the_campaign(reg):
    """Backlog H2's dangerous half, and it is dangerous because it is silent.

    A rehearsal with the mock chain written into it produces `6/6 tasks ok` with plausible
    metrics on a GPU allocation that loaded the real toolkits. There is no default now, and a
    rehearsal with no chain refuses by name rather than inventing one.
    """
    oracle = RehearsalOracle(stages=REAL_CHAIN)
    pl = OraclePlanner(stages=REAL_CHAIN, oracle=oracle)
    goal = Goal(text="bind", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    obs = _obs(reg, REAL_CHAIN)

    raw = await oracle.think("stage", pl._prompt(spec, PlanningContext(goal, obs), REAL_CHAIN),
                             STAGE_SCHEMA)
    assert raw["stages"] == REAL_CHAIN, \
        "the rehearsal answered with a chain the campaign did not declare"

    with pytest.raises(ValueError, match="no chain was supplied"):
        await RehearsalOracle().think("stage", "REFINING: []", STAGE_SCHEMA)


async def test_the_rehearsal_carries_no_stopping_condition_at_all(reg):
    """`cycle >= 4` and `front >= 3` were literals inside the stand-in, which is X1 again.

    A four-hour arm would have stopped itself after four decisions, in about fifteen minutes,
    and reported a clean campaign. They are **gone** rather than made configurable, because
    stopping is not a model's call: the Listener asks when the Spec completes and the executor
    decides, since budget, stagnation and repeated failure are facts about state a reasoner
    cannot see. A stand-in with a stopping condition of its own is a stand-in that can end a
    campaign the campaign did not ask to end.
    """
    oracle = RehearsalOracle(stages=CHAIN)
    assert not hasattr(oracle, "max_cycles")
    assert not hasattr(oracle, "target_front")
    assert not hasattr(oracle, "propose"), \
        "the `DecisionModel` surface went with `OraclePolicy`; keeping an unused method is " \
        "how a reader comes to believe there are two ways in"

    # Behaviourally, not by scanning the source - which is what the first version did, and it
    # matched the docstring explaining the defect it was checking for. The fourth test in this
    # repository to catch its own documentation.
    front = "FRONT_IDS: []\nMETRICS: [\"iptm\"]\nREFINING: []"
    for node, schema in (("spec", SPEC_SCHEMA), ("stage", STAGE_SCHEMA)):
        answer = await oracle.think(node, front, schema)
        assert "stop" not in str(answer).lower(), (
            f"the rehearsal asked to {answer} at node {node}: stopping is the Listener's "
            f"request and the executor's call, never a model's")


async def test_the_specifier_refuses_a_metric_the_campaign_never_declared(reg):
    """An objective on an unreported metric makes every later Stage refusable.

    The Reviewer's coverage gate demands a Task or a Deferral for every ready objective, and
    the executor refuses a graph that cannot produce a declared objective's metric (A8). So a
    model inventing a metric does not produce a creative campaign; it produces a campaign that
    refuses everything, several cycles after the reply that caused it.
    """
    goal = Goal(text="stabilize", objectives=list(OBJS))
    sp = OracleSpecifier(oracle=RehearsalOracle(stages=CHAIN))
    spec = await sp.initial_spec(goal)
    node = _node(iptm=0.8, sc_rmsd=1.0)
    ev = SpecEvidence(_obs(reg, front=[node]), DataRegistry())

    with pytest.raises(ValueError, match="not one this campaign declares"):
        sp._to_revision({"action": "refine", "metric": "invented_metric",
                         "parent_node": node.id}, spec, ev)
    with pytest.raises(ValueError, match="not on the current front"):
        sp._to_revision({"action": "refine", "metric": "iptm",
                         "parent_node": "n-does-not-exist"}, spec, ev)

    rev = sp._to_revision({"action": "refine", "metric": "iptm", "parent_node": node.id},
                          spec, ev)
    assert rev.new_objectives[0].parent_node == node.id
    assert rev.new_objectives[0].satisfied_when.min == 0.55, \
        "the campaign's own bound, not the model's: an arm may choose what to push on, not " \
        "the number it is judged against"


async def test_the_planner_refuses_a_tool_or_a_parameter_that_does_not_exist(reg):
    """Checked inside the bounded retry, where the model can still be told.

    A tool the campaign never enabled is the mock-chain-on-a-GPU failure in its most direct
    form; a parameter outside its declared range is a gate-3 rejection one round trip later;
    a frozen parameter is a rejection the spec already explains. All three are things the
    model is told rather than things it discovers.
    """
    goal = Goal(text="bind", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    pl = OraclePlanner(stages=REAL_CHAIN, oracle=RehearsalOracle(stages=REAL_CHAIN))
    check = pl._validator(REAL_CHAIN, PlanningContext(goal, _obs(reg, REAL_CHAIN)))

    check({"stages": REAL_CHAIN, "replicas": 2,
           "params": {"rfd3_design": {"diffusion_steps": 120}}})

    for reply, pattern in (
        ({"stages": ["mock_generate"], "replicas": 1}, "not in this campaign's chain"),
        ({"stages": REAL_CHAIN, "replicas": 99}, "at most"),
        ({"stages": REAL_CHAIN, "replicas": 0}, "at least 1"),
        ({"stages": REAL_CHAIN, "replicas": 1,
          "params": {"rfd3_design": {"nonexistent": 1}}}, "declares no parameter"),
        ({"stages": REAL_CHAIN, "replicas": 1,
          "params": {"rfd3_design": {"diffusion_steps": 9999}}}, "is above"),
        # `packmin` IS in the chain, and is not in the two stages this reply asks for.
        ({"stages": REAL_CHAIN[:2], "replicas": 1,
          "params": {"packmin": {"cycles": 2}}}, "not in this stage"),
        ({"stages": REAL_CHAIN, "replicas": 1, "parent_node": "n0001"},
         "not the Planner's to choose"),
    ):
        with pytest.raises(ValueError, match=pattern):
            check(reply)
    del spec


async def test_a_refusing_oracle_degrades_to_the_declared_fallback(reg):
    """An API outage must degrade explicitly, never stall a multi-GPU allocation (risk R7).

    And it must be visible: a degraded arm reported as a live one is what the experiment voids
    an arm for, and the event name matches model A's and the legacy policy's so that one query
    over `transitions` finds every degraded decision in a campaign.
    """
    class Refusing:
        model_id = "refusing"

        async def think(self, node, prompt, schema):
            raise LLMError("503 from the endpoint")

    goal = Goal(text="stabilize", objectives=list(OBJS))
    records, sink = _sink()
    sp = OracleSpecifier(oracle=Refusing(), sink=sink)
    spec = await sp.initial_spec(goal)
    ev = SpecEvidence(_obs(reg), DataRegistry())
    assert (await sp.revise(spec, ev)).is_empty
    assert sp.degraded is True

    pl = OraclePlanner(stages=CHAIN, oracle=Refusing(), sink=sink)
    stage = await pl.plan(spec, PlanningContext(goal, _obs(reg)))
    assert stage is not None, "the fallback plans; the campaign does not stall"
    assert pl.degraded is True

    events = [r[1] for r in records if r[1].get("event") == "reasoner_degraded"]
    assert [e["node"] for e in events] == ["spec", "stage"]
    assert all("503" in e["error"] for e in events)
    assert [e["fallback"] for e in events] == ["threshold-spec", "threshold-plan"]


# ---------------------------------------------------------------------------
# The live client, against a fake endpoint.
# ---------------------------------------------------------------------------

class _Resp:
    """The shape `openai` returns, as much of it as `_message_from_response` reads."""

    class _Msg:
        def __init__(self, content, reasoning=None):
            self.content = content
            self.reasoning_content = reasoning
            self.model_extra = {}

    class _Choice:
        def __init__(self, content, finish, reasoning):
            self.message = _Resp._Msg(content, reasoning)
            self.finish_reason = finish

    class _Usage:
        prompt_tokens = 11
        completion_tokens = 7

    def __init__(self, content="{}", finish="stop", reasoning=None):
        self.choices = [self._Choice(content, finish, reasoning)]
        self.usage = self._Usage()


class _Endpoint:
    """A fake `AsyncOpenAI`. Replays a script, recording every request it was sent."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        reply = self.replies.pop(0) if self.replies else _Resp()
        if isinstance(reply, Exception):
            raise reply
        return reply


def _oracle(endpoint, **kw):
    profile = ModelProfile(name="fake", base_url="http://x", model="fake-1-0", **kw)
    oracle = OpenAICompatOracle.__new__(OpenAICompatOracle)
    oracle.profile = profile
    oracle.model_id = profile.model
    oracle.prompt_tokens = oracle.completion_tokens = 0
    oracle._history = []
    oracle._client = endpoint
    return oracle


async def test_the_reply_is_parsed_not_brace_sliced():
    """`LangChainOracle` took `text[find("{"):rfind("}")+1]` despite claiming structured output.

    So a prose answer containing two braces produced a decision from whatever was between
    them, and a malformed object produced one from a prefix of itself. A reply that is not a
    JSON object is a schema failure, and `reasoning.ask` is what tells the model so.
    """
    oracle = _oracle(_Endpoint(_Resp('{"action": "hold", "rationale": "ok"}')))
    assert await oracle.think("spec", "p", SPEC_SCHEMA) == {"action": "hold",
                                                            "rationale": "ok"}
    assert oracle.prompt_tokens == 11 and oracle.completion_tokens == 7

    fenced = _oracle(_Endpoint(_Resp('```json\n{"action": "hold"}\n```')))
    assert await fenced.think("spec", "p", SPEC_SCHEMA) == {"action": "hold"}

    prose = _oracle(_Endpoint(_Resp("I would {probably} refine {this one}")))
    with pytest.raises(ValueError, match="did not return JSON"):
        await prose.think("spec", "p", SPEC_SCHEMA)

    listed = _oracle(_Endpoint(_Resp('["hold"]')))
    with pytest.raises(ValueError, match="not a JSON object"):
        await listed.think("spec", "p", SPEC_SCHEMA)


async def test_a_declining_model_is_named_rather_than_reported_as_bad_json():
    """Measured on `claude-opus-5-5` through this endpoint: filtered, 0 completion tokens.

    With the system prompt and without it, so it is the workload and not the prompt's wording,
    and the remedy is a different model rather than a reworded prompt. Reported as "no JSON
    object" it would look like a prompt bug and be reworded for a week.
    """
    oracle = _oracle(_Endpoint(_Resp("", finish="content_filter")))
    with pytest.raises(LLMError, match="declined the request"):
        await oracle.think("spec", "p", SPEC_SCHEMA)

    truncated = _oracle(_Endpoint(_Resp('{"action": "ho', finish="length")))
    with pytest.raises(LLMError, match="hit max_tokens"):
        await truncated.think("spec", "p", SPEC_SCHEMA)


async def test_a_reasoning_models_own_reasoning_is_carried_back():
    """Beam refuses a follow-up whose earlier assistant messages lack `reasoning_content`.

    `400 missing_required_parameter`. Turn one succeeds and turn two does not, so a
    single-turn probe of the endpoint passes while every corrective retry fails - which is how
    144 degraded turns were once reported as a healthy run. The corrective retry is the only
    multi-turn path here, so this is exactly where it bites.
    """
    endpoint = _Endpoint(_Resp('{"action": "nonsense"}', reasoning="thinking hard"),
                         _Resp('{"action": "hold", "rationale": "ok"}'))
    oracle = _oracle(endpoint)
    await oracle.think("spec", "first", SPEC_SCHEMA)
    await oracle.think("spec", "second", SPEC_SCHEMA)

    second = endpoint.requests[1]["messages"]
    assistant = [m for m in second if m["role"] == "assistant"]
    assert assistant and assistant[0]["reasoning_content"] == "thinking hard"
    oracle.reset()
    assert oracle._history == [], "a new decision starts a new exchange, not a longer one"


async def test_sampling_and_the_model_id_are_pinned_on_every_request():
    """A comparison cannot hold temperature constant if no request states it.

    An endpoint's default is free to change between runs, which would show up as a model
    behaving differently in week two. And the id recorded has to be the dated one: a profile
    named `claude-sonnet` says nothing about what answered.
    """
    endpoint = _Endpoint(_Resp('{"action": "hold", "rationale": "ok"}'))
    oracle = _oracle(endpoint, max_tokens=1234, temperature=0.0)
    await oracle.think("spec", "p", SPEC_SCHEMA)

    sent = endpoint.requests[0]
    assert sent["model"] == "fake-1-0" and oracle.model_id == "fake-1-0"
    assert sent["temperature"] == 0.0 and sent["max_tokens"] == 1234
    assert sent["response_format"] == {"type": "json_object"}
    assert json.dumps(SPEC_SCHEMA, indent=2) in sent["messages"][-1]["content"], \
        "the schema is in the prompt too, for an endpoint that enforces nothing"


async def test_a_retryable_fault_is_retried_and_a_bad_request_is_not():
    """Four exponential retries into a 400 is a decision's worth of wall clock for nothing.

    And `Retry-After` is honoured because ignoring it is how a rate-limited client stays rate
    limited: the retries all land inside the window the endpoint named.
    """
    class Fault(Exception):
        def __init__(self, status, headers=None):
            super().__init__(f"HTTP {status}")
            self.status_code = status
            self.response = type("R", (), {"status_code": status,
                                           "headers": headers or {}})()

    ok = _Resp('{"action": "hold", "rationale": "ok"}')
    endpoint = _Endpoint(Fault(503), ok)
    oracle = _oracle(endpoint, max_retries=4)
    assert await oracle.think("spec", "p", SPEC_SCHEMA) == {"action": "hold",
                                                            "rationale": "ok"}
    assert len(endpoint.requests) == 2

    refused = _Endpoint(Fault(401), ok)
    with pytest.raises(LLMError, match="401"):
        await _oracle(refused, max_retries=4).think("spec", "p", SPEC_SCHEMA)
    assert len(refused.requests) == 1, "an auth failure fails identically however often sent"

    from impress_a.policy.llm import _backoff
    assert _backoff(Fault(429, {"retry-after": "7"}), 0) == 7.0
    assert _backoff(Fault(429, {"retry-after": "9999"}), 0) == 120.0, "bounded"
    assert _backoff(Fault(503), 3) == 8.0, "exponential when the endpoint said nothing"


async def test_an_endpoint_that_rejects_response_format_is_retried_without_it():
    """"OpenAI-compatible" is not a uniform surface, and a 400 here is not the model's fault.

    Dropping the parameter and retrying once is the difference between a model that cannot be
    used and one whose schema is enforced by the prompt alone.
    """
    class Fault(Exception):
        status_code = 400
        response = type("R", (), {"status_code": 400, "headers": {}})()

    endpoint = _Endpoint(Fault(), _Resp('{"action": "hold", "rationale": "ok"}'))
    oracle = _oracle(endpoint, max_retries=4)
    assert (await oracle.think("spec", "p", SPEC_SCHEMA))["action"] == "hold"
    assert "response_format" in endpoint.requests[0]
    assert "response_format" not in endpoint.requests[1]


# ---------------------------------------------------------------------------
# The profiles.
# ---------------------------------------------------------------------------

async def test_every_profile_declares_what_a_live_run_needs():
    """A profile missing a base_url or a model id fails at the first request, mid-allocation."""
    profiles = load_profiles(REPO / "models.yaml")
    assert "rehearsal" in profiles and profiles["rehearsal"].kind == "rehearsal"
    for name, profile in profiles.items():
        if not profile.is_live:
            continue
        if profile.kind == "rhapsody_vllm":
            # Served by the campaign's own engine: no URL, but a layout for its GPUs.
            assert "num_gpus" in profile.hardware, f"{name} declares no GPU layout"
        else:
            assert profile.base_url, f"{name} declares no base_url"
        assert profile.model, f"{name} declares no model id"
        assert profile.max_tokens >= 1024, f"{name}: {profile.max_tokens} is too small"


async def test_no_profile_names_a_barred_vendor():
    """The machine-wide provenance policy, asserted rather than reviewed.

    `~/.claude/CLAUDE.md` bars models developed by Chinese organisations by any route - weights
    on project storage, a server inside an allocation, or a hosted API arm. The sibling example
    enforces it the same way and for the same reason: a barred vendor must fail a pytest run
    rather than wait on someone noticing it in a diff.
    """
    barred = ("qwen", "deepseek", "glm", "zhipu", "minimax", "kimi", "moonshot",
              "yi-", "01-ai", "baichuan", "internlm", "hunyuan", "ernie", "doubao",
              "step-", "skywork")
    text = (REPO / "models.yaml").read_text().lower()
    for name in barred:
        assert name not in text, (
            f"models.yaml mentions {name!r}, which the machine-wide provenance policy in "
            f"~/.claude/CLAUDE.md bars by any route")


async def test_a_rehearsal_profile_builds_without_a_key_and_a_live_one_refuses_without_one():
    """The default must work offline, and a live profile must say which variable is missing.

    Key before package: a missing key reported as a missing package sends you to pip.
    """
    profiles = load_profiles(REPO / "models.yaml")
    rehearsal = build_oracle(profiles["rehearsal"], stages=CHAIN)
    assert rehearsal.stages == CHAIN

    with pytest.raises(LLMError, match="needs ANTHROPIC_API_KEY_THAT_IS_NOT_SET"):
        build_oracle(ModelProfile(name="x", base_url="http://x", model="m",
                                  api_key_env="ANTHROPIC_API_KEY_THAT_IS_NOT_SET"))
    with pytest.raises(LLMError, match="unknown kind"):
        build_oracle(ModelProfile(name="x", kind="telepathy"))


async def test_the_cli_refuses_an_unknown_profile_by_name():
    """With the known ones listed: a typo should not look like a missing file."""
    from impress_a.cli import _client_for
    from impress_a.runtime.executor import CampaignSpec

    spec = CampaignSpec(campaign_id="c", goal="g", objectives=list(OBJS), stages=CHAIN)
    assert _client_for(None, spec) is None, "no profile means the registry's rehearsal"
    with pytest.raises(ValueError, match="unknown model profile"):
        _client_for("no-such-profile", spec)
    assert build_oracle(load_profiles(REPO / "models.yaml")["rehearsal"],
                        stages=CHAIN).stages == CHAIN


async def test_model_b_builds_both_halves_with_the_campaigns_chain():
    """The whole of H2's silent half, at the point it is wired."""
    pair = reasoners.build_roles("B", options=reasoners.ReasonerOptions(stages=REAL_CHAIN))
    assert pair.planner.stages == REAL_CHAIN
    assert pair.specifier.oracle.stages == REAL_CHAIN
    assert pair.planner.oracle.stages == REAL_CHAIN
    assert isinstance(pair.specifier.fallback, ThresholdSpecifier), \
        "a declared fallback is mandatory: an outage must degrade, not stall an allocation"


async def test_the_planner_half_does_not_truncate_a_chain_on_a_budget_rejection(reg):
    """Job 22675512: the shipped oracle dropped the last stage, which was the only producer
    of `complex_plddt` and `ligand_iptm` - two of four objectives - and recorded
    `rejected: null`. Breadth shrinks instead, through model D's mechanics.
    """
    goal = Goal(text="bind", objectives=list(OBJS))
    spec = await ThresholdSpecifier().initial_spec(goal)
    pl = OraclePlanner(stages=CHAIN, oracle=RehearsalOracle(stages=CHAIN))
    ctx = PlanningContext(goal, _obs(reg))
    stage = await pl.plan(spec, ctx)
    tools = {t.tool for t in stage.runs}

    shrunk = await pl.replan(stage, ValidationFailure(gate="budget", reason="no room"),
                             spec, ctx)
    assert {t.tool for t in shrunk.runs} == tools, "the chain must be untouched"
    assert shrunk.lineages == stage.lineages - 1


@pytest.mark.skipif(_no_openai(), reason="the 'oracle' extra is not installed")
async def test_a_live_client_actually_constructs(monkeypatch):
    """The client has to be built at least once by something.

    `LangChainOracle` was built nowhere, which is how it kept a docstring claiming structured
    output over a brace-slice for as long as it did. This stops short of a request - that
    needs a key and an endpoint, and the request *shape* is covered above against a fake - but
    it does prove the real `AsyncOpenAI` accepts what the profile passes it, which is the part
    a fake cannot prove.
    """
    monkeypatch.setenv("IMPRESS_A_TEST_KEY", "not-a-real-key")
    profile = ModelProfile(name="probe", base_url="http://127.0.0.1:1/v1", model="probe-1-0",
                           api_key_env="IMPRESS_A_TEST_KEY", max_tokens=256)
    oracle = OpenAICompatOracle(profile)
    assert oracle.model_id == "probe-1-0"
    assert str(oracle._client.base_url).rstrip("/") == "http://127.0.0.1:1/v1"
    assert oracle._client.max_retries == 0, \
        "retries are ours, with backoff and a log line; the client's would be silent"


async def test_one_exchange_per_decision_rather_than_one_per_campaign():
    """The history is a corrective exchange, not a transcript.

    Nothing ended it, so every decision appended to the last one: by cycle fifty the prompt
    carried fifty decisions, the bill grew quadratically with the campaign, and - because both
    halves share one client instance - the Spec and Stage exchanges interleaved inside it. The
    tokens bought nothing, since each decision is answered from the observation it was given.
    `reasoning.ask` ends the exchange, because `think` cannot tell a first attempt from a new
    decision and `ask` can.
    """
    from impress_a.policy import reasoning
    from impress_a.policy.llm import MAX_EXCHANGE

    endpoint = _Endpoint(*[_Resp('{"action": "hold", "rationale": "ok"}')] * 6)
    oracle = _oracle(endpoint)
    for _ in range(3):
        await reasoning.ask(oracle, "spec", "p", SPEC_SCHEMA, required=("action",))
    assert [len(r["messages"]) for r in endpoint.requests] == [1, 1, 1], \
        "each decision is one user message, not a growing conversation"

    # Within one decision the retry IS multi-turn, which is the thing being preserved.
    retrying = _Endpoint(_Resp('{"action": "nonsense"}'),
                         _Resp('{"action": "hold", "rationale": "ok"}'))
    oracle = _oracle(retrying)
    await reasoning.ask(oracle, "spec", "p", SPEC_SCHEMA, required=("action",),
                        validate=lambda raw: None if raw["action"] == "hold" else
                        (_ for _ in ()).throw(ValueError("not an action")))
    assert [len(r["messages"]) for r in retrying.requests] == [1, 3], \
        "the second attempt carries the first prompt, the reply and the correction"

    # And a caller that never resets is still bounded.
    unbounded = _Endpoint(*[_Resp('{"action": "hold", "rationale": "ok"}')] * 20)
    oracle = _oracle(unbounded)
    for _ in range(20):
        await oracle.think("spec", "p", SPEC_SCHEMA)
    assert len(oracle._history) <= MAX_EXCHANGE


async def test_a_profile_is_refused_at_load_time_for_what_it_would_do_with_a_key():
    """Two load-time refusals, both about a credential and both enforced where it is read.

    The vendor policy was checked only by a test over this repository's own `models.yaml`,
    and `IMPRESS_A_MODELS` can name another file - a policy enforced only where someone
    remembered to look is not enforced. And a profile naming an `api_key_env` beside a plain
    `http://` endpoint off-host would put the operator's key on the wire in cleartext, which
    is not a configuration choice to leave to whoever edits the file.
    """
    bad_vendor = tmp_profiles('{"profiles": {"x": {"kind": "openai_compat", '
                              '"base_url": "https://api.example.com/v1", '
                              '"model": "Qwen3-Max", "api_key_env": "K"}}}')
    with pytest.raises(LLMError, match="provenance policy"):
        load_profiles(bad_vendor)

    cleartext = tmp_profiles('{"profiles": {"x": {"kind": "openai_compat", '
                             '"base_url": "http://elsewhere.example.com/v1", '
                             '"model": "m", "api_key_env": "K"}}}')
    with pytest.raises(LLMError, match="over \\nplain HTTP|plain HTTP"):
        load_profiles(cleartext)

    # Loopback over http is the in-allocation case and is allowed; so is http with no key.
    for doc in ('{"profiles": {"x": {"kind": "openai_compat", '
                '"base_url": "http://localhost:8000/v1", "model": "m", "api_key_env": "K"}}}',
                '{"profiles": {"x": {"kind": "openai_compat", '
                '"base_url": "http://elsewhere.example.com/v1", "model": "m"}}}'):
        assert "x" in load_profiles(tmp_profiles(doc))


async def test_the_profiles_file_is_the_packaged_one_unless_an_operator_names_another(
        tmp_path, monkeypatch):
    """A `models.yaml` in the working directory used to win, and that is a credential path.

    A profile's `base_url` is where the request goes and its `api_key_env` names the key that
    goes with it, so a file in whatever directory a job started in could point the operator's
    own key at someone else's endpoint. On a shared filesystem with a launcher that cd's into
    a per-job directory, that is not a remote hazard.
    """
    from impress_a.cli import _client_for
    from impress_a.runtime.executor import CampaignSpec

    spec = CampaignSpec(campaign_id="c", goal="g", objectives=list(OBJS), stages=CHAIN)
    planted = tmp_path / "models.yaml"
    planted.write_text('profiles:\n  rehearsal:\n    kind: rehearsal\n  sneaky:\n'
                       '    kind: rehearsal\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="unknown model profile"):
        _client_for("sneaky", spec)

    monkeypatch.setenv("IMPRESS_A_MODELS", str(planted))
    assert _client_for("sneaky", spec) is not None, \
        "an operator naming a file explicitly is a decision; a directory is not"
