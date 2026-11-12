"""`CampaignSession.infer`: a locally hosted reasoner's calls as engine `prompt_task`s.

The model itself needs Dragon and a GPU, so these tests stand a backend in for rhapsody's
`DragonVllmInferenceBackend` that completes a task EXACTLY as `rhapsody/backends/ai/vllm.py`
does: the answer in `task["response"]` as a list of Dragon Inference dicts, no `stdout`, state
DONE. That shape is the point - asyncflow resolves a prompt task from `stdout`, so the
documented route never resolves without `exec/backend.PromptResults` in between, and a stand-in
that set `stdout` itself would prove nothing.
"""
from __future__ import annotations

import asyncio

import pytest
from rhapsody.backends.base import BaseBackend
from rhapsody.backends.constants import StateMapper

from impress_a.compose.validate import SiteCaps
from impress_a.control.http import ControlPlaneClient, ControlPlaneServer
from impress_a.control.plane import InProcessControlPlane
from impress_a.control.session import RemoteSession
from impress_a.core.pareto import Direction, Objective
from impress_a.exec import backend as backend_mod
from impress_a.exec.backend import AI, PromptResults, make_engine
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.tools.registry import Registry


class FakeVllm(BaseBackend):
    """Completes as `vllm.py` does: `task["response"] = [{"assistant": ...}]`, then DONE."""

    def __init__(self, reply=lambda prompt: f"echo:{prompt}"):
        super().__init__(name=AI)
        StateMapper.register_backend_tasks_states_with_defaults(self.name)
        self._cb = None
        self.reply = reply
        self.prompts: list[str] = []

    def register_callback(self, func):
        self._cb = func

    def get_task_states_map(self):
        return StateMapper(AI)

    def task_state_cb(self, task, state):
        self._cb(task, state)

    def build_task(self, *a, **k):
        pass

    def state(self):
        return "RUNNING"

    async def cancel_task(self, uid):
        return False

    async def shutdown(self):
        pass

    async def submit_tasks(self, tasks):
        for t in tasks:
            self.prompts.append(t["prompt"])
            self._cb(t, "RUNNING")

            async def done(t=t):
                await asyncio.sleep(0.01)
                t["response"] = [{"assistant": self.reply(t["prompt"])}]
                self._cb(t, "DONE")

            asyncio.ensure_future(done())


async def _engine_with(tmp_path, ai):
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path),
                                ai=await PromptResults(ai))
    return flow


async def _ask(flow, prompt):
    async def reason():
        return prompt
    return await asyncio.wait_for(flow.prompt_task(backend=AI)(reason)(), 10)


async def test_a_vllm_shaped_completion_resolves_with_the_models_text(tmp_path):
    flow = await _engine_with(tmp_path, FakeVllm())
    try:
        assert await _ask(flow, "hello") == "echo:hello", \
            "unwrapped from [{'assistant': ...}] to the text itself"
    finally:
        await flow.shutdown()


async def test_an_in_band_error_string_fails_the_task_rather_than_answering(tmp_path):
    """The backend reports a batch timeout as DONE with "ERROR: ..." as the answer. Handed to a
    reasoner, that is parsed as a decision; it has to be a failure instead."""
    flow = await _engine_with(tmp_path, FakeVllm(lambda p: "ERROR: Batch timeout, response 1"))
    try:
        with pytest.raises(Exception, match="Batch timeout"):
            await _ask(flow, "hello")
    finally:
        await flow.shutdown()


OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0)]


def _spec(cid, tmp_path, inference):
    return CampaignSpec(campaign_id=cid, goal="g", objectives=OBJS,
                        budget={"gpu_hours": 1.0, "cpu_hours": 1.0}, max_cycles=1,
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1), backend="concurrent",
                        backend_config={"workers": 1}, root=str(tmp_path),
                        trust_root=str(tmp_path / "trust"), inference=inference)


