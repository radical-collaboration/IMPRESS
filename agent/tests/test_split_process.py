"""T5 - the control plane in its own process.

Backlog C5: the out-of-process split was reachable from `tests/` and from no shell, so
`docs/reference/frontends.md` described as "implemented" something nobody could run. Three of
these tests drive the roles over a loopback socket, which exercises the same code path the
split uses; the last one spawns `impress-a serve` and `impress-a control` as real processes,
because "reachable from a shell" is the part a same-process test cannot claim.

What the split buys, and what these assert:

* the roles run unchanged against `RemoteSession` - which is the whole reason phase 1 wrote
  them against `CampaignSession` rather than against the executor;
* the executor's pump reaps independently of the control side, so a slow Specifier costs
  decisions rather than throughput;
* losing the control process drains and stops with a reason that names the loss, rather than
  leaving a campaign silently not replanning while it holds an allocation.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import sys
import time

import pytest
import yaml

from impress_a.cli import run_campaign
from impress_a.compose.validate import SiteCaps
from impress_a.control.http import ControlPlaneClient, ControlPlaneServer
from impress_a.control.plane import InProcessControlPlane
from impress_a.control.session import RemoteSession
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners import ExternalPlanner, ThresholdPlanner
from impress_a.policy.registry import RolePair
from impress_a.policy.specifiers import ExternalSpecifier, ThresholdSpecifier
from impress_a.runtime.roles import RolesDriver
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _spec(cid, tmp_path, **kw):
    # A budget large enough that the interlock's 10%-of-available cap cannot reject the first
    # admission. Not cosmetic: a rejected submission still burns a run label, run labels seed
    # the replica draws, and so a comparison between two campaigns that retried a different
    # number of times compares different science. Removing the retry makes the parity question
    # answerable; the cap itself is tested in `test_validation.py`, where it belongs.
    return CampaignSpec(
        campaign_id=cid, goal="stabilize", objectives=OBJS,
        budget={"gpu_hours": 40.0, "cpu_hours": 200.0},
        site=SiteCaps(gpu_api="cuda", gpus_per_node=1), backend="concurrent",
        backend_config={"workers": 3}, root=str(tmp_path),
        trust_root=str(tmp_path / f"trust-{cid}"), stages=CHAIN, **kw)


class _Idle:
    """The execution side's non-reasoner. See `cli._Idle`."""

    name = "served"

    async def conduct(self, session):
        await asyncio.Event().wait()


def _shape(nodes):
    return [(n.cycle, n.qc.verdict.value,
             sorted((k, p.value) for k, p in n.properties.items())) for n in nodes]


