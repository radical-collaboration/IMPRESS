import asyncio
from unittest.mock import patch

import pytest

from impress import PipelineSetup

from .test_manager_core import MockPipeline


class MockWorkflowEngine:
    """Mock workflow engine"""

    @classmethod
    async def create(cls, backend=None):
        return cls()


class TestManagerLifecycle:
    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_start_simple_pipeline(self, impress_manager):
        """Test starting with a simple pipeline that completes"""
        pipeline_setup = {
            "name": "test_pipeline",
            "type": MockPipeline,
            "config": {},
            "kwargs": {},
        }

        # Run the manager
        await impress_manager.start([pipeline_setup])

        # Verify manager completed successfully (no exceptions)
        assert len(impress_manager.pipeline_tasks) == 0
        assert len(impress_manager.adaptive_tasks) == 0
        assert len(impress_manager.new_pipeline_buffer) == 0

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_start_multiple_pipelines(self, impress_manager):
        """Test starting with multiple pipelines"""
        pipeline_setups = [
            {"name": "pipeline_1", "type": MockPipeline, "config": {}, "kwargs": {}},
            {"name": "pipeline_2", "type": MockPipeline, "config": {}, "kwargs": {}},
        ]

        # Run the manager
        await impress_manager.start(pipeline_setups)

        # Verify all pipelines completed
        assert len(impress_manager.pipeline_tasks) == 0
        assert len(impress_manager.adaptive_tasks) == 0

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_start_with_kill_parent(self, impress_manager):
        """Test starting with pipeline that kills itself"""

        # Create a pipeline that kills itself
        class SuicidalMockPipeline(MockPipeline):
            async def run(self):
                self._run_called = True
                self.kill_parent = True
                await asyncio.sleep(1)  # This should be cancelled
                return "completed"

        pipeline_setup = {
            "name": "suicidal_pipeline",
            "type": SuicidalMockPipeline,
            "config": {},
            "kwargs": {},
        }

        # Run the manager
        await impress_manager.start([pipeline_setup])

        # Verify manager completed (pipeline was killed)
        assert len(impress_manager.pipeline_tasks) == 0

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_pipeline_with_long_adaptive_task(self, impress_manager):
        """Test pipeline completion waits for adaptive task to finish"""

        # Create a slow adaptive function
        async def slow_adaptive_fn(pipeline):
            await asyncio.sleep(0.2)

        # Create a fast pipeline with slow adaptive function
        class FastPipelineSlowAdaptive(MockPipeline):
            def __init__(self, name: str, flow=None, **kwargs):
                super().__init__(name, flow, **kwargs)
                self._adaptive_barrier = asyncio.Event()

            async def run(self):
                self._run_called = True
                self.invoke_adaptive_step = True
                await asyncio.sleep(0.05)  # Finish quickly
                return "completed"

        pipeline_setup = PipelineSetup(
            name="fast_pipeline",
            type=FastPipelineSlowAdaptive,
            config={},
            kwargs={},
            adaptive_fn=slow_adaptive_fn,
        )

        start_time = asyncio.get_event_loop().time()
        await impress_manager.start([pipeline_setup])
        end_time = asyncio.get_event_loop().time()

        # Should take at least 0.15 seconds due to slow adaptive function
        assert end_time - start_time >= 0.15
