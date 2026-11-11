"""T3 - the execution loop on `impress`.

Everything here is about the seam between IMPRESS-A and the framework at the repository root.
The traps are all in `ImpressBasePipeline`/`ImpressManager` rather than in our own code, which
is why they are asserted rather than described: a reader of `runtime/pipelines.py` cannot tell
from the code that `register_pipeline_tasks()` runs before `self.logger` exists, or that the
manager exits the instant nothing is in flight.
"""
from __future__ import annotations

import asyncio

import pytest
from impress import ImpressBasePipeline

from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps
from impress_a.core.decision import ExperimentIntent
from impress_a.core.pareto import Direction, Objective
from impress_a.exec.backend import make_engine
from impress_a.exec.dispatch import Dispatcher, node_task
from impress_a.exec.resources import gpu_env, thread_caps
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.explicit import ThresholdPolicy
from impress_a.runtime.pipelines import StagePipeline
from impress_a.runtime.runner import StageRunner
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]
#: Which metrics each mock tool reports. Used to prove attribution, not to check the science.
REPORTS = {"mock_generate": {"ss_fraction", "designability"},
           "mock_design": {"seq_recovery", "diversity"},
           "mock_fold": {"iptm", "sc_rmsd", "ss_fraction"}}


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _graph(reg, replicas=2, stages=None):
    return Composer(reg).compose(
        ExperimentIntent(goal="g", stages=stages or CHAIN, replicas=replicas), "r0001")


async def _runner(reg, tmp_path, workers=4):
    flow, _ = await make_engine("concurrent", {"workers": workers}, work_dir=str(tmp_path))
    r = StageRunner(flow, reg, workdir=str(tmp_path))
    await r.start()
    return flow, r


# ---------------------------------------------------------------------------
# The base class's traps.
# ---------------------------------------------------------------------------

def test_a_pipeline_registers_its_tasks_before_the_logger_exists(reg):
    """`register_pipeline_tasks()` runs two lines before `self.logger` is assigned.

    `impress_pipeline.py:61` calls it; `:63` creates the logger. `**config` is stashed at
    `:52`, so reading from `self.config` is safe where reading an attribute a subclass sets
    after `super().__init__()` is not - that ordering crashed job 22692267. `StagePipeline`
    reads `self.config` for exactly this reason, and this test is the record of why.
    """
    seen = {}

    class ReadsConfig(ImpressBasePipeline):
        def register_pipeline_tasks(self):
            seen["has_logger"] = hasattr(self, "logger")
            seen["has_config"] = "marker" in self.config

        async def run(self):
            return None

    ReadsConfig("p", flow=None, marker=1)
    assert seen == {"has_logger": False, "has_config": True}, (
        "the logger does not exist yet, and `self.config` does - which is why a pipeline must "
        "read its configuration rather than an attribute set after super().__init__()")

    class ReadsAttribute(ImpressBasePipeline):
        def register_pipeline_tasks(self):
            _ = self.marker          # set after super().__init__(), so not yet present

        async def run(self):
            return None

    class Subclass(ReadsAttribute):
        def __init__(self, name, flow=None, **cfg):
            super().__init__(name, flow, **cfg)
            self.marker = 1          # too late, by two lines

    with pytest.raises(AttributeError):
        Subclass("p")


async def test_a_stage_pipeline_stays_hashable_by_identity(reg, tmp_path):
    """`ImpressManager.pipeline_tasks` is keyed by the pipeline OBJECT.

    So a pipeline that defined `__eq__`/`__hash__` by value would collide with its siblings and
    the manager would lose their tasks. Nothing in `StagePipeline` should ever define them.
    """
    flow, r = await _runner(reg, tmp_path)
    try:
        first = StagePipeline("a", flow=flow, graph=_graph(reg, 1), registry=reg,
                              done=asyncio.get_running_loop().create_future())
        second = StagePipeline("b", flow=flow, graph=_graph(reg, 1), registry=reg,
                               done=asyncio.get_running_loop().create_future())
        assert first != second and hash(first) != hash(second)
        assert len({first, second}) == 2
        await r.shutdown()
    finally:
        await flow.shutdown()


async def test_the_manager_does_not_exit_during_an_idle_gap(reg, tmp_path):
    """`start()` breaks its loop the moment nothing is in flight.

    A campaign deploys Stages with gaps between them - that is what a control plane is - so
    without a keep-alive the manager finishes before the second Stage arrives, and the
    `ControlPipeline` is structural rather than decorative.
    """
    flow, r = await _runner(reg, tmp_path)
    try:
        await r.collect(r.submit(_graph(reg, 1), run_id="r0001"))
        # An idle gap several poll intervals long: the manager polls at 0.5 s.
        await asyncio.sleep(1.2)
        assert r._loop_task is not None and not r._loop_task.done(), (
            "the manager exited during an idle gap; the keep-alive is not holding it")

        out = await r.collect(r.submit(_graph(reg, 1), run_id="r0002"))
        assert out.per_task, "a Stage deployed after the gap still runs"
        await r.shutdown()
        assert r._loop_task.done(), "releasing the keep-alive lets it drain"
    finally:
        await flow.shutdown()