class Idle:
    name = "idle"

    async def conduct(self, session):
        await asyncio.sleep(3600)


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeVllm()

    async def make_ai_backend(inference):
        assert inference["model"]["model_name"] == "stand-in"
        return await PromptResults(model)

    monkeypatch.setattr(backend_mod, "make_ai_backend", make_ai_backend)
    return model


async def test_infer_is_a_prompt_task_on_the_campaigns_own_engine(tmp_path, fake_model):
    mgr = CampaignManager(_spec("t-infer", tmp_path, {"model": {"model_name": "stand-in"}}),
                          Idle(), Registry().load())
    await mgr.executor.start()
    try:
        assert await mgr.session.infer("specify", "what next?") == "echo:what next?"
        assert fake_model.prompts == ["what next?"]
    finally:
        await mgr.executor.shutdown()


async def test_infer_is_refused_where_there_is_no_local_model(tmp_path):
    mgr = CampaignManager(_spec("t-infer-none", tmp_path, {}), Idle(), Registry().load())
    await mgr.executor.start()
    try:
        with pytest.raises(RuntimeError, match="no local model"):
            await mgr.session.infer("specify", "what next?")
    finally:
        await mgr.executor.shutdown()


async def test_a_remote_reasoner_reaches_the_model_on_the_execution_side(tmp_path, fake_model):
    """ADR 0007: an operation in the core protocol is carried by every adapter. The model runs
    on the serving process's engine; only the prompt and the text cross the socket."""
    mgr = CampaignManager(_spec("t-infer-remote", tmp_path,
                                {"model": {"model_name": "stand-in"}}), Idle(), Registry().load())
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    await mgr.executor.start()
    try:
        async with ControlPlaneServer(plane) as server, \
                ControlPlaneClient(server.base_url) as api:
            session = RemoteSession(api, cid)
            assert await session.infer("plan", "which tool?") == "echo:which tool?"
    finally:
        await mgr.executor.shutdown()


# ---------------------------------------------------------------------------
# The reasoner side: a `rhapsody_vllm` profile and the oracle that calls `infer`.
# ---------------------------------------------------------------------------

def test_a_rhapsody_vllm_profile_becomes_the_engines_inference_config():
    from impress_a.policy.llm import ModelProfile, SessionOracle, build_oracle
    p = ModelProfile(name="local", kind="rhapsody_vllm", model="meta-llama/Llama-3.1-8B",
                     max_tokens=2048, temperature=0.0, hardware={"num_gpus": 1},
                     model_options={"tp_size": 1}, hf_token_env="HF_TOKEN")
    assert p.is_live, "it makes model calls, so it is a live arm"
    assert p.inference() == {
        "model": {"model_name": "meta-llama/Llama-3.1-8B", "max_tokens": 2048,
                  "temperature": 0.0, "tp_size": 1},
        "hardware": {"num_gpus": 1}, "hf_token_env": "HF_TOKEN"}, \
        "sampling stays pinned from the profile, as for every other kind"
    assert isinstance(build_oracle(p), SessionOracle)
    assert ModelProfile(name="hosted", kind="openai_compat").inference() == {}


def test_a_barred_vendor_is_refused_for_a_local_model_too(tmp_path):
    """The provenance rule bars a model by any route, and serving one inside the allocation is
    a route."""
    from impress_a.policy.llm import LLMError, load_profiles
    f = tmp_path / "models.yaml"
    f.write_text("profiles:\n  local:\n    kind: rhapsody_vllm\n    model: Qwen/Qwen2.5-7B\n")
    with pytest.raises(LLMError, match="qwen"):
        load_profiles(f)


