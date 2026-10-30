"""Framework task defaults against a real engine and asyncflow's own backend.

Needs no rhapsody, so it runs wherever the package's own dependencies are
installed. `LocalExecutionBackend` ignores `capture_stdio`: it returns stdout
as text and puts a failed command's stderr text in the exception, so this
covers the other failure shape from `test_task_defaults.py`.

The commands run script files rather than `bash -c '...'`. asyncflow 0.5.1
`shlex.split`s an executable's command and this backend re-joins the parts
with spaces, so any quoting is lost. See F15 in
plans/2026-10-15-asyncflow-pattern-rollback.md.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from radical.asyncflow import LocalExecutionBackend, WorkflowEngine

from impress import ImpressBasePipeline, ImpressManager, PipelineSetup
from impress.utils.logger import ImpressLogger


async def _make_flow(work_dir):
    compute = await LocalExecutionBackend(ThreadPoolExecutor(max_workers=2), name="compute")
    # Named threads, so a test can prove which pool a callback ran on.
    local = await LocalExecutionBackend(
        ThreadPoolExecutor(max_workers=2, thread_name_prefix="localpool"),
        name="local",
    )
    return await WorkflowEngine.create(backend=[compute, local], work_dir=str(work_dir))


def _script(path, body):
    path.write_text(body)
    return str(path)


class ShellPipeline(ImpressBasePipeline):
    ok_script = broken_script = None  # set per test, before the manager starts

    def register_pipeline_tasks(self):
        @self.auto_register_task()
        async def ok():
            return f"bash {self.ok_script}"

        @self.auto_register_task()
        async def broken():
            return f"bash {self.broken_script}"

    async def run(self):
        self.state["ok"] = await self.ok()
        try:
            await self.broken()
        except Exception as exc:
            self.state["error"] = exc
        await self.run_adaptive_step()


@pytest.mark.integration
async def test_failure_explained_and_adaptive_on_declared_backend(tmp_path, monkeypatch):
    logged = []
    monkeypatch.setattr(
        ImpressLogger,
        "pipeline_log",
        lambda self, message, level=None: logged.append(message),
    )
    monkeypatch.setattr(
        ShellPipeline,
        "ok_script",
        _script(tmp_path / "ok.sh", "echo out-line; echo err-line >&2\n"),
    )
    monkeypatch.setattr(
        ShellPipeline,
        "broken_script",
        _script(
            tmp_path / "broken.sh",
            "for i in $(seq 1 25); do echo e$i >&2; done; exit 3\n",
        ),
    )
    flow = await _make_flow(tmp_path)
    seen = {}

    async def decide(pipeline):  # asyncflow's task shape: no awaits needed
        seen["thread"] = threading.get_ident()
        seen["thread_name"] = threading.current_thread().name
        seen["state"] = dict(pipeline.state)

    decide_task = flow.function_task(backend="local")(decide)

    manager = ImpressManager(flow, use_colors=False)
    try:
        await manager.start([PipelineSetup(name="p1", type=ShellPipeline, adaptive_fn=decide_task)])
    finally:
        await flow.shutdown()

    state = seen["state"]
    # This backend returns stdout as text rather than a file path.
    assert state["ok"] == "out-line\n"

    # The failure carries the command's stderr in the exception itself...
    exc = state["error"]
    assert isinstance(exc, RuntimeError)
    assert "e25" in str(exc)
    # ...and the log line names the stage and includes it.
    failures = [m for m in logged if m.startswith("broken failed:")]
    assert len(failures) == 1
    assert "e25" in failures[0]

    # The adaptive callback ran on the backend it was declared on — not just
    # off the loop, but on that backend's own pool.
    assert seen["thread"] != threading.get_ident()
    assert seen["thread_name"].startswith("localpool")


@pytest.mark.integration
async def test_undeclared_adaptive_fn_fails_before_any_work(tmp_path):
    """A callback the caller never declared is refused up front.

    The manager has no execution path of its own to fall back to, so this has
    to fail rather than silently run somewhere. Passed as a dict, the shape a
    child config arrives in, so `start()` is what normalizes and refuses it.
    """
    flow = await _make_flow(tmp_path)
    manager = ImpressManager(flow, use_colors=False)
    try:
        with pytest.raises(TypeError, match=r"p1'.*not an engine task"):
            await manager.start(
                [{"name": "p1", "type": ShellPipeline, "adaptive_fn": lambda p: None}]
            )
        assert manager.pipeline_tasks == {}
    finally:
        await flow.shutdown()


@pytest.mark.integration
async def test_declared_elsewhere_but_passed_bare_is_refused(tmp_path):
    """The bare body of a declared callback is refused, against the real engine.

    asyncflow marks the function it decorates, not just the wrapper it
    returns, so after a callback has been declared the bare body carries
    `__task_description__` too. The mark alone therefore cannot tell them
    apart, and a child config that passes the bare name — the recursion
    mistake the docs warn about — would otherwise reach the engine and fail
    as a caught `adaptive_failed`, leaving the pipeline to carry on with no
    decision taken.
    """
    flow = await _make_flow(tmp_path)
    try:

        async def adaptive_decision(pipeline):
            pass

        adaptive_task = flow.function_task(backend="local")(adaptive_decision)

        # Upstream's own behaviour, asserted so this test fails loudly if a
        # future asyncflow stops marking the original.
        assert hasattr(adaptive_decision, "__task_description__")

        PipelineSetup(name="p1", type=ShellPipeline, adaptive_fn=adaptive_task)
        with pytest.raises(TypeError, match="undecorated function"):
            PipelineSetup(name="p1", type=ShellPipeline, adaptive_fn=adaptive_decision)
    finally:
        await flow.shutdown()
