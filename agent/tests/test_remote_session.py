"""T5 - the reasoner in a genuinely separate process.

`core/session.py` has always described the split it was designed for: "a reasoner on a
login node talking to an executor inside a batch allocation". Everything needed for it
was true - the surface is request/response, every value is serializable, the HTTP adapter
carries the whole control plane - except that nothing implemented `CampaignSession` over
that transport. A caller on the far side could submit and then poll, which is not the
same thing: `SequentialPolicyDriver` blocks in `result()`, and a `conduct` reasoner
collects with `as_completed`, and neither of those crossed the wire.

The assertion that matters is the first one: an UNMODIFIED model-D policy, driven by the
unmodified driver, reaches the same tree and the same Pareto front from outside the
process as it does inside it. If that holds, "where the reasoner runs" really is a
deployment decision and not an architectural one.

Mock tools only - no GPU, no real toolkit, like the rest of the campaign tier.
"""
from __future__ import annotations

import asyncio

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.interlock import PatternRecord
from impress_a.compose.validate import SiteCaps
from impress_a.control.http import ControlPlaneClient, ControlPlaneServer
from impress_a.control.plane import InProcessControlPlane
from impress_a.control.session import RemoteSession
from impress_a.core.decision import ExperimentIntent
from impress_a.core.pareto import Direction, Objective
from impress_a.core.session import (
    CampaignSession,
    CampaignStopped,
    SubmissionRejected,
)
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.driver import SequentialPolicyDriver
from impress_a.policy.explicit import ThresholdPolicy
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55),
        Objective(name="ddg", direction=Direction.MIN)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _spec(cid, root, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        max_cycles=kw.pop("max_cycles", 4),
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root=str(root), **kw)


class Idle:
    """The in-process half of a split campaign: it holds the allocation and decides
    nothing. Every decision arrives from the other side of the socket."""

    name = "idle"

    async def conduct(self, session):
        await asyncio.sleep(3600)


async def _guarded(caller, plane, cid):
    """Run the caller, then end the campaign whatever happened - otherwise a failed
    assertion leaves `Idle` asleep and the test hangs instead of reporting."""
    try:
        await caller()
    finally:
        await plane.stop(cid, "caller finished")


def _shape(nodes):
    """Compare campaigns by what they FOUND, not by the ids they minted.

    Node ids carry a per-process token and a sequence, so two campaigns can be identical
    scientifically and share not one id. What has to match is the lineage structure, the
    QC verdict and the numbers.
    """
    return [(n.cycle, n.qc.verdict.value,
             sorted((k, p.value) for k, p in n.properties.items()))
            for n in nodes]


def _trust(mgr, reg, stages=CHAIN):
    """Mark the self-consistency shape already proven at this site.

    The interlock refuses to run an UNTRUSTED pattern concurrently with itself, so a
    fan-out of one novel workflow is not something any reasoner may do - remote or not.
    """
    sig = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=stages, replicas=1), "probe"
    ).pattern_signature()
    mgr.trust.patterns[sig] = PatternRecord(signature=sig, trusted=True, clean_runs=3)


def test_a_remote_session_is_a_campaign_session():
    """`CampaignSession` is `runtime_checkable`; this is the check it exists for.

    A driver accepts a session, not a transport. If this fails, models A, B and D cannot
    be pointed at a remote campaign whatever else works.
    """
    session = RemoteSession(object(), "c-1")
    assert isinstance(session, CampaignSession)
    assert isinstance(session, CampaignSession) == isinstance(
        RemoteSession(object(), "c-2"), CampaignSession)


async def test_an_unchanged_policy_reaches_the_same_campaign_out_of_process(reg, tmp_path):
    """Model D, driven by the standard driver, over a socket - same result.

    Both halves get their own campaign root so each starts from an empty trust ledger;
    sharing one would let the first campaign promote the pattern the second then runs
    under different scrutiny, and the comparison would be measuring the ledger.
    """
    reference = await CampaignManager(
        _spec("t-parity", tmp_path / "in-process"), ThresholdPolicy(), reg).run()

    s = _spec("t-parity", tmp_path / "remote")
    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def drive():
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid, wait_s=10.0)
                assert isinstance(session, CampaignSession)
                # Exactly what `CampaignManager._reasoner()` builds in process, around a
                # policy that has no idea it is not there.
                await SequentialPolicyDriver(
                    ThresholdPolicy(), max_turns=s.max_cycles,
                    max_attempts=s.max_attempts,
                    concurrency=s.concurrency).conduct(session)

        t = asyncio.create_task(_guarded(drive, plane, cid))
        res = await asyncio.wait_for(mgr.run(), timeout=180)
        await t

    assert len(res.tree) == len(reference.tree) > 0
    assert _shape(res.tree) == _shape(reference.tree), \
        "the same policy must explore the same design space from outside the process"
    assert _shape(res.front) == _shape(reference.front), \
        "and rank it the same way"
    assert res.stop_reason == reference.stop_reason
    assert res.cycles == reference.cycles


