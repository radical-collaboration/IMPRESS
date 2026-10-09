"""Framework task defaults against a real engine and rhapsody backend."""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from radical.asyncflow import WorkflowEngine

from impress import ImpressBasePipeline, ImpressManager, PipelineSetup

rhapsody_backends = pytest.importorskip("rhapsody.backends")


async def _make_flow(work_dir):
    compute = await rhapsody_backends.ConcurrentExecutionBackend(
        ThreadPoolExecutor(max_workers=2), name="compute"
    )
    local = await rhapsody_backends.ConcurrentExecutionBackend(
        ThreadPoolExecutor(max_workers=2), name="local"
    )
    return await WorkflowEngine.create(backend=[compute, local], work_dir=str(work_dir))


class ShellPipeline(ImpressBasePipeline):
    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def ok():
            return "bash -c 'echo out-line; echo err-line >&2'"

        @self.auto_register_task()
        async def broken():
            return "bash -c 'for i in $(seq 1 25); do echo e$i >&2; done; exit 3'"

    async def run(self):
        self.state["ok"] = await self.ok()
        try:
            await self.broken()
        except Exception as exc:
            self.state["error"] = exc
        await self.run_adaptive_step()


@pytest.mark.integration
async def test_stdio_captured_labelled_and_failure_explained(tmp_path):
    flow = await _make_flow(tmp_path)
    seen = {}

    def decide(pipeline):  # a plain sync callback
        seen["thread"] = threading.get_ident()
        seen["state"] = dict(pipeline.state)

    manager = ImpressManager(flow, use_colors=False)
    try:
        await manager.start(
            [PipelineSetup(name="p1", type=ShellPipeline, adaptive_fn=decide)]
        )
    finally:
        await flow.shutdown()

    state = seen["state"]
    # Captured by default: the result is a file under the engine work dir.
    stdout_path = state["ok"]
    assert stdout_path.startswith(str(tmp_path))
    with open(stdout_path) as fh:
        assert fh.read() == "out-line\n"
    stderr_path = stdout_path[: -len(".stdout")] + ".stderr"
    assert os.path.isfile(stderr_path)

    # The failure carries the end of the task's stderr.
    exc = state["error"]
    if sys.version_info >= (3, 11):
        note = "\n".join(exc.__notes__)
        assert "e25" in note
        assert "e5\n" not in note

    # The adaptive callback ran in a worker thread on the "local" backend.
    assert seen["thread"] != threading.get_ident()
