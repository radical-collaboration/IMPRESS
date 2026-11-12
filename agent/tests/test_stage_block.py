"""Stages as asyncflow blocks - the one execution loop.

Ported from the two loops it replaced (the `Dispatcher` and the IMPRESS-pipeline Runner), keeping
each test for the failure it records, plus what a block adds: a cancel that reaches the work.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import impress_a.exec.stage as stage_mod
from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps
from impress_a.core.decision import ExperimentIntent
from impress_a.core.pareto import Direction, Objective
from impress_a.exec.backend import make_engine
from impress_a.exec.stage import StageExecutor
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.planners import ThresholdPlanner
from impress_a.policy.registry import RolePair
from impress_a.policy.specifiers import ThresholdSpecifier
from impress_a.tools._subprocess import run_cmd
from impress_a.tools.agent import TaskAgent
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]
#: Which metrics each mock tool reports. Used to prove attribution, not to check the science.
REPORTS = {"mock_generate": {"ss_fraction", "designability"},
           "mock_design": {"seq_recovery", "diversity"},
           "mock_fold": {"iptm", "sc_rmsd", "ss_fraction"}}
PARITY = Path(__file__).parent / "data" / "dispatcher_parity_campaign.json"


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _graph(reg, replicas=2, stages=None, label="r0001"):
    return Composer(reg).compose(
        ExperimentIntent(goal="g", stages=stages or CHAIN, replicas=replicas), label)


@pytest.fixture
async def engine(tmp_path):
    flow, _ = await make_engine("concurrent", {"workers": 4}, work_dir=str(tmp_path))
    try:
        yield flow
    finally:
        await flow.shutdown()


# ---------------------------------------------------------------------------
# Loop ownership and attribution.
# ---------------------------------------------------------------------------

async def test_the_engine_belongs_to_the_submitting_loop(reg, engine):
    """The constraint that cost jobs 22328172 and 22328262 their full allocations: an engine
    built on another loop looks healthy and dispatches nothing. Only work through it tells."""
    assert engine.loop is asyncio.get_running_loop()
    out = await StageExecutor(engine, reg).run(_graph(reg, 1), invocation="r0001")
    assert len(out.per_task) == len(CHAIN)


async def test_results_are_attributed_to_the_task_that_produced_them(reg, engine):
    """Kahn's algorithm emits every root first, so with two replicas topo order and insertion
    order differ - and zipping against the wrong one hands each node another's metrics."""
    g = _graph(reg, 2)
    assert list(g.topo_order()) != list(g.nodes), \
        "only meaningful while the orders differ; find another shape rather than deleting it"
    out = await StageExecutor(engine, reg).run(g, invocation="r0001")
    assert out.failures == {}, out.failures
    for tid, result in out.per_task.items():
        tool = g.nodes[tid].tool
        assert result.tool == tool
        assert set(result.metrics) == REPORTS[tool], f"{tid} carries another task's metrics"


async def test_a_failing_task_does_not_cancel_its_siblings(reg, engine):
    g = _graph(reg, 2)
    g.nodes[next(iter(g.nodes))].params = {"no_such_parameter": 1}
    out = await StageExecutor(engine, reg).run(g, invocation="r0001")
    assert out.failures, "the bad node fails"
    assert len(out.per_task) + len(out.failures) == len(g.nodes)
    assert out.per_task, "and the other lineage still ran"


async def test_two_stages_submitted_in_one_sweep_both_run(reg, engine):
    """The IMPRESS child-pipeline mailbox was one slot; a block per Stage has no mailbox."""
    s = StageExecutor(engine, reg)
    first, second = s.submit(_graph(reg, 1), "r0001"), s.submit(_graph(reg, 1), "r0002")
    a, b = await asyncio.gather(s.collect(first), s.collect(second))
    assert len(a.per_task) == len(b.per_task) == len(CHAIN)


async def test_each_run_is_one_block_whose_members_are_its_nodes(reg, engine):
    """One block per run, named alike across runs - the label is what tells them apart."""
    s = StageExecutor(engine, reg)
    h = s.submit(_graph(reg, 2), "r0007")
    await s.collect(h)
    block = engine.components[h.gather.uid]
    assert block["type"] == "block" and block["description"]["name"] == "stage"
    assert block["description"].get("workflow_id") == "r0007"
    assert {engine.components[f.uid]["description"].get("workflow_id")
            for f in h.futures.values()} == {"r0007"}


