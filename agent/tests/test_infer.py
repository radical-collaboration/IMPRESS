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