async def _drive_remotely(reg, spec, driver_factory, wait_s=30.0):
    """Serve `spec`, drive it over loopback, and return the campaign result."""
    mgr = CampaignManager(spec, _Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    async with ControlPlaneServer(plane) as server:
        async def control():
            try:
                async with ControlPlaneClient(server.base_url) as api:
                    session = RemoteSession(api, cid)
                    obs = await session.observe()
                    goal = Goal(text=obs.goal, objectives=list(obs.objectives))
                    await driver_factory(goal).conduct(session)
            finally:
                # Without this a failed assertion leaves the served campaign waiting forever,
                # and the test hangs instead of reporting which line broke.
                await plane.stop(cid, "control side finished")

        task = asyncio.create_task(control())
        res = await asyncio.wait_for(mgr.run(), timeout=wait_s)
        await task
    return res


async def test_the_roles_drive_a_campaign_over_a_socket(reg, tmp_path):
    """The split changes nothing, which is the only thing worth asserting about a move.

    Same policy, same science, in-process and across a socket. A failure after this is a
    transport failure and nothing else - which is why the roles were written against
    `CampaignSession` in phase 1 rather than against the executor.
    """
    local = await CampaignManager(
        _spec("t-local", tmp_path, max_cycles=3), RolePair(*_halves()), reg).run()

    # Built with the same bounds `CampaignManager._roles()` gives the in-process driver, so
    # the only difference between the two campaigns is the transport.
    remote = await _drive_remotely(
        reg, _spec("t-remote", tmp_path, max_cycles=3),
        lambda goal: RolesDriver(goal, *_halves(), max_turns=3, max_attempts=4,
                                 concurrency=1))

    assert _shape(remote.tree.nodes.values()) == _shape(local.tree.nodes.values()), \
        "every node, verdict and metric must match the in-process campaign"
    assert remote.cycles == local.cycles
    assert len(remote.front) == len(local.front)


def _halves():
    """Model D's two halves - which, since phase 11, is what model D *is*.

    These tests used to drive `DecideAsRoles(ThresholdPolicy())`, a `ControlPolicy` presented
    as a pair, so that the split could be shown to change nothing before anything moved. The
    strangler is finished and the adapter is gone; the pair is the real one.
    """
    return ThresholdSpecifier(), ThresholdPlanner(stages=CHAIN)


async def test_the_pump_reaps_while_the_control_side_is_slow(reg, tmp_path):
    """A slow Specifier costs decisions, not throughput.

    This is what the split is FOR. The executor's pump and the roles are independent: work
    already admitted is reaped while the control side is thinking, so a decision that takes a
    minute does not idle the allocation for a minute. In one process that independence is a
    property of the loop; across a socket it is a property of the process boundary, and this
    exercises the same seam either way.
    """
    reaped: list[str] = []

    class SlowPlanner:
        name = "slow"

        def __init__(self, inner):
            self.inner = inner

        async def plan(self, spec, ctx):
            # Long enough that a pump waiting on us would show it, short enough to keep the
            # suite fast.
            await asyncio.sleep(0.25)
            return await self.inner.plan(spec, ctx)

        async def replan(self, *a, **kw):
            return await self.inner.replan(*a, **kw)

        async def after_collect(self, *a, **kw):
            return None

    spec = _spec("t-slow", tmp_path, max_cycles=3, concurrency=3)
    mgr = CampaignManager(spec, _Idle(), reg)
    original = mgr.executor._reap

    async def watched(run_id):
        reaped.append(run_id)
        return await original(run_id)

    mgr.executor._reap = watched
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def control():
            try:
                async with ControlPlaneClient(server.base_url) as api:
                    session = RemoteSession(api, cid)
                    obs = await session.observe()
                    goal = Goal(text=obs.goal, objectives=list(obs.objectives))
                    spec_half, plan_half = _halves()
                    await RolesDriver(goal, spec_half, SlowPlanner(plan_half),
                                      max_turns=3, concurrency=3).conduct(session)
            finally:
                await plane.stop(cid, "control side finished")

        task = asyncio.create_task(control())
        await asyncio.wait_for(mgr.run(), timeout=60)
        await task

    assert reaped, "the pump must have collected work while the planner was thinking"


async def test_execution_drains_and_stops_when_contact_is_lost(reg, tmp_path):
    """A lost control process must be loud, and must not abandon paid-for work.

    Draining rather than aborting is deliberate: cancellation is advisory, so in-flight work
    will finish whether or not anyone collects it, and throwing away results already paid for
    buys nothing. The stop reason names the loss, because a campaign that quietly stopped
    replanning while holding an allocation is the failure this exists to make visible.
    """
    spec = _spec("t-lost", tmp_path, max_cycles=50, control_liveness_timeout_s=0.5)
    mgr = CampaignManager(spec, _Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def control():
            """Submit one Stage, then go silent - the shape of a control process that died.

            Driven through the session rather than through `RolesDriver`, and that is the
            whole point: a driver that runs out of turns calls `session.stop` on its way out,
            which is a control process saying goodbye. Letting it do that here made the test a
            race between its own stop and the liveness timeout - the campaign ended with
            `max_cycles=1 reached` whenever the Stage finished inside the timeout, which is
            most of the time on mock tools. A process that died makes no further calls at all.
            """
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid)
                obs = await session.observe()
                goal = Goal(text=obs.goal, objectives=list(obs.objectives))
                spec_half, plan_half = _halves()
                campaign_spec = await spec_half.initial_spec(goal)
                await session.publish_spec(campaign_spec)
                stage = await plan_half.plan(
                    campaign_spec, PlanningContext(goal, await session.observe()))
                await session.submit_stage(stage)

        task = asyncio.create_task(control())
        res = await asyncio.wait_for(mgr.run(), timeout=60)
        await task

    assert "control plane lost" in res.stop_reason, res.stop_reason
    assert mgr.executor._inflight == {}, "in-flight work was drained, not abandoned"
    lost = [r for r in mgr.prov.read("transitions") if r.get("event") == "control_lost"]
    assert lost, "the loss must be on the record, not only in the stop reason"
    assert lost[0]["silent_s"] >= 0.5


@pytest.mark.skipif(shutil.which("impress-a") is None,
                    reason="console script not installed in this environment")
async def test_serve_and_control_drive_a_campaign_in_two_processes(tmp_path):
    """Backlog C5, answered the only way it can be: from a shell.

    Every other test here shares one interpreter, so none of them can claim the entry points
    exist. This spawns both and asserts the campaign completes - which is also the exact shape
    `scripts/delta_gpu_run.sh` uses when it starts the control sidecar beside the server.
    """
    spec_path = tmp_path / "split.yaml"
    spec_path.write_text(yaml.safe_dump({
        "campaign_id": "split-cli", "goal": "stabilize", "backend": "concurrent",
        "backend_config": {"workers": 3}, "max_cycles": 2, "stagnation_limit": 9,
        "control_liveness_timeout_s": 30, "root": str(tmp_path),
        "site": {"gpu_api": "cuda", "gpus_per_node": 1},
        "budget": {"gpu_hours": 2.0, "cpu_hours": 12.0}, "stages": CHAIN,
        "objectives": [{"name": "sc_rmsd", "direction": "minimize", "max": 3.0},
                       {"name": "iptm", "direction": "maximize", "min": 0.55}]}))

    env = dict(os.environ, IMPRESS_A_TRUST_DIR=str(tmp_path / "trust"),
               IMPRESS_A_HEARTBEAT_S="0")
    server = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "impress_a", "serve", str(spec_path), "--port", "0",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
    try:
        url = None
        for _ in range(200):                       # the URL is printed, not guessed
            line = await asyncio.wait_for(server.stdout.readline(), timeout=30)
            if not line:
                break
            text = line.decode(errors="replace")
            if "serving on" in text:
                url = text.strip().split()[-1]
                break
        assert url, "the server must print the URL it bound, since the port is chosen for it"

        control = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "impress_a", "control", "--connect", url,
            "--campaign", "split-cli", "--model", "D",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
        out, _ = await asyncio.wait_for(control.communicate(), timeout=120)
        assert control.returncode == 0, out.decode(errors="replace")[-2000:]

        rest, _ = await asyncio.wait_for(server.communicate(), timeout=120)
        served = rest.decode(errors="replace")
        assert "stop" in served, served[-2000:]
        assert server.returncode == 0, served[-2000:]
    finally:
        for proc in (server,):
            if proc.returncode is None:
                proc.kill()
                await proc.wait()


async def test_model_c_is_refused_by_run_rather_than_silently_becoming_d(tmp_path, caplog):
    """Backlog C6, closed by refusing rather than by detecting.

    `impress-a run` attaches no control plane, so model C's `decide` blocked on an inbox
    nothing fed, timed out every five seconds and ran its declared fallback - producing a
    model-D campaign reported as model C. That is the single most dangerous failure mode in a
    four-arm comparison, because a disguised arm is indistinguishable from a real one in every
    figure derived from it.

    The entry points that make C real exist now, so "no caller attached" is an operator error
    with an answer rather than a mode to degrade into.
    """
    spec_path = tmp_path / "c.yaml"
    spec_path.write_text(yaml.safe_dump({
        "campaign_id": "c-refused", "goal": "stabilize", "backend": "concurrent",
        "max_cycles": 1, "root": str(tmp_path), "stages": CHAIN,
        "site": {"gpu_api": "cuda", "gpus_per_node": 1},
        "budget": {"gpu_hours": 2.0, "cpu_hours": 12.0},
        "objectives": [{"name": "iptm", "direction": "maximize", "min": 0.55}]}))

    with caplog.at_level("ERROR"):
        rc = await run_campaign(str(spec_path), model="C")
    assert rc == 1, "a model-C `run` must fail, not fall back"
    # And it must say what to do instead: an error that refuses without naming the remedy just
    # moves the confusion.
    assert "impress-a serve" in caplog.text and "impress-a control" in caplog.text, caplog.text
    assert not (tmp_path / "c-refused-C").exists(), \
        "no campaign directory: it refused before starting, rather than part way through"


async def test_naming_c_as_either_half_is_refused_too():
    """`--specifier C` is the same hazard wearing a different flag."""
    assert await run_campaign("campaigns/mock-stabilize.yaml", specifier="C") == 1
    assert await run_campaign("campaigns/mock-stabilize.yaml", planner="C") == 1


# ---------------------------------------------------------------------------
# The real halves over the wire, in one process and across a socket.
# ---------------------------------------------------------------------------

async def test_a_models_own_halves_reproduce_the_in_process_campaign(reg, tmp_path):
    """Model D's real Specifier and Planner, in one process and across a socket.

    The parity assertion the plan requires of every move, applied to the thing that now
    executes: `cli.build_roles` prefers a model's declared halves over the legacy adapter, so
    `--model D --control roles` runs `ThresholdSpecifier` + `ThresholdPlanner` and the earlier
    tests here no longer cover what ships.
    """
    def pair():
        return RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=CHAIN))

    local_spec = _spec("t-halves-local", tmp_path, max_cycles=3)
    local = await CampaignManager(local_spec, pair(), reg).run()

    remote = await _drive_remotely(
        reg, _spec("t-halves-remote", tmp_path, max_cycles=3),
        lambda goal: RolesDriver(goal, *_halves(), max_turns=3, max_attempts=4,
                                 concurrency=1))

    assert _shape(remote.tree.nodes.values()) == _shape(local.tree.nodes.values()), \
        "every node, verdict and metric must match the in-process campaign"
    assert remote.cycles == local.cycles
    assert remote.stop_reason == local.stop_reason
    assert len(remote.front) == len(local.front)