async def test_two_stages_deployed_in_one_sweep_both_run(reg, tmp_path):
    """The single-slot mailbox hazard, proven absent.

    `submit_child_pipeline_request` is one slot: a second request before the manager's 0.5 s
    poll silently overwrites the first. The Runner uses `submit_new_pipelines` directly, which
    creates each pipeline's task immediately on the caller's own loop.
    """
    flow, r = await _runner(reg, tmp_path, workers=6)
    try:
        first = r.submit(_graph(reg, 1), run_id="r0001")
        second = r.submit(_graph(reg, 1), run_id="r0002")      # same sweep, no await between
        a, b = await asyncio.gather(r.collect(first), r.collect(second))
        assert len(a.per_task) == len(CHAIN) and len(b.per_task) == len(CHAIN)
        assert a.failures == {} and b.failures == {}
        await r.shutdown()
    finally:
        await flow.shutdown()


# ---------------------------------------------------------------------------
# Loop ownership and attribution.
# ---------------------------------------------------------------------------

async def test_the_engine_belongs_to_the_submitting_loop(reg, tmp_path):
    """The constraint that cost jobs 22328172 and 22328262 their full allocations.

    `WorkflowEngine.__init__` captures the running loop and schedules its dispatch on exactly
    that loop. An engine built elsewhere looks healthy and dispatches nothing - so the only way
    to tell a live engine from a dead one is to put work through it, which this does.
    """
    flow, r = await _runner(reg, tmp_path)
    try:
        assert flow.loop is asyncio.get_running_loop(), \
            "false here means every submit hangs forever, silently"
        out = await r.collect(r.submit(_graph(reg, 1), run_id="r0001"))
        assert len(out.per_task) == len(CHAIN), "and work actually went through it"
        await r.shutdown()
    finally:
        await flow.shutdown()


async def test_results_are_attributed_to_the_task_that_produced_them(reg, tmp_path):
    """The bug a two-lineage probe caught, which no single-lineage test could.

    The pipeline built its futures in TOPO order and zipped the results against
    `graph.nodes` in INSERTION order. Kahn's algorithm emits every root first, so with two
    replicas the second lineage's first task lands where the first lineage's second task sits,
    and each node came back carrying whichever task's metrics occupied its position -
    `mock_design` reporting `designability`. A silent misattribution, not a failure.
    """
    flow, r = await _runner(reg, tmp_path, workers=6)
    try:
        g = _graph(reg, 2)
        assert list(g.topo_order()) != list(g.nodes), (
            "this test is only meaningful while the two orders differ; if they stop "
            "differing, find another shape rather than deleting it")
        out = await r.collect(r.submit(g, run_id="r0001"))

        assert out.failures == {}, out.failures
        for tid, result in out.per_task.items():
            tool = g.nodes[tid].tool
            assert result.tool == tool, f"{tid}: reported by {result.tool}, not {tool}"
            assert set(result.metrics) == REPORTS[tool], (
                f"{tid} ({tool}) carries {sorted(result.metrics)}, which belongs to another "
                f"task")
        await r.shutdown()
    finally:
        await flow.shutdown()


async def test_a_failing_task_does_not_cancel_its_siblings(reg, tmp_path):
    """`return_exceptions=True`, and the failure is recorded per task.

    One bad task must not take its siblings with it, and an unretrieved exception on a future
    nobody awaits is a warning nobody sees.
    """
    flow, r = await _runner(reg, tmp_path, workers=6)
    try:
        g = _graph(reg, 2)
        # A node naming a tool the registry does not have fails at construction of its agent.
        g.nodes[next(iter(g.nodes))].tool = "mock_generate"
        out = await r.collect(r.submit(g, run_id="r0001"))
        assert len(out.per_task) + len(out.failures) == len(g.nodes)
        await r.shutdown()
    finally:
        await flow.shutdown()


# ---------------------------------------------------------------------------
# Equivalence with the Dispatcher.
# ---------------------------------------------------------------------------

