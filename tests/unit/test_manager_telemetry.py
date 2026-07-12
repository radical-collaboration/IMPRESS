from unittest.mock import Mock, patch

import pytest

from impress import ImpressManager

from .telemetry_mocks import MockWorkflowEngineWithTelemetry
from .test_manager_core import MockPipeline


class TestManagerTelemetryConfig:
    def test_defaults_to_empty_config_and_subscribers(self, mock_execution_backend):
        manager = ImpressManager(mock_execution_backend)

        assert manager._telemetry_config == {}
        assert manager._telemetry_subscribers == []
        assert manager.telemetry is None

    def test_stores_given_config_and_subscribers(self, mock_execution_backend):
        subscriber = Mock()
        config = {"checkpoint_path": "./telemetry/", "resource_poll_interval": 5.0}

        manager = ImpressManager(
            mock_execution_backend,
            telemetry_config=config,
            telemetry_subscribers=[subscriber],
        )

        assert manager._telemetry_config == config
        assert manager._telemetry_subscribers == [subscriber]


class TestManagerTelemetryStart:
    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngineWithTelemetry)
    async def test_start_telemetry_called_when_config_given(
        self, mock_execution_backend
    ):
        subscriber = Mock()
        manager = ImpressManager(
            mock_execution_backend,
            use_colors=False,
            telemetry_config={"checkpoint_path": "./telemetry/"},
            telemetry_subscribers=[subscriber],
        )

        pipeline_setup = {
            "name": "p1",
            "type": MockPipeline,
            "config": {},
            "kwargs": {},
        }
        await manager.start([pipeline_setup])

        assert manager.telemetry is not None
        assert subscriber in manager.telemetry.subscribers

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngineWithTelemetry)
    async def test_start_telemetry_not_called_when_config_empty(
        self, mock_execution_backend
    ):
        manager = ImpressManager(mock_execution_backend, use_colors=False)

        pipeline_setup = {
            "name": "p1",
            "type": MockPipeline,
            "config": {},
            "kwargs": {},
        }
        await manager.start([pipeline_setup])

        assert manager.telemetry is None


class TestSubmitNewPipelinesTelemetry:
    @patch("impress.impress_manager.asyncio.create_task")
    def test_submit_new_pipelines_passes_telemetry_kwarg(
        self, mock_create_task, impress_manager
    ):
        impress_manager.flow = Mock()
        impress_manager.telemetry = Mock(name="telemetry-handle")
        mock_create_task.return_value = Mock()

        captured = {}

        class CapturingPipeline(MockPipeline):
            def __init__(self, name, flow=None, telemetry=None, **kwargs):
                captured["telemetry"] = telemetry
                super().__init__(name, flow, **kwargs)

        pipeline_setup = {
            "name": "p1",
            "type": CapturingPipeline,
            "config": {},
            "kwargs": {},
        }
        impress_manager.submit_new_pipelines([pipeline_setup])

        assert captured["telemetry"] is impress_manager.telemetry
