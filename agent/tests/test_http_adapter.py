"""T4 - the HTTP control plane, exercised end to end on loopback.

This test exists to stop the adapter rotting. An unbuilt transport is a gap; a built one
that nothing runs is worse, because it looks finished. It is the cheapest form of the
guarantee: drive a real campaign through the socket and assert the far side sees what an
in-process caller would.
"""
from __future__ import annotations

import asyncio

import pytest

from impress_a.compose.validate import SiteCaps
from impress_a.control.http import ControlPlaneClient, ControlPlaneServer
from impress_a.control.plane import InProcessControlPlane
from impress_a.core.artifacts import (
    AUTHORITY_ASSAY,
    Property,
    PropertySource,
    SourceKind,
)
from impress_a.core.pareto import Direction, Objective
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55)]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _spec(cid, root, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 20.0, "cpu_hours": 100.0},
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root=str(root), **kw)


async def _guarded(caller, plane, cid):
    """Run the caller, and stop the campaign whatever happens.

    Without this a failed assertion leaves `Idle` sleeping and the campaign never
    returns - a test that hangs instead of reporting which line broke.
    """
    try:
        await caller()
    finally:
        await plane.stop(cid, "caller finished")


class Idle:
    """Stays alive so an external caller can drive - model C's shape, over HTTP."""

    name = "idle"

    async def conduct(self, session):
        await asyncio.sleep(3600)