async def test_a_rejection_crosses_the_wire_with_its_gate_and_reason(reg, tmp_path):
    """Admission is synchronous, and a 409 is a `SubmissionRejected` on this side.

    The bounded retry depends on the policy being told WHY in the same breath as it
    asked. A transport that flattened the refusal into a generic error would leave
    `on_rejected` with nothing to act on.
    """
    s = _spec("t-remote-reject", tmp_path, max_cycles=99)
    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def drive():
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid)
                with pytest.raises(SubmissionRejected) as caught:
                    await session.submit(ExperimentIntent(
                        goal="g", stages=["no_such_tool"], replicas=1))
                assert caught.value.failure.gate == "type"
                assert "no_such_tool" in caught.value.failure.reason
                assert caught.value.failure.transient is False
                await session.stop("done")

        t = asyncio.create_task(_guarded(drive, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=60)
        await t


async def test_as_completed_delivers_runs_over_the_wire_as_they_finish(reg, tmp_path):
    """The other collection mechanism, remoted.

    In process this consumes `CampaignExecutor._completed`, an `asyncio.Queue` that by
    construction cannot be seen from another process. Here the same sequence arrives on
    the event stream - so a `conduct` reasoner fanning out and adapting to whatever lands
    first is expressible from outside the allocation too, which was the originating
    requirement for the whole decoupling.
    """
    s = _spec("t-remote-ensemble", tmp_path, max_cycles=99, concurrency=8)
    mgr = CampaignManager(s, Idle(), reg)
    _trust(mgr, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    submitted: list[str] = []
    collected: list[str] = []
    overlapped = 0

    async with ControlPlaneServer(plane) as server:
        async def drive():
            nonlocal overlapped
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid, wait_s=10.0, event_timeout_s=3.0)
                obs = await session.observe()
                for _ in range(4):
                    submitted.append(await session.submit(ExperimentIntent(
                        goal=obs.goal, stages=CHAIN, replicas=1)))
                overlapped = len(await session.inflight())
                async for outcome in session.as_completed(submitted):
                    collected.append(outcome.run_id)
                    assert outcome.artifacts, "a delivered run must carry what it made"
                await session.stop("ensemble complete")

        t = asyncio.create_task(_guarded(drive, plane, cid))
        res = await asyncio.wait_for(mgr.run(), timeout=180)
        await t

    assert overlapped > 1, "four experiments were submitted without waiting on any"
    assert sorted(collected) == sorted(submitted), \
        "every submitted run must be delivered exactly once"
    assert len(mgr.tree) >= 4, "each lineage is its own candidate"
    assert res.stop_reason == "ensemble complete"


async def test_as_completed_is_woken_when_the_campaign_ends(reg, tmp_path):
    """Nothing may be left iterating a campaign that has ended.

    In process the queue gets a `None` sentinel. Over the wire the sentinel is a record
    on the event stream, written at the same instant and for the same reason - after
    drain, when nothing further can possibly arrive.
    """
    s = _spec("t-remote-ended", tmp_path, max_cycles=99, concurrency=8)
    mgr = CampaignManager(s, Idle(), reg)
    _trust(mgr, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    woken = asyncio.Event()

    async with ControlPlaneServer(plane) as server:
        async def drive():
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid, wait_s=5.0, event_timeout_s=3.0)
                obs = await session.observe()
                rid = await session.submit(ExperimentIntent(
                    goal=obs.goal, stages=CHAIN, replicas=1))
                # Ask for one run that will land and one that never will.
                try:
                    async for _ in session.as_completed([rid, "r9999"]):
                        await session.stop("stopping with a run still wanted")
                except CampaignStopped:
                    woken.set()

        t = asyncio.create_task(_guarded(drive, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=120)
        await t

    assert woken.is_set(), \
        "as_completed must be woken by the campaign ending, not left waiting"


async def test_termination_wakes_an_outstanding_remote_result(reg, tmp_path):
    """The characteristic hazard of the split, now with a socket in the middle.

    In process `CampaignExecutor.result` races the run's future against the halt event,
    because a terminating executor that simply stops answering deadlocks its reasoner.
    That race has to survive the transport: a long poll that returned "nothing yet"
    forever would be the same deadlock wearing a timeout.

    The pump is deliberately not started, so the run's future is one nothing will ever
    set - which is exactly the state the hazard describes, without a fast mock tool
    racing the assertion.
    """
    s = _spec("t-remote-stop", tmp_path, max_cycles=99)
    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    await mgr.executor.start()
    try:
        async with ControlPlaneServer(plane) as server, \
                ControlPlaneClient(server.base_url) as api:
            session = RemoteSession(api, cid, wait_s=20.0)
            obs = await session.observe()
            rid = await session.submit(ExperimentIntent(
                goal=obs.goal, stages=CHAIN, replicas=1))

            waiting = asyncio.create_task(session.result(rid))
            await asyncio.sleep(0.2)
            assert not waiting.done(), \
                "result() must BLOCK on the far side, not poll from this one"

            await session.stop("stopped while the reasoner was waiting")
            with pytest.raises(CampaignStopped):
                await asyncio.wait_for(waiting, timeout=20)
    finally:
        await mgr.executor.shutdown()


async def test_the_rest_of_the_session_reaches_the_executor(reg, tmp_path):
    """`status`, `inflight`, `cancel`, `backtrack` and `request_human` over the wire.

    Each of these existed on `CampaignSession` and on the executor and had no route
    between them, which is why a remote caller had to poll `run_result` and could not
    branch the tree at all. ADR 0007 is the reason they were added to the CORE protocol
    first and only then rendered as routes.
    """
    s = _spec("t-remote-ops", tmp_path, max_cycles=99, concurrency=4)
    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def drive():
            async with ControlPlaneClient(server.base_url) as api:
                session = RemoteSession(api, cid, wait_s=10.0)
                obs = await session.observe()
                rid = await session.submit(ExperimentIntent(
                    goal=obs.goal, stages=CHAIN, replicas=1))

                assert (await session.status(rid)).run_id == rid
                assert rid in {r.run_id for r in await session.inflight()}
                with pytest.raises(KeyError):
                    await session.status("r9999")

                outcome = await session.result(rid)
                assert outcome.run_id == rid and outcome.nodes

                branched = await session.backtrack(outcome.nodes[0], "trying again")
                assert mgr.tree.get(branched).parent == outcome.nodes[0], \
                    "backtracking branches the tree; it never deletes"

                # `since` is a watermark into absorption order, and it has to cross the
                # wire or a remote observer cannot ask "what landed since I last looked".
                after = await session.observe(since=obs.seq)
                assert after.recent and after.seq > obs.seq
                assert not (await session.observe(since=after.seq)).recent

                await session.cancel(rid)          # advisory, and finished anyway
                await session.request_human("which ligand?", {"tried": 1})

        t = asyncio.create_task(_guarded(drive, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=120)
        await t

    assert mgr.pending_human is not None
    assert mgr.pending_human.question == "which ligand?", \
        "a request for a human must reach the executor, not just the socket"


class _RecordsInterpret(ThresholdPolicy):
    """A model-D policy that writes down every outcome `interpret` is handed."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.interpreted: list[str] = []

    async def interpret(self, results, obs):
        self.interpreted.append(results.run_id)
        return await super().interpret(results, obs)


async def test_interpret_reaches_a_policy_on_the_far_side_of_the_socket(reg, tmp_path):
    """The hook has to cross the wire, or a policy quietly changes behaviour remotely.

    This is the one thing the parity test could not catch. `interpret` was called by the
    executor, on the executor's OWN policy - which in a split campaign is the placeholder
    holding the allocation, not the reasoner that is deciding anything. So a policy that
    accumulates across runs stopped accumulating the moment it moved out of process:
    `ThresholdPolicy._stalled` stayed at 0, and the `Backtrack` it guards
    (`explicit.py:53`) became unreachable. Nothing failed; the policy just silently
    became a different policy.
    """
    s = _spec("t-remote-interpret", tmp_path, max_cycles=3)
    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    pol = _RecordsInterpret()

    async with ControlPlaneServer(plane) as server:
        async def drive():
            async with ControlPlaneClient(server.base_url) as api:
                await SequentialPolicyDriver(
                    pol, max_turns=s.max_cycles, max_attempts=s.max_attempts,
                    concurrency=s.concurrency).conduct(
                        RemoteSession(api, cid, wait_s=10.0))

        t = asyncio.create_task(_guarded(drive, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=180)
        await t

    assert pol.interpreted, \
        "interpret never reached the remote policy - the reasoner is not seeing its own results"
    assert len(pol.interpreted) == len(set(pol.interpreted)), \
        f"interpret called twice for the same run: {pol.interpreted}"
    assert mgr.executor.policy is not pol, \
        "the placeholder, not the reasoner, is what the executor holds - the point of the test"
