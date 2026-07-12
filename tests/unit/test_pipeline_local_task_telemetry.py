import types
from unittest.mock import Mock

import pytest

from impress import ImpressBasePipeline
from impress.utils import telemetry as telemetry_module


def _fake_make_event(event_cls, **fields):
    return types.SimpleNamespace(event_type=event_cls, **fields)


@pytest.fixture(autouse=True)
def _fake_telemetry_events(monkeypatch):
    """Force the LocalTask* event-emission path to run deterministically,
    independent of whether the optional `rhapsody` package is installed."""
    monkeypatch.setattr(telemetry_module, "_TELEMETRY_EVENTS_AVAILABLE", True)
    monkeypatch.setattr(
        telemetry_module, "LocalTaskStarted", "impress.LocalTaskStarted"
    )
    monkeypatch.setattr(
        telemetry_module, "LocalTaskCompleted", "impress.LocalTaskCompleted"
    )
    monkeypatch.setattr(telemetry_module, "LocalTaskFailed", "impress.LocalTaskFailed")
    monkeypatch.setattr(telemetry_module, "make_event", _fake_make_event)


class _LocalTaskPipeline(ImpressBasePipeline):
    """Minimal concrete pipeline exercising auto_register_task(local_task=True)."""

    def register_pipeline_tasks(self):
        @self.auto_register_task(local_task=True)
        async def greet(name):
            return f"hello {name}"

        @self.auto_register_task(local_task=True)
        async def boom():
            raise ValueError("kaboom")

        @self.auto_register_task()
        async def hpc_step():
            return "echo hi"

    async def run(self):
        pass

    async def finalize(self):
        pass


@pytest.fixture
def pipeline_with_telemetry():
    telemetry = Mock()
    telemetry.session_id = "sess-1"
    flow = Mock()
    return _LocalTaskPipeline(name="p1", flow=flow, telemetry=telemetry), telemetry


@pytest.fixture
def pipeline_without_telemetry():
    flow = Mock()
    return _LocalTaskPipeline(name="p1", flow=flow, telemetry=None)


class TestLocalTaskTelemetry:
    @pytest.mark.asyncio
    async def test_success_emits_started_then_completed(self, pipeline_with_telemetry):
        pipeline, telemetry = pipeline_with_telemetry

        result = await pipeline.greet("world")

        assert result == "hello world"
        assert telemetry.emit.call_count == 2
        started_event, completed_event = (
            call.args[0] for call in telemetry.emit.call_args_list
        )
        assert started_event.event_type == "impress.LocalTaskStarted"
        assert completed_event.event_type == "impress.LocalTaskCompleted"
        assert started_event.task_name == "greet"
        assert completed_event.pipeline_name == "p1"

    @pytest.mark.asyncio
    async def test_failure_emits_failed_and_reraises(self, pipeline_with_telemetry):
        pipeline, telemetry = pipeline_with_telemetry

        with pytest.raises(ValueError, match="kaboom"):
            await pipeline.boom()

        assert telemetry.emit.call_count == 2  # started + failed
        failed_event = telemetry.emit.call_args_list[-1].args[0]
        assert failed_event.event_type == "impress.LocalTaskFailed"
        assert failed_event.error == "kaboom"
        assert failed_event.task_name == "boom"

    @pytest.mark.asyncio
    async def test_runs_without_telemetry_configured(self, pipeline_without_telemetry):
        result = await pipeline_without_telemetry.greet("world")

        assert result == "hello world"

    def test_non_local_task_still_routed_through_flow(self, pipeline_with_telemetry):
        pipeline, _telemetry = pipeline_with_telemetry

        # auto_register_task(local_task=False) must still go through
        # self.flow.executable_task(...), unaffected by the local-task wrapper.
        pipeline.flow.executable_task.assert_called_once()