async def test_an_external_caller_steers_both_halves_over_the_socket(reg, tmp_path):
    """Model C end to end, which is the only path model C has.

    **The arrangement is one process, and writing this test is what established that.** The
    first attempt served the campaign with no reasoner and drove it from a control process,
    the way arms A, B and D run - and every directive came back
    `campaign is not under external control`, because `plane.steer` reaches
    `manager.policy`, which is in the *execution* process, and the halves were in the control
    process. That is not a transport bug: decision 0002 says model C **is** the headless mode,
    and the headless mode is one process serving a campaign whose halves are its inboxes.
    `impress-a serve <spec> --model C` is that arrangement; `impress-a serve <spec>` alone
    keeps the split for the models whose halves have no inbox.

    Both inboxes are fed through the one `steer` operation with a `role` key, the campaign
    produces real nodes, and nothing falls back: a C arm that silently became a D arm is
    byte-for-byte a D campaign and invisible in the log, which the four-arm design names as
    one of its two dangerous failures.
    """
    spec = _spec("t-steered", tmp_path, max_cycles=2)
    pair = RolePair(ExternalSpecifier(timeout_s=15.0),
                    ExternalPlanner(stages=CHAIN, timeout_s=15.0, on_timeout="stop"))
    mgr = CampaignManager(spec, pair, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def caller():
            """A third party, over HTTP, through the plane's own operation and nothing else."""
            async with ControlPlaneClient(server.base_url) as api:
                for _ in range(2):
                    assert (await api.steer(cid, {"role": "specifier", "kind": "hold"})
                            )["accepted"] is True
                    assert (await api.steer(cid, {"role": "planner", "stages": CHAIN,
                                                  "replicas": 1,
                                                  "params": {"mock_fold": {"recycles": 5}}})
                            )["accepted"] is True
                    await asyncio.sleep(0.3)

        steering = asyncio.create_task(caller())
        res = await asyncio.wait_for(mgr.run(), timeout=60)
        await steering

    assert res.tree.nodes, "the caller's directives produced real designs"
    assert pair.planner.directives >= 1
    assert pair.planner.rejections == [], "no directive was refused at a gate"
    timeouts = [r for r in mgr.prov.read("transitions")
                if r.get("event") == "caller_timeout"]
    assert timeouts == [], f"arm C must not have fallen back: {timeouts}"
    # And the caller's parameter actually reached the graph, which is what distinguishes
    # steering a campaign from watching one.
    deployed = [r for r in mgr.prov.read("stages") if r.get("event") == "deployed"]
    assert deployed, "no stage was deployed"
    recycles = {m["params"].get("recycles") for r in deployed for m in r["mappings"]
                if m["tool"] == "mock_fold"}
    assert recycles == {5}, f"the caller's parameters did not reach the tasks: {recycles}"


async def test_an_unaddressed_half_is_refused_with_its_reason_over_http(reg, tmp_path):
    """A directive the campaign cannot route must come back refused, not as a 500.

    `RolePair.steer` raises `ValueError` when the addressed half has no inbox, and a 500 over
    the wire says "this server is broken" where the truth is "this campaign's specifier is not
    the external one". It is also what tells a caller its directives are going nowhere -
    silently dropping them would report an arm as externally steered while it steered itself.
    """
    spec = _spec("t-unroutable", tmp_path, max_cycles=1)
    mgr = CampaignManager(spec, RolePair(*_halves()), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    answer = await plane.steer(cid, {"role": "planner", "stages": CHAIN})
    assert answer["accepted"] is False
    assert "takes no external directives" in answer["reason"]
    assert "threshold-plan" in answer["reason"], "it must say which half refused"


async def test_serve_binds_loopback_on_an_ephemeral_port_and_writes_the_url(reg, tmp_path):
    """The whole boundary this arrangement can defend, asserted against a real `serve`.

    The plane has no auth and no TLS (backlog C7), and ADR 0014 settles that for exactly this
    configuration: both ends on one compute node, bound to loopback. So three things have to
    hold, and one was briefly broken by the launcher.

    **Loopback**, because a host-reachable plane with no auth is a different proposition.
    **An ephemeral port**, because a fixed one is guessable, collides with a second `serve` on
    the same node, and is the one piece of this arrangement an unrelated process could find
    without looking - the Delta launcher pinned it to 8711 for one commit, which was a
    regression against this default. **And the URL in a 0600 file**, so a sidecar reads it
    rather than being told a number.

    What none of this defends against is another process of the SAME user, and a token would
    not either: the same user can read the token. What rules that out is the node being the
    job's, which is a property of the resource request rather than of this code.
    """
    import os
    import stat

    from impress_a.cli import serve_campaign

    spec_file = tmp_path / "c.yaml"
    spec_file.write_text(
        "campaign_id: t-serve-url\ngoal: g\nbackend: concurrent\n"
        "backend_config: {workers: 1}\nmax_cycles: 1\nstages: [mock_generate]\n"
        f"root: {tmp_path / 'runs'}\n"
        f"trust_root: {tmp_path / 'trust'}\n"
        "objectives:\n  - {name: ss_fraction, direction: maximize, min: 0.1}\n")

    # No --model, so the campaign is served with no reasoner and ends on the liveness path or
    # its own cycle bound. What is under test is the socket it opened, not the science.
    served = asyncio.create_task(serve_campaign(str(spec_file)))
    url_file = tmp_path / "runs" / "t-serve-url" / "control_plane.url"
    for _ in range(200):
        if url_file.is_file():
            break
        await asyncio.sleep(0.05)
    assert url_file.is_file(), "serve must write the URL where a sidecar can read it"

    url = url_file.read_text().strip()
    assert url.startswith("http://127.0.0.1:"), \
        f"a plane with no auth must bind loopback, got {url}"
    port = int(url.rsplit(":", 1)[1].rstrip("/"))
    assert port not in (0, 8711), (
        f"port {port} is either unassigned or the fixed one the launcher briefly pinned; an "
        f"ephemeral port is the hardening")
    assert stat.S_IMODE(os.stat(url_file).st_mode) == 0o600, \
        "the url file must be owner-only - it is the whole of what a caller needs"

    served.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await served


def test_the_launcher_does_not_pin_the_control_planes_port():
    """The regression this file's test above describes, pinned at its source.

    `serve`'s own default is an ephemeral port. The launcher passed `--port 8711` for one
    commit, which replaced a hardening with a guessable constant - and a launcher flag is
    exactly where such a thing survives, because nothing about the server would look wrong.
    """
    import pathlib

    launcher = pathlib.Path("scripts/delta_gpu_run.sh").read_text()
    serve_branch = launcher.split("    serve)")[1].split(";;")[0]
    code = "\n".join(line.split("#", 1)[0] for line in serve_branch.splitlines())
    assert "--port" not in code, \
        "the launcher must not pin the port: serve's ephemeral default is the hardening"
    assert "--host" not in code, \
        "nor the host: loopback is the only boundary a plane with no auth can defend"


async def test_the_liveness_bound_is_armed_only_for_a_registered_campaign(reg, tmp_path):
    """An in-process campaign has no control plane, so there is none to lose.

    `control_liveness_timeout_s: 120` killed three arms of the first four-arm smoke - A, B
    and D, each after ONE cycle, at 267s/182s/185s of "silence" against a 120s bound - while
    arm C, the only arm that actually had a caller, ran to its own stop. Nothing external
    existed for those three: the "caller" was the role driver in the same process, and it is
    silent exactly when it is busy awaiting the tasks it just asked for.

    The spec's comment claimed the bound "matters for any arm driven from a control process",
    which is the opposite of what it did. `cli/__init__.py` records that the setting did
    nothing at all until the loader began reading it, so its first real outing was the one
    that lost three arms.

    Two conditions, both asserted here: registration is what arms it, and work in flight
    suspends it - because a cycle of the real chain runs ~180s with no session traffic, so
    any bound shorter than a cycle turns normal progress into a lost plane for arm C too.
    """
    from impress_a.control.plane import InProcessControlPlane

    spec = _spec("t-liveness", tmp_path, control_liveness_timeout_s=120.0)
    mgr = CampaignManager(spec, _Idle(), reg)
    assert mgr.under_external_control is False, \
        "a campaign nobody registered must not be under external control"
    mgr.executor._last_contact = time.monotonic() - 10_000
    assert mgr.executor._control_lost_for() is None, \
        "an in-process campaign has no plane to lose, however long it is quiet"

    InProcessControlPlane().register(mgr)
    assert mgr.under_external_control is True, "registering IS what arms the bound"
    assert mgr.executor.under_external_control is True, \
        "and it must reach the executor, which is what consults it - not stop at the manager"
    assert mgr.executor._control_lost_for() is not None, \
        "a registered campaign silent past its bound has lost its caller"

    mgr.executor._inflight["r0001"] = object()
    try:
        assert mgr.executor._control_lost_for() is None, \
            "work in flight explains the silence; a long cycle is not a dead caller"
    finally:
        mgr.executor._inflight.clear()