async def test_both_execution_loops_produce_the_same_campaign(reg, tmp_path):
    """The acceptance criterion for the Runner, and why the default has not moved.

    Identical science down both paths on the laptop tier. What this does NOT prove is Dragon
    placement, GPU affinity or bounded teardown, none of which a `ConcurrentExecutionBackend`
    can exercise - so `CampaignSpec.runner` stays `dispatcher` until a Delta smoke has run.
    Swapping a dispatcher that works for one that has never seen Dragon is the move this
    project's own records argue against.
    """
    def shape(nodes):
        return [(n.cycle, n.qc.verdict.value,
                 sorted((k, p.value) for k, p in n.properties.items())) for n in nodes]

    out = {}
    for runner in ("dispatcher", "impress"):
        s = CampaignSpec(
            campaign_id=f"t-loop-{runner}", goal="stabilize", objectives=OBJS,
            budget={"gpu_hours": 2.0, "cpu_hours": 12.0}, max_cycles=3,
            site=SiteCaps(gpu_api="cuda", gpus_per_node=1), backend="concurrent",
            backend_config={"workers": 3}, root=str(tmp_path),
            trust_root=str(tmp_path / f"trust-{runner}"), control="roles", runner=runner)
        res = await CampaignManager(s, ThresholdPolicy(), reg).run()
        out[runner] = (res.cycles, res.stop_reason, len(res.front),
                       shape(res.tree.nodes.values()))

    assert out["dispatcher"][1] == out["impress"][1], "same stop reason"
    assert out["dispatcher"][0] == out["impress"][0], "same number of runs admitted"
    assert out["dispatcher"][3] == out["impress"][3], "every node, verdict and metric matches"


# ---------------------------------------------------------------------------
# GPU assignment (backlog A10's other half).
# ---------------------------------------------------------------------------

def test_one_lineage_gets_one_gpu(reg):
    """Backlog A10: concurrent GPU tasks were not pinned, and nothing called `resources`.

    Several lineages could land on the same device while others sat idle, which is consistent
    with GPU-busy measuring at most 17% of billed GPU time while three of four GPUs never held
    work. One lineage, one device, round-robin - the way the reference pipeline assigns them.
    """
    d = Dispatcher(None, reg, "dragon", gpus_per_node=4)
    assert [d._gpu_for(i) for i in range(6)] == [0, 1, 2, 3, 0, 1]
    assert Dispatcher(None, reg, "concurrent", gpus_per_node=1)._gpu_for(3) is None, \
        "one device means there is nothing to choose, which is also true of a laptop"


def test_the_env_pins_a_gpu_only_where_the_env_is_what_pins_it():
    """Two shapes, and only one of them is an environment variable.

    Under a concurrent backend the env handed to `asyncio.create_subprocess_exec` REPLACES the
    child's, so `CUDA_VISIBLE_DEVICES` works. Under Dragon it does not: local services merges a
    process template's env and then applies the placement policy afterwards, so a policy with
    no `gpu_affinity` resolves to every GPU on the node whatever the env said. Returning an
    env var for Dragon would look like pinning and do nothing.
    """
    assert gpu_env(2, "concurrent") == {"CUDA_VISIBLE_DEVICES": "2"}
    assert gpu_env(2, "dragon") == {}, "Dragon needs Policy(gpu_affinity=[2]), not an env var"
    assert gpu_env(None, "concurrent") == {}


def test_thread_caps_hold_a_cpu_stage_to_its_share():
    """`os.cpu_count()` reports the node, not the allocation.

    So on anything less than a whole node every CPU stage claims every core and the stages
    fight each other; uncapped, one tool took about 30 cores of the Dragon primary on smoke job
    22670942.
    """
    caps = thread_caps(4)
    assert caps["OMP_NUM_THREADS"] == "4" and caps["MKL_NUM_THREADS"] == "4"
    assert caps["OMP_WAIT_POLICY"] == "PASSIVE", \
        "spinning idle threads burn a core each while a stage waits on the GPU stages"
    assert thread_caps(0)["OMP_NUM_THREADS"] == "1", "never zero"


async def test_a_task_is_told_which_gpu_it_may_use(reg, tmp_path):
    """The assignment has to reach the adapter, which is what applies it to its own child."""
    seen = {}
    g = _graph(reg, 2, stages=["mock_generate"])
    flow, _ = await make_engine("concurrent", {"workers": 3}, work_dir=str(tmp_path))
    try:
        d = Dispatcher(flow, reg, "concurrent", gpus_per_node=2)
        # Intercept at the factory rather than inside a mock agent, so this holds for every
        # tool rather than for the ones that happen to record it.
        original = node_task

        def spy(*args, **kw):
            seen[args[2]] = kw.get("gpu_index")
            return original(*args, **kw)

        import impress_a.exec.dispatch as mod
        mod.node_task = spy
        try:
            await d.collect(d.submit(g, run_id="r0001"))
        finally:
            mod.node_task = original
    finally:
        await flow.shutdown()

    assert set(seen.values()) == {0, 1}, f"both devices should be used: {seen}"