async def test_the_oracle_refuses_until_bound_and_carries_its_exchange():
    from impress_a.policy.llm import LLMError, ModelProfile, SessionOracle

    class Session:
        def __init__(self):
            self.calls = []

        async def infer(self, node, prompt):
            self.calls.append((node, prompt))
            return '{"next": "ligandmpnn_design"}' if len(self.calls) > 1 else "not json"

    oracle = SessionOracle(ModelProfile(name="l", kind="rhapsody_vllm", model="m"))
    with pytest.raises(LLMError, match="no campaign session"):
        await oracle.think("plan", "which tool?", {"next": "str"})
    session = Session()
    oracle.bind(session)
    with pytest.raises(ValueError, match="did not return JSON"):
        await oracle.think("plan", "which tool?", {"next": "str"})   # ask() retries this
    assert await oracle.think("plan", "try again", {"next": "str"}) == \
        {"next": "ligandmpnn_design"}
    retry = session.calls[1][1]
    assert "which tool?" in retry and "not json" in retry and retry.endswith("Assistant:"), \
        "the corrective retry carries the exchange so far"
    assert oracle.token_counts_estimated and oracle.prompt_tokens > 0


async def test_the_oracle_reaches_the_model_on_the_campaigns_engine(tmp_path, monkeypatch):
    from impress_a.policy.llm import ModelProfile, SessionOracle
    model = FakeVllm(reply=lambda prompt: '{"done": true}')

    async def make_ai_backend(inference):
        return await PromptResults(model)

    monkeypatch.setattr(backend_mod, "make_ai_backend", make_ai_backend)
    mgr = CampaignManager(_spec("t-oracle", tmp_path, {"model": {"model_name": "m"}}),
                          Idle(), Registry().load())
    await mgr.executor.start()
    try:
        oracle = SessionOracle(ModelProfile(name="l", kind="rhapsody_vllm", model="m"))
        oracle.bind(mgr.session)
        assert await oracle.think("specify", "anything left?", {"done": "bool"}) == \
            {"done": True}
        assert model.prompts and model.prompts[0].startswith("User: anything left?")
    finally:
        await mgr.executor.shutdown()


def test_tools_are_not_placed_on_the_local_models_gpus():
    from impress_a.exec.stage import StageExecutor
    reg = Registry().load()
    s = StageExecutor(None, reg, "dragon", gpus_per_node=4, gpu_offset=1)
    assert [s._gpu_for(i) for i in range(4)] == [1, 2, 3, 1], "GPU 0 is the model's"
    assert StageExecutor(None, reg, gpus_per_node=2, gpu_offset=1)._gpu_for(5) == 1, \
        "one GPU left is still pinned, or a tool could land on the model's"
    with pytest.raises(ValueError, match="no GPU is left"):
        StageExecutor(None, reg, gpus_per_node=1, gpu_offset=1)._gpu_for(0)


def test_the_executor_reserves_what_the_profile_asks_for(tmp_path):
    def model_gpus(hardware):
        spec = _spec("t-res", tmp_path, {"model": {"model_name": "m"}, "hardware": hardware})
        spec.site = SiteCaps(gpu_api="cuda", gpus_per_node=4)
        return CampaignManager(spec, Idle(), Registry().load()).executor._model_gpus()

    assert model_gpus({"num_gpus": 1}) == 1
    assert model_gpus({"num_gpus": -1}) == 4, "Dragon's -1 is every GPU on the node"
    assert model_gpus({"num_gpus": 2, "node_offset": 1}) == 0, "a node of its own"


def test_the_cli_hands_the_engine_its_model_and_the_halves_an_oracle_to_bind(tmp_path):
    """`run`/`serve` fill `spec.inference` from the profile (the engine side); `build_roles`
    hands back the oracle so whichever process holds a session can bind it."""
    from impress_a.cli import _inference_for, build_roles
    from impress_a.policy.llm import SessionOracle
    assert _inference_for("local-dragon")["hardware"]["num_gpus"] == 1
    assert _inference_for(None) == {} and _inference_for("rehearsal") == {}
    pair = build_roles("B", _spec("t-cli", tmp_path, {}), profile="local-dragon")
    assert isinstance(pair.session_oracle, SessionOracle)
    assert build_roles("D", _spec("t-cli-d", tmp_path, {})).session_oracle is None