# ---------------------------------------------------------------------------
# GPU assignment (backlog A10).
# ---------------------------------------------------------------------------

def test_one_lineage_gets_one_gpu(reg):
    """Unpinned GPU tasks piled onto one device while three of four sat idle. One lineage,
    one device, round-robin - the way the reference pipeline assigns them."""
    s = StageExecutor(None, reg, "dragon", gpus_per_node=4)
    assert [s._gpu_for(i) for i in range(6)] == [0, 1, 2, 3, 0, 1]
    assert StageExecutor(None, reg, gpus_per_node=1)._gpu_for(3) is None


async def test_every_lineage_of_a_stage_is_placed_on_its_own_gpu(reg, engine, monkeypatch):
    seen: dict[str, int | None] = {}
    original = stage_mod.node_task

    def spy(*args, **kw):
        seen[args[2]] = kw["placement"].gpu_index
        return original(*args, **kw)

    monkeypatch.setattr(stage_mod, "node_task", spy)
    s = StageExecutor(engine, reg, gpus_per_node=2)
    await s.run(_graph(reg, 4, stages=["mock_generate"]), invocation="r0001")
    assert len(seen) == 4 and set(seen.values()) == {0, 1}, seen


# ---------------------------------------------------------------------------
# Cancellation reaches the work.
# ---------------------------------------------------------------------------

class SleepAgent(TaskAgent):
    """One command that sleeps, and leaves a marker if it ever started."""

    async def run(self, req, params):
        marker = Path(req.workdir) / f"started-{req.node_id.replace(':', '_')}"
        await run_cmd(["sh", "-c", f"touch {marker}; exec sleep 20"], timeout_s=4)
        return {"outputs": {}, "metrics": {}}


class _SleepRegistry:
    def __init__(self, real):
        self.real = real

    def get(self, tool_id):
        return self.real.get(tool_id)

    def agent_for(self, tool_id):
        return SleepAgent


async def test_cancelling_a_stage_stops_queued_commands_and_accounts_for_every_node(
        reg, tmp_path):
    """The Runner cancelled a side-channel future; its tasks ran on, and the executor released
    the run's budget while they did. A block cancel cascades to every unfinished member,
    commands included, so a queued command never starts."""
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path))
    try:
        s = StageExecutor(flow, _SleepRegistry(reg), workdir=str(tmp_path), command_slots=1)
        g = _graph(reg, 3, stages=["mock_generate"], label="r0003")
        h = s.submit(g, "r0003")
        # Wait until one command holds the single compute worker, so the others are queued.
        for _ in range(200):
            if list(tmp_path.glob("started-*")):
                break
            await asyncio.sleep(0.05)
        assert len(list(tmp_path.glob("started-*"))) == 1
        s.cancel(h)
        res = await asyncio.wait_for(s.collect(h), timeout=stage_mod.SETTLE_S + 10)
    finally:
        await flow.shutdown()
    assert h.cancelled
    assert set(res.failures) == set(g.nodes), "every node is accounted for, as cancelled"
    await asyncio.sleep(1.0)
    assert len(list(tmp_path.glob("started-*"))) == 1, "a queued command must never start"


# ---------------------------------------------------------------------------
# Parity with the loop this replaced.
# ---------------------------------------------------------------------------

async def test_a_campaign_matches_the_dispatcher_it_replaced(reg, tmp_path):
    """Recorded from the `Dispatcher` before it was deleted (three identical runs), and replayed
    here: the same stop reason, the same runs, and every node's verdict and metrics."""
    s = CampaignSpec(
        campaign_id="t-loop-parity", goal="stabilize", objectives=OBJS,
        budget={"gpu_hours": 2.0, "cpu_hours": 12.0}, max_cycles=3,
        site=SiteCaps(gpu_api="cuda", gpus_per_node=1), backend="concurrent",
        backend_config={"workers": 3}, root=str(tmp_path), trust_root=str(tmp_path / "trust"))
    pair = RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=CHAIN))
    res = await CampaignManager(s, pair, reg).run()
    got = {"cycles": res.cycles, "stop_reason": res.stop_reason, "front": len(res.front),
           "nodes": [[n.cycle, n.qc.verdict.value,
                      sorted([k, p.value] for k, p in n.properties.items())]
                     for n in res.tree.nodes.values()]}
    assert got == json.loads(PARITY.read_text())
