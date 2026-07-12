import asyncio
from unittest.mock import Mock, patch

import pytest

from impress import ImpressManager, PipelineSetup

from ..unit.telemetry_mocks import MockWorkflowEngineWithTelemetry
from ..unit.test_manager_core import MockPipeline


class TestTelemetryIntegration:
    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngineWithTelemetry)
    async def test_pipeline_run_wrapped_in_workflow_scope(self, mock_execution_backend):
        manager = ImpressManager(
            mock_execution_backend,
            use_colors=False,
            telemetry_config={"checkpoint_path": "./telemetry/"},
        )
        manager.logger = Mock()

        pipeline_setup = PipelineSetup(
            name="p1", type=MockPipeline, config={}, kwargs={}
        )
        await manager.start([pipeline_setup])

        assert manager.telemetry is not None
        assert manager.flow.workflow_scope_calls == ["p1"]

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngineWithTelemetry)
    async def test_child_pipeline_gets_own_scope(self, mock_execution_backend):
        manager = ImpressManager(
            mock_execution_backend,
            use_colors=False,
            telemetry_config={"checkpoint_path": "./telemetry/"},
        )
        manager.logger = Mock()

        class ParentMockPipeline(MockPipeline):
            async def run(self):
                self._run_called = True
                self._child_pipeline_request = {
                    "name": "child_pipeline",
                    "type": MockPipeline,
                    "config": {},
                    "kwargs": {},
                }
                await asyncio.sleep(0.05)
                return "completed"

        pipeline_setup = {
            "name": "parent_pipeline",
            "type": ParentMockPipeline,
            "config": {},
            "kwargs": {},
        }

        await manager.start([pipeline_setup])

        assert sorted(manager.flow.workflow_scope_calls) == [
            "child_pipeline",
            "parent_pipeline",
        ]

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngineWithTelemetry)
    async def test_no_workflow_scope_when_telemetry_not_configured(
        self, mock_execution_backend
    ):
        manager = ImpressManager(mock_execution_backend, use_colors=False)
        manager.logger = Mock()

        pipeline_setup = {
            "name": "p1",
            "type": MockPipeline,
            "config": {},
            "kwargs": {},
        }
        await manager.start([pipeline_setup])

        assert manager.telemetry is None
        assert manager.flow.workflow_scope_calls == []
