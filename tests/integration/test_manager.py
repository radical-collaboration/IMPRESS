import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from impress import PipelineSetup

from ..unit.test_manager_core import (
    MockPipeline,
)
from ..unit.test_manager_life_cycle import MockWorkflowEngine


class TestIntegration:
    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_start_with_adaptive_function(self, impress_manager):
        """Test starting with pipeline that has adaptive function"""
        adaptive_fn = AsyncMock()

        # Create a custom pipeline that triggers adaptive step
        class AdaptiveMockPipeline(MockPipeline):
            def __init__(self, name: str, flow=None, **kwargs):
                super().__init__(name, flow, **kwargs)
                self._adaptive_barrier = asyncio.Event()

            async def run(self):
                self._run_called = True
                self.invoke_adaptive_step = True
                await asyncio.sleep(0.1)
                # Wait for adaptive barrier to be set
                await self._adaptive_barrier.wait()
                return "completed"
            
            async def finalize(self):
                return True

        pipeline_setup = PipelineSetup(
            name="adaptive_pipeline",
            type=AdaptiveMockPipeline,
            config={},
            kwargs={},
            adaptive_fn=adaptive_fn,
        )

        # Run the manager
        await impress_manager.start([pipeline_setup])

        # Check that adaptive function was called
        adaptive_fn.assert_called_once()

    @pytest.mark.asyncio
    @patch("impress.impress_manager.WorkflowEngine", MockWorkflowEngine)
    async def test_complex_pipeline_workflow(self, impress_manager):
        """Test complex workflow with adaptive functions and child pipelines"""
        adaptive_calls = []

        async def tracking_adaptive_fn(pipeline):
            adaptive_calls.append(pipeline.name)
            await asyncio.sleep(0.05)

        class ComplexPipeline(MockPipeline):
            def __init__(self, name: str, flow=None, create_child=False, **kwargs):
                super().__init__(name, flow, **kwargs)
                self._adaptive_barrier = asyncio.Event()
                self.create_child = create_child

            async def run(self):
                self._run_called = True
                self.invoke_adaptive_step = True

                # Create child if requested
                if self.create_child:
                    self._child_pipeline_request = {
                        "name": f"{self.name}_child",
                        "type": ComplexPipeline,
                        "config": {},
                        "kwargs": {"create_child": False},
                    }

                await asyncio.sleep(0.1)
                await self._adaptive_barrier.wait()
                return "completed"

            async def finalize(self):
                return True

        pipeline_setup = PipelineSetup(
            name="complex_parent",
            type=ComplexPipeline,
            config={},
            kwargs={"create_child": True},
            adaptive_fn=tracking_adaptive_fn,
        )

        # Run the manager
        await impress_manager.start([pipeline_setup])

        # Verify adaptive function was called for parent
        assert "complex_parent" in adaptive_calls
        assert len(impress_manager.pipeline_tasks) == 0
        assert len(impress_manager.adaptive_tasks) == 0
