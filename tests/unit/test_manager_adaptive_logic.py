import asyncio
import threading
import time
from unittest.mock import AsyncMock, Mock

import pytest

from impress import ImpressManager

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


class LocalBackendFlow:
    """Engine stand-in with a backend named "local".

    function_task runs the coroutine function in a worker thread, as
    rhapsody's thread-pool ConcurrentExecutionBackend does.
    """

    def __init__(self):
        self._backends = {"local": object()}
        self.registered = []
        self.calls = []

    def function_task(self, backend=None):
        def decorator(func):
            self.registered.append((func.__name__, backend))

            def flow_task(*args, **kwargs):
                self.calls.append(kwargs)
                return asyncio.ensure_future(
                    asyncio.to_thread(asyncio.run, func(*args))
                )

            flow_task.__task_description__ = {}
            return flow_task

        return decorator


def _adaptive_pipeline(name="p1", fn=None):
    pipeline = MockPipeline(name)
    pipeline._adaptive_fn = fn
    pipeline.invoke_adaptive_step = True
    pipeline._adaptive_barrier = asyncio.Event()
    return pipeline


class TestAdaptiveOffload:
    async def test_blocking_callback_does_not_stall_the_loop(self, impress_manager):
        def blocking(pipeline):
            time.sleep(0.5)  # stands in for blocking file I/O

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        tick_task = asyncio.create_task(ticker())
        await impress_manager._run_adaptive_fn(_adaptive_pipeline(fn=blocking))
        tick_task.cancel()
        assert ticks > 10

    async def test_async_callback_without_awaits_runs_off_loop(self, impress_manager):
        seen = {}

        async def no_awaits(pipeline):
            seen["thread"] = threading.get_ident()

        await impress_manager._run_adaptive_fn(_adaptive_pipeline(fn=no_awaits))
        assert seen["thread"] != threading.get_ident()

    async def test_sync_callback_result_applied_to_live_pipeline(
        self, impress_manager
    ):
        def decide(pipeline):
            pipeline.next_step = 3

        pipeline = _adaptive_pipeline(fn=decide)
        await impress_manager._run_adaptive_fn(pipeline)
        assert pipeline.next_step == 3
        assert pipeline._adaptive_barrier.is_set()

    async def test_offload_disabled_runs_on_loop(self, mock_flow):
        manager = ImpressManager(mock_flow, use_colors=False, adaptive_offload=False)
        manager.logger = Mock()
        seen = {}

        async def on_loop(pipeline):
            seen["thread"] = threading.get_ident()

        await manager._run_adaptive_fn(_adaptive_pipeline(fn=on_loop))
        assert seen["thread"] == threading.get_ident()

    async def test_uses_local_backend_when_present(self):
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()
        calls = []

        def adaptive_decision(pipeline):
            calls.append(pipeline.name)

        for name in ("p1", "p2"):
            await manager._run_adaptive_fn(_adaptive_pipeline(name, adaptive_decision))

        assert calls == ["p1", "p2"]
        # Registered once, labelled after the callback, routed to "local".
        assert flow.registered == [("adaptive_decision", "local")]
        assert [c["workflow_id"] for c in flow.calls] == ["p1:adaptive", "p2:adaptive"]

    async def test_flow_task_passed_through(self):
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()
        calls = []

        async def already_a_task(pipeline):
            calls.append(pipeline.name)

        task = flow.function_task(backend="local")(already_a_task)
        flow.registered.clear()
        await manager._run_adaptive_fn(_adaptive_pipeline(fn=task))
        assert calls == ["p1"]
        assert flow.registered == []  # not wrapped a second time

    async def test_offloaded_exception_still_releases_barrier(self, impress_manager):
        def raises(pipeline):
            raise ValueError("bad decision")

        pipeline = _adaptive_pipeline(fn=raises)
        await impress_manager._run_adaptive_fn(pipeline)
        impress_manager.logger.adaptive_failed.assert_called_once()
        assert pipeline._adaptive_barrier.is_set()
