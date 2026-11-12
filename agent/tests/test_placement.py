"""Placement: every tool command is an engine task, placed in its backend's own vocabulary.

Two halves. The rendering - what `Placement.describe` hands each backend - is asserted directly,
including Dragon's, against a stand-in `Policy` because Dragon is an optional extra the tier does
not install. The routing - that a command started by an adapter really becomes an executable task
on the engine's `compute` route, with its GPU and thread share in force, while the adapter itself
runs in this process - is asserted by running real commands through a real engine.

What this replaces, and why it is asserted rather than described: a node used to be one opaque
Python function task on `compute` with no task description, so the backend never saw the binary,
and `_subprocess.child_env` said "there the placement policy pins" about a policy nothing set.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types

import pytest

from impress_a.compose.composer import Composer
from impress_a.core.decision import ExperimentIntent
from impress_a.exec.backend import COMPUTE, make_engine
from impress_a.exec.launch import Launcher
from impress_a.exec.resources import (
    KILL_GRACE_S,
    Placement,
    placement_for,
    thread_caps,
    thread_share,
)
from impress_a.exec.stage import StageExecutor
from impress_a.tools._subprocess import SubprocessError, run_cmd
from impress_a.tools.agent import TaskAgent
from impress_a.tools.registry import Registry
from impress_a.tools.spec import ResourceShape

GPU = ResourceShape(gpus=1, cores=4)
CPU = ResourceShape(gpus=0, cores=8)


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------

def test_only_a_gpu_tool_is_given_a_gpu():
    """A CPU stage pinned to a device holds nothing on it, and under Dragon its policy would
    restrict it for no reason."""
    assert placement_for(GPU, "concurrent", threads=2, gpu_index=1).gpu_index == 1
    assert placement_for(CPU, "concurrent", threads=2, gpu_index=1).gpu_index is None


def test_the_concurrent_backend_is_pinned_by_the_env_it_replaces():
    """rhapsody's concurrent backend REPLACES a child's environment, so the description carries
    the whole environment, with the placement on top."""
    d = placement_for(GPU, "concurrent", threads=3, gpu_index=1).describe(
        env={"PATH": "/usr/bin", "MPNN_DIR": "/opt/mpnn"}, cwd="/w")
    assert d["cwd"] == "/w"
    assert d["env"]["PATH"] == "/usr/bin" and d["env"]["MPNN_DIR"] == "/opt/mpnn"
    assert d["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    assert d["env"]["OMP_NUM_THREADS"] == "3" and d["env"]["OMP_WAIT_POLICY"] == "PASSIVE"
    assert "PATH" in placement_for(CPU, "concurrent", threads=1).describe()["env"], \
        "no env asked for means this process's own, never an empty one"


@pytest.fixture
def fake_dragon(monkeypatch):
    """`dragon.infrastructure.policy.Policy`, recording what it was built with."""
    class Policy:
        class Placement:
            HOST_NAME = "HOST_NAME"

        def __init__(self, **kw):
            self.kw = kw

    names = ("dragon", "dragon.infrastructure", "dragon.infrastructure.policy")
    mods = {n: types.ModuleType(n) for n in names}
    mods["dragon.infrastructure.policy"].Policy = Policy
    for n, m in mods.items():
        monkeypatch.setitem(sys.modules, n, m)
    return Policy


def test_dragon_is_pinned_by_policy_and_never_by_the_env(fake_dragon, monkeypatch):
    """Dragon merges a template's env into the node's own and applies the policy AFTER, so a
    `CUDA_VISIBLE_DEVICES` in the env is overwritten - and one that survived would name a device
    Dragon never gave the process. The policy pins; the env carries only what differs."""
    monkeypatch.setenv("SHARED", "same")
    d = placement_for(GPU, "dragon", threads=2, gpu_index=3, host="gpub001").describe(
        env={**os.environ, "BOLTZ_CACHE": "/c"}, cwd="/w", timeout_s=600)
    tmpl = d["process_template"]
    assert tmpl["cwd"] == "/w"
    assert "CUDA_VISIBLE_DEVICES" not in tmpl["env"]
    assert tmpl["env"]["BOLTZ_CACHE"] == "/c" and tmpl["env"]["OMP_NUM_THREADS"] == "2"
    assert "SHARED" not in tmpl["env"], "sending our whole env would overwrite the node's"
    assert tmpl["policy"].kw == {"placement": "HOST_NAME", "host_name": "gpub001",
                                 "gpu_affinity": [3]}
    assert d["timeout"] == 600 + KILL_GRACE_S, "Dragon enforces the walltime itself"


def test_a_dragon_cpu_stage_on_one_host_carries_no_policy(fake_dragon):
    d = placement_for(CPU, "dragon", threads=8, gpu_index=0).describe()
    assert "policy" not in d["process_template"]


def test_an_operator_who_exported_a_cap_keeps_it(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "16")
    caps = thread_caps(2)
    assert caps["OMP_NUM_THREADS"] == "16" and caps["MKL_NUM_THREADS"] == "2"


def test_the_thread_share_divides_the_allocation_not_the_node(monkeypatch):
    """The three Rosetta stages are CPU-bound and run one per lineage. Sized from
    `os.cpu_count()` they would each claim the whole node and fight. Backlog C9."""
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: set(range(64)))
    assert thread_share(None, 2, 4) == 4, "64 cpus / (2*4 pipelines * 2)"
    assert thread_share(None, 1, 0) == 32, "replicas 0 ('policy decides') divides by one"
    assert thread_share(12, 1, 1) == 6, "a caller's grant beats the cgroup"
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: {0, 1})
    assert thread_share(None, 4, 8) == 1, "never zero"


# ---------------------------------------------------------------------------
# Routing, through a real engine.
# ---------------------------------------------------------------------------

#: What each probe command saw, keyed by node. The probe adapter runs on the `local` route -
#: a thread in this process - which is exactly what lets it write here.
SEEN: dict[str, dict] = {}


class ProbeAgent(TaskAgent):
    """Runs one command that reports its own environment, and records where each half ran."""

    async def run(self, req, params):
        out, _ = await run_cmd(
            ["sh", "-c", 'echo "${CUDA_VISIBLE_DEVICES:-none} ${OMP_NUM_THREADS:-none} $$"'])
        gpu, threads, child = out.split()
        SEEN[req.node_id] = {"gpu": gpu, "threads": threads, "child": int(child),
                             "adapter_pid": os.getpid()}
        return {"outputs": {}, "metrics": {}}


class _ProbeRegistry:
    def __init__(self, real):
        self.real = real

    def get(self, tool_id):
        return self.real.get(tool_id)

    def agent_for(self, tool_id):
        return ProbeAgent


async def test_a_command_is_an_engine_task_placed_on_its_lineages_gpu(reg, tmp_path):
    """The adapter runs here; its command runs on `compute`, as an executable task named after
    the node, with that lineage's device and the campaign's thread share in its environment."""
    SEEN.clear()
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=["mock_generate"],
                                               replicas=2), "r0001")
    flow, _ = await make_engine("concurrent", {"workers": 2}, work_dir=str(tmp_path))
    try:
        d = StageExecutor(flow, _ProbeRegistry(reg), "concurrent", gpus_per_node=2, threads=3)
        res = await d.collect(d.submit(g, run_id="r0001"))
    finally:
        await flow.shutdown()

    assert not res.failures, res.failures
    assert sorted(v["gpu"] for v in SEEN.values()) == ["0", "1"], SEEN
    assert {v["threads"] for v in SEEN.values()} == {"3"}
    assert {v["adapter_pid"] for v in SEEN.values()} == {os.getpid()}, \
        "the adapter runs on the local route, in this process"
    assert all(v["child"] != os.getpid() for v in SEEN.values())
    for payload in res.per_task.values():
        assert "queued" in payload.usage.phases, "command queue wait is measured apart"
        assert payload.usage.cuda_visible_devices in ("0", "1")
        # And what ran is on the record, as the backend was handed it - not reconstructed
        # from the adapter's source by whoever reads provenance later.
        (cmd,) = payload.usage.commands
        assert cmd["argv"][:2] == ["sh", "-c"], "no walltime was asked for, so no wrapper"
        assert cmd["exit_code"] == 0 and cmd["backend"] == "concurrent"
        assert cmd["placement_env"]["CUDA_VISIBLE_DEVICES"] == str(cmd["gpu_index"])
        assert cmd["placement_env"]["OMP_NUM_THREADS"] == "3"
        assert "PATH" not in cmd["placement_env"], \
            "only what the placement added: the base environment is never recorded"
        assert cmd["queued_s"] >= 0 and cmd["ran_s"] >= 0


def _launch(flow, coro_fn):
    """Call a `Launcher` the way an adapter does: from another thread, on its own loop."""
    return asyncio.to_thread(asyncio.run, coro_fn())


async def test_a_failing_command_raises_the_subprocess_error_adapters_expect(tmp_path):
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path))
    try:
        launcher = Launcher(flow, flow.loop, "n0",
                            placement_for(CPU, "concurrent", threads=1))
        with pytest.raises(SubprocessError) as err:
            await _launch(flow, lambda: launcher.run(
                ["sh", "-c", "echo partial; echo broken >&2; exit 3"]))
    finally:
        await flow.shutdown()
    assert err.value.returncode == 3
    assert [r["exit_code"] for r in launcher.records] == [3], \
        "a failed command is recorded too, with the code it exited on"
    assert "broken" in err.value.stderr and "partial" in err.value.stdout


async def test_a_timed_out_command_is_killed_on_the_backend_and_says_so(tmp_path):
    """The old in-process `run_cmd` killed its child; rhapsody's concurrent backend does not
    kill a process when its task is cancelled. So the bound travels WITH the command."""
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path))
    marker = "73.25"
    try:
        launcher = Launcher(flow, flow.loop, "n0",
                            placement_for(CPU, "concurrent", threads=1))
        with pytest.raises(SubprocessError) as err:
            await _launch(flow, lambda: launcher.run(
                ["sh", "-c", f"echo started >&2; exec sleep {marker}"], timeout_s=1))
    finally:
        await flow.shutdown()
    assert err.value.returncode == -1 and "timed out after 1" in err.value.stderr
    assert "started" in err.value.stderr, "partial stderr survives the kill"
    (rec,) = launcher.records
    assert rec["argv"][:3] == ["timeout", "--kill-after=10", "1"], \
        "the record is the argv the backend ran, wrapper included - not the adapter's"
    assert rec["timeout_s"] == 1 and rec["exit_code"] in (124, 137)
    alive = subprocess.run(["pgrep", "-f", f"sleep {marker}"], capture_output=True, text=True)
    assert not alive.stdout.strip(), "the command must not outlive its walltime"


async def test_outside_the_engine_run_cmd_still_runs_the_command_itself(tmp_path):
    """`impress-a preflight` and the gate fixtures call adapters with no engine at all."""
    out, _ = await run_cmd(["sh", "-c", "echo here"])
    assert out.strip() == "here"


def test_a_placement_is_the_only_thing_that_names_a_backend_route():
    assert COMPUTE == "compute"
    assert Placement(backend_kind="Dragon", threads=1).dragon


async def test_under_dragon_the_walltime_is_dragons_and_the_command_is_not_wrapped(tmp_path):
    """Coreutils `timeout` makes itself a process-group leader, and Dragon's local services
    reaps only children in its own group (`os.waitpid(0, ...)`). A wrapped command therefore
    exits, is never reaped, and its task never completes - job 23814643, both rfd3 commands
    left as `[timeout] <defunct>`. Under Dragon the bound is Dragon's own `timeout`; the
    concurrent backend keeps the wrapper, because its cancel kills nothing.

    The engine here is concurrent - it ignores a process template - so what is asserted is
    the command each placement SUBMITS, which is what Dragon would have been handed.
    """
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path))
    try:
        for kind in ("dragon", "concurrent"):
            launcher = Launcher(flow, flow.loop, f"n-{kind}",
                                placement_for(CPU, kind, threads=1))
            await _launch(flow, lambda la=launcher: la.run(["true"], timeout_s=30))
        submitted = {c["description"]["name"]: c["description"]["executable"]
                     for c in flow.components.values() if c["description"].get("executable")}
    finally:
        await flow.shutdown()
    assert submitted == {"n_dragon.true": "true", "n_concurrent.true": "timeout"}, submitted
