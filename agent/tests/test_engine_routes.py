"""The one engine and its two routes: `compute` (default) and `local`.

A campaign has exactly one `WorkflowEngine`. Tool work is routed to `compute`, the campaign's
execution backend; parsing and QC are routed to `local`, a thread pool in the engine's own
process. These tests put work through both, because the only way to tell a live route from a
registered-but-dead one is to run something on it (see test_backend_bound.py's docstring for
what that cost once).
"""
from __future__ import annotations

import os
import threading

import pytest

from impress_a.exec.backend import COMPUTE, LOCAL, make_engine, probe_topology


@pytest.fixture
async def engine(tmp_path):
    flow, backend = await make_engine("concurrent", {"workers": 1}, work_dir=str(tmp_path))
    try:
        yield flow, backend
    finally:
        await flow.shutdown()


async def test_the_engine_has_exactly_the_two_routes_and_compute_is_the_default(engine):
    flow, backend = engine
    assert backend.name == COMPUTE
    assert flow.backend is backend, "an unrouted task must land on compute"
    assert set(flow._backends) == {COMPUTE, LOCAL}


def _pid() -> int:
    return os.getpid()


async def test_local_runs_in_the_engines_own_process_and_compute_does_not(engine):
    """`compute` here is a process pool, so a task routed there runs in another process;
    `local` must run in this one, or a QC task could not read the campaign's own objects."""
    flow, _ = engine

    @flow.function_task(backend=LOCAL)
    async def where_local():
        return os.getpid(), threading.current_thread() is not threading.main_thread()

    @flow.function_task
    async def where_compute():
        return _pid()

    pid, off_main = await where_local()
    assert pid == os.getpid() and off_main, "local is a thread pool in this process"
    assert await where_compute() != os.getpid(), "compute is the campaign's process pool"


async def test_an_unknown_route_fails_where_it_is_declared(engine):
    flow, _ = engine
    with pytest.raises(ValueError, match="compute"):
        @flow.function_task(backend="cmopute")
        async def misrouted():
            return 1


async def test_topology_describes_the_concurrent_host(engine):
    _, backend = engine
    topo = await probe_topology(backend)
    assert len(topo) == 1 and {"id", "cores", "gpus"} <= set(topo[0])
    assert topo[0]["cores"] >= 1


async def test_a_backend_that_cannot_describe_itself_is_unknown_not_empty_handed():
    class Mute:
        name = "mute"

    class Broken:
        name = "broken"

        def topology(self):
            raise RuntimeError("NVML said no")

    assert await probe_topology(Mute()) == []
    assert await probe_topology(Broken()) == []
