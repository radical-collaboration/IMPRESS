import asyncio
from unittest.mock import patch

import pytest

from .test_manager_core import MockPipeline
from .test_manager_life_cycle import MockWorkflowEngine


class TestChildPipelines:
    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_start_with_child_pipeline(self, impress_manager):
        """Test starting with pipeline that creates child pipeline"""

        # Create a pipeline that submits a child pipeline
        class ParentMockPipeline(MockPipeline):
            async def run(self):
                self._run_called = True
                # Submit child pipeline request
                self._child_pipeline_request = {
                    "name": "child_pipeline",
                    "type": MockPipeline,
                    "config": {},
                    "kwargs": {},
                }
                await asyncio.sleep(0.1)
                return "completed"

        pipeline_setup = {
            "name": "parent_pipeline",
            "type": ParentMockPipeline,
            "config": {},
            "kwargs": {},
        }

        # Run the manager
        await impress_manager.start([pipeline_setup])

        # Verify both pipelines completed successfully
        assert len(impress_manager.pipeline_tasks) == 0
        assert len(impress_manager.new_pipeline_buffer) == 0

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_simple_child_pipeline_creation(self, impress_manager):
        """Test a simple case of one parent creating one child pipeline"""
        completed_pipelines = []

        class SimpleParentPipeline(MockPipeline):
            async def run(self):
                self._run_called = True
                nonlocal completed_pipelines
                completed_pipelines.append(f"parent_{self.name}")

                # Create exactly one child
                self._child_pipeline_request = {
                    "name": "simple_child",
                    "type": SimpleChildPipeline,
                    "config": {},
                    "kwargs": {},
                }
                await asyncio.sleep(0.05)
                return "completed"

        class SimpleChildPipeline(MockPipeline):
            async def run(self):
                self._run_called = True
                nonlocal completed_pipelines
                completed_pipelines.append(f"child_{self.name}")
                # Child creates NO further children
                await asyncio.sleep(0.05)
                return "completed"

        pipeline_setup = {
            "name": "parent",
            "type": SimpleParentPipeline,
            "config": {},
            "kwargs": {},
        }

        # Run the manager with timeout
        try:
            await asyncio.wait_for(impress_manager.start([pipeline_setup]), timeout=3.0)
        except asyncio.TimeoutError:
            # Print debug info if it times out
            print(f"Completed pipelines: {completed_pipelines}")
            print(f"Pipeline tasks: {len(impress_manager.pipeline_tasks)}")
            print(f"Adaptive tasks: {len(impress_manager.adaptive_tasks)}")
            print(f"Buffer: {len(impress_manager.new_pipeline_buffer)}")
            pytest.fail("Simple child pipeline test timed out")

        # Verify exactly 2 pipelines completed: parent and child
        assert len(completed_pipelines) == 2
        assert "parent_parent" in completed_pipelines
        assert "child_simple_child" in completed_pipelines
        assert len(impress_manager.pipeline_tasks) == 0

    def test_get_child_pipeline_request_clears_after_retrieval(self):
        """Test that child pipeline requests are cleared after being retrieved"""
        pipeline = MockPipeline("test_pipeline")

        # Set up a child pipeline request
        child_config = {
            "name": "child_pipeline",
            "type": MockPipeline,
            "config": {},
            "kwargs": {},
        }
        pipeline._child_pipeline_request = child_config

        # First retrieval should return the config
        result1 = pipeline.get_child_pipeline_request()
        assert result1 == child_config

        # Second retrieval should return None (cleared)
        result2 = pipeline.get_child_pipeline_request()
        assert result2 is None
