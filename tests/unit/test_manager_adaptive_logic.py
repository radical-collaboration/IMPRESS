import asyncio
from unittest.mock import AsyncMock

import pytest

from .test_manager_core import MockPipeline


class TestAdaptiveFunctions:
    @pytest.mark.asyncio
    async def test_run_adaptive_fn_success(self, impress_manager):
        """Test successful adaptive function execution"""
        # Create a mock adaptive function
        adaptive_fn = AsyncMock()

        # Create a mock pipeline
        pipeline = MockPipeline("test_pipeline")
        pipeline._adaptive_fn = adaptive_fn
        pipeline.invoke_adaptive_step = True
        pipeline._adaptive_barrier = asyncio.Event()

        await impress_manager._run_adaptive_fn(pipeline)

        # Check that adaptive function was called
        adaptive_fn.assert_called_once_with(pipeline)

        # Check that flags were reset
        assert pipeline.invoke_adaptive_step is False
        assert pipeline._adaptive_barrier.is_set()

    @pytest.mark.asyncio
    async def test_run_adaptive_fn_no_function(self, impress_manager):
        """Test adaptive function execution with no adaptive function"""
        # Create a mock pipeline without adaptive function
        pipeline = MockPipeline("test_pipeline")
        pipeline.invoke_adaptive_step = True
        pipeline._adaptive_barrier = asyncio.Event()

        await impress_manager._run_adaptive_fn(pipeline)

        # Check that flags were reset
        assert pipeline.invoke_adaptive_step is False
        assert pipeline._adaptive_barrier.is_set()

    @pytest.mark.asyncio
    async def test_run_adaptive_fn_exception(self, impress_manager):
        """Test adaptive function execution with exception"""
        # Create a mock adaptive function that raises exception
        adaptive_fn = AsyncMock(side_effect=Exception("Test error"))

        # Create a mock pipeline
        pipeline = MockPipeline("test_pipeline")
        pipeline._adaptive_fn = adaptive_fn
        pipeline.invoke_adaptive_step = True
        pipeline._adaptive_barrier = asyncio.Event()

        await impress_manager._run_adaptive_fn(pipeline)

        # Check that exception was handled
        adaptive_fn.assert_called_once_with(pipeline)

        # Check that flags were reset even after exception
        assert pipeline.invoke_adaptive_step is False
        assert pipeline._adaptive_barrier.is_set()
