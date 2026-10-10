import asyncio
import subprocess
import sys
from unittest.mock import Mock

import pytest

from impress.pipelines.impress_pipeline import ImpressBasePipeline
from impress.utils import telemetry as impress_telemetry
from impress.utils.stdio import logged_command


class RecordingFlow:
    """Stands in for WorkflowEngine.executable_task.

    Records the decorator kwargs and each call's kwargs, and hands back a
    plain future the test resolves itself.
    """

    def __init__(self):
        self.decorator_kwargs = None
        self.calls = []
        self.futures = []

    def executable_task(self, **kwargs):
        self.decorator_kwargs = kwargs

        def decorator(func):
            def flow_task(*args, **call_kwargs):
                self.calls.append(call_kwargs)
                fut = asyncio.get_running_loop().create_future()
                self.futures.append(fut)
                return fut

            return flow_task

        return decorator


class OneTaskPipeline(ImpressBasePipeline):
    def __init__(self, name, flow=None, register_kwargs=None, local=False, **kw):
        self._register_kwargs = register_kwargs or {}
        self._local = local
        super().__init__(name, flow, **kw)

    def register_pipeline_tasks(self):
        @self.auto_register_task(local_task=self._local, **self._register_kwargs)
        async def stage(**kwargs):
            if self._local:
                if kwargs.get("fail"):
                    raise ValueError("boom")
                return "local-result"
            return "echo hi"

    async def run(self):
        pass


class FakeTelemetry:
    session_id = "session.test"

    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class TestExecutableTaskDefaults:
    def test_capture_stdio_on_by_default(self):
        flow = RecordingFlow()
        OneTaskPipeline("p1", flow)
        assert flow.decorator_kwargs["capture_stdio"] is True

    def test_capture_stdio_can_be_turned_off(self):
        flow = RecordingFlow()
        OneTaskPipeline("p1", flow, register_kwargs={"capture_stdio": False})
        assert flow.decorator_kwargs["capture_stdio"] is False

    def test_other_kwargs_still_forwarded(self):
        flow = RecordingFlow()
        OneTaskPipeline("p1", flow, register_kwargs={"backend": "local"})
        assert flow.decorator_kwargs["backend"] == "local"

    async def test_workflow_id_defaults_to_pipeline_and_stage(self):
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        p.stage()
        assert flow.calls[0]["workflow_id"] == "p1:stage"

    async def test_caller_workflow_id_wins(self):
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        p.stage(workflow_id="custom")
        assert flow.calls[0]["workflow_id"] == "custom"

    async def test_engine_future_returned_unchanged(self):
        # A stage future must stay the engine's own, so it can be passed to
        # another task as a dependency.
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        fut = p.stage()
        assert fut is flow.futures[0]

    async def test_failure_reports_stderr_tail(self, tmp_path):
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        p.logger = Mock()
        stderr = tmp_path / "task.000001.stderr"
        stderr.write_text("".join(f"line {i}\n" for i in range(30)))

        fut = p.stage()
        # What the Concurrent backend raises with capture_stdio on.
        fut.set_exception(RuntimeError(str(stderr)))
        await asyncio.sleep(0)  # let the done callback run

        message = p.logger.pipeline_log.call_args.args[0]
        assert "stage failed" in message
        assert "line 29" in message
        assert "line 9\n" not in message  # only the last 20 lines
        with pytest.raises(RuntimeError) as info:
            await fut
        if sys.version_info >= (3, 11):
            assert any("line 29" in n for n in info.value.__notes__)

    async def test_failure_without_stderr_file_still_logged(self):
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        p.logger = Mock()
        fut = p.stage()
        fut.set_exception(SystemExit(3))
        await asyncio.sleep(0)
        assert "SystemExit(3)" in p.logger.pipeline_log.call_args.args[0]
        with pytest.raises(SystemExit):
            await fut

    async def test_success_logs_nothing(self):
        flow = RecordingFlow()
        p = OneTaskPipeline("p1", flow)
        p.logger = Mock()
        fut = p.stage()
        fut.set_result("/path/to/stdout")
        await asyncio.sleep(0)
        p.logger.pipeline_log.assert_not_called()


@pytest.mark.skipif(
    impress_telemetry.LocalStage is None, reason="rhapsody telemetry not installed"
)
class TestLocalTaskTelemetry:
    async def test_local_task_emits_one_event_per_call(self):
        p = OneTaskPipeline("p1", local=True)
        tel = FakeTelemetry()
        p._telemetry = tel
        assert await p.stage() == "local-result"
        assert len(tel.events) == 1
        event = tel.events[0]
        assert (event.stage, event.pipeline, event.status) == (
            "stage",
            "p1",
            "completed",
        )
        assert event.duration >= 0

    async def test_failed_local_task_reports_failed(self):
        p = OneTaskPipeline("p1", local=True)
        tel = FakeTelemetry()
        p._telemetry = tel
        with pytest.raises(ValueError):
            await p.stage(fail=True)
        assert tel.events[0].status == "failed"

    async def test_no_telemetry_is_a_no_op(self):
        p = OneTaskPipeline("p1", local=True)
        assert await p.stage() == "local-result"

    def test_local_task_keeps_its_name(self):
        p = OneTaskPipeline("p1", local=True)
        assert p.stage.__name__ == "stage"


class TestLoggedCommand:
    def test_success_writes_log(self, tmp_path):
        log = tmp_path / "stage.log"
        cmd = logged_command(str(log), "echo 'hello world'; echo err >&2")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        assert res.returncode == 0
        assert log.read_text() == "hello world\nerr\n"
        assert res.stderr == ""

    def test_failure_tails_log_to_stderr(self, tmp_path):
        log = tmp_path / "my stage.log"  # a space in the path must survive
        cmd = logged_command(str(log), "for i in $(seq 1 30); do echo $i; done; exit 7")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        assert res.returncode == 7
        assert "exit code 7" in res.stderr
        assert res.stderr.rstrip().endswith("30")
        assert "\n10\n" not in res.stderr
        assert log.exists()