async def test_a_campaign_is_driven_entirely_over_http(reg, tmp_path):
    spec = _spec("t-http", tmp_path, max_cycles=99, concurrency=4)
    mgr = CampaignManager(spec, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def caller():
            async with ControlPlaneClient(server.base_url) as api:
                await asyncio.sleep(0.2)

                obs = await api.observe(cid)
                assert obs.campaign_id == cid, "the same observation a policy receives"
                assert obs.goal == "stabilize"

                intent = {"goal": "g", "stages": CHAIN, "replicas": 1}
                accepted = await api.submit_run(cid, intent)
                assert accepted["accepted"], accepted
                run_id = accepted["run_id"]

                listed = await api.list_runs(cid)
                assert any(r["run_id"] == run_id for r in listed)

                for _ in range(200):
                    result = await api.run_result(cid, run_id)
                    if result is not None:
                        break
                    await asyncio.sleep(0.05)
                else:
                    raise AssertionError("no result came back over the wire")

                # Stage 4's contract, observed from the far side of a socket.
                assert result["run_id"] == run_id
                assert result["artifacts"], "a run must report what it produced"
                for port, ref in result["artifacts"].items():
                    assert ref["type"], f"{port} arrived untyped"
                    assert ref["path"] or ref["value"] is not None

                events = [e async for e in api.events(cid)]
                assert {"campaign", "graphs", "executions"} <= {e["kind"] for e in events}

                prov = await api.provenance(cid, "graphs")
                assert prov and all("signature" in g for g in prov)

                front = await api.artifacts(cid, "front")
                assert isinstance(front, list)

                # Where a run got to, and what is still outstanding - the two questions
                # that used to have no route, so a remote caller could only poll for a
                # result and never ask what was happening.
                assert (await api.status(cid, run_id)).state.is_terminal
                assert isinstance(await api.inflight(cid), list)

                # Backtracking is non-destructive, over the wire as anywhere else.
                nid = result["nodes"][0]
                branched = await api.backtrack(cid, nid, "external caller branching")
                assert mgr.tree.get(branched).parent == nid
                assert nid in mgr.tree.nodes, "the abandoned branch stays"

                # `since` is a watermark into absorption order; without it on the wire a
                # remote observer cannot ask what landed since it last looked.
                fresh = await api.observe(cid, since=obs.seq)
                assert fresh.recent and fresh.seq > obs.seq
                assert not (await api.observe(cid, since=fresh.seq)).recent

                await api.pause(cid)
                assert mgr.executor.paused, "pause must reach the executor"
                await api.resume(cid)
                assert not mgr.executor.paused

                await api.stop(cid, "caller done over http")

        t = asyncio.create_task(_guarded(caller, plane, cid))
        res = await asyncio.wait_for(mgr.run(), timeout=60)
        await t

    assert res.stop_reason == "caller done over http"
    assert len(mgr.tree) >= 1


async def test_a_rejected_run_answers_409_with_its_reason(reg, tmp_path):
    """Admission is synchronous: refused in the same call that asked, with the gate and
    the reason - which is what a remote reasoner needs to retry sensibly."""
    spec = _spec("t-http-reject", tmp_path, max_cycles=99, concurrency=4)
    mgr = CampaignManager(spec, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def caller():
            async with ControlPlaneClient(server.base_url) as api:
                await asyncio.sleep(0.2)
                bad = await api.submit_run(
                    cid, {"goal": "g", "stages": ["no_such_tool"], "replicas": 1})
                assert bad["accepted"] is False
                assert bad["failure"]["gate"] == "type", bad
                assert "no_such_tool" in bad["failure"]["reason"]
                assert await api.run_result(cid, "r9999") is None, \
                    "an unknown run is absent, not an error payload"
                await api.request_human(cid, "which ligand?", {"tried": 1})
                assert mgr.pending_human is not None
                assert mgr.pending_human.question == "which ligand?", \
                    "the question must reach the executor, not stop at the socket"

        t = asyncio.create_task(_guarded(caller, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=60)
        await t


async def test_measurements_and_cancellation_cross_the_wire(reg, tmp_path):
    spec = _spec("t-http-measure", tmp_path, max_cycles=99, concurrency=4)
    mgr = CampaignManager(spec, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async with ControlPlaneServer(plane) as server:
        async def caller():
            async with ControlPlaneClient(server.base_url) as api:
                await asyncio.sleep(0.2)
                run = await api.submit_run(
                    cid, {"goal": "g", "stages": CHAIN, "replicas": 1})
                rid = run["run_id"]

                cancelled = await api.cancel_run(cid, rid)
                assert cancelled["requested"] and cancelled["advisory"], \
                    "cancellation must not claim more than it can deliver"

                for _ in range(200):
                    if await api.run_result(cid, rid) is not None:
                        break
                    await asyncio.sleep(0.05)

                nid = next(iter(mgr.tree.nodes), None)
                if nid is not None:
                    out = await api.ingest_measurement(cid, nid, Property(
                        name="ddg", value=-5.0,
                        source=PropertySource(name="robolab", kind=SourceKind.MEASURED,
                                              authority=AUTHORITY_ASSAY)))
                    assert out["accepted"]
                    assert mgr.tree.get(nid).properties["ddg"].is_measured
                await api.stop(cid, "done")

        t = asyncio.create_task(_guarded(caller, plane, cid))
        await asyncio.wait_for(mgr.run(), timeout=60)
        await t


async def test_the_blocking_result_route_answers_all_four_ways(reg, tmp_path):
    """The long poll, with nothing racing it.

    `GET /runs/<id>/result?wait=` is what lets a remote `CampaignSession.result` block
    instead of poll, and it has exactly four answers: the outcome, "ask again" when the
    deadline beat the run, "gone" when the campaign ended first, and "unknown". The pump
    is deliberately never started, so the run's future is one nothing will resolve - the
    deadline and the halt are then the only two things that can end the wait, which is
    what makes the assertions below deterministic rather than a race against a mock tool
    that finishes in milliseconds.
    """
    spec = _spec("t-http-wait", tmp_path, max_cycles=99, concurrency=4)
    mgr = CampaignManager(spec, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    await mgr.executor.start()
    try:
        async with ControlPlaneServer(plane) as server, \
                ControlPlaneClient(server.base_url) as api:
            run = await api.submit_run(
                cid, {"goal": "g", "stages": CHAIN, "replicas": 1})
            rid = run["run_id"]
            assert (await api.status(cid, rid)).run_id == rid
            assert [r.run_id for r in await api.inflight(cid)] == [rid]

            started = asyncio.get_running_loop().time()
            answer = await api.await_run_result(cid, rid, 0.4)
            held = asyncio.get_running_loop().time() - started
            assert answer["state"] == "pending", answer
            assert held >= 0.3, \
                "the request must be HELD to its deadline, not answered immediately"

            assert (await api.await_run_result(cid, "r9999", 0.1))["state"] == "unknown"

            # And the halt reaches a waiter that is already blocked.
            waiting = asyncio.create_task(api.await_run_result(cid, rid, 20.0))
            await asyncio.sleep(0.2)
            assert not waiting.done()
            await api.stop(cid, "stopped with a caller waiting")
            stopped = await asyncio.wait_for(waiting, timeout=20)
            assert stopped["state"] == "stopped"
            assert "stopped with a caller waiting" in stopped["reason"]
    finally:
        await mgr.executor.shutdown()
