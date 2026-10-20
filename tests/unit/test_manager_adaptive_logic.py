import asyncio
import threading
import time
from unittest.mock import AsyncMock, Mock

import pytest

from impress import ImpressManager, PipelineSetup

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

        # Called with the live pipeline, labelled for telemetry
        adaptive_fn.assert_called_once_with(
            pipeline, workflow_id="test_pipeline:adaptive"
        )

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
        adaptive_fn.assert_called_once_with(
            pipeline, workflow_id="test_pipeline:adaptive"
        )

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


class TestAdaptiveRouting:
    """The caller declares the backend; the manager only awaits the task.

    There is one execution path, so these cover the task being awaited and
    labelled, and anything that is not a task being rejected up front.
    """

    async def test_declared_task_is_awaited_and_labelled(self):
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()
        calls = []

        async def adaptive_decision(pipeline):
            calls.append(pipeline.name)

        task = flow.function_task(backend="local")(adaptive_decision)
        for name in ("p1", "p2"):
            await manager._run_adaptive_fn(_adaptive_pipeline(name, task))

        assert calls == ["p1", "p2"]
        # Declared once by the caller; the manager never registers it again.
        assert flow.registered == [("adaptive_decision", "local")]
        assert [c["workflow_id"] for c in flow.calls] == ["p1:adaptive", "p2:adaptive"]

    async def test_declared_task_runs_off_the_loop(self):
        """The engine owns execution, so a body with no awaits cannot stall it."""
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()
        seen = {}

        async def no_awaits(pipeline):
            seen["thread"] = threading.get_ident()
            time.sleep(0.3)  # stands in for blocking file I/O

        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = flow.function_task(backend="local")(no_awaits)
        tick_task = asyncio.create_task(ticker())
        await manager._run_adaptive_fn(_adaptive_pipeline(fn=task))
        tick_task.cancel()

        assert seen["thread"] != threading.get_ident()
        assert ticks > 10

    async def test_mutations_reach_the_live_pipeline(self):
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()

        async def decide(pipeline):
            pipeline.next_step = 3

        pipeline = _adaptive_pipeline(fn=flow.function_task(backend="local")(decide))
        await manager._run_adaptive_fn(pipeline)
        assert pipeline.next_step == 3
        assert pipeline._adaptive_barrier.is_set()

    @pytest.mark.parametrize(
        "fn, kind",
        [
            (lambda pipeline: None, "callable"),
            (AsyncMock(), "callable"),
        ],
        ids=["sync-def", "async-mock"],
    )
    async def test_undeclared_adaptive_fn_rejected_before_any_pipeline(
        self, mock_flow, fn, kind
    ):
        manager = ImpressManager(mock_flow, use_colors=False)
        manager.logger = Mock()
        setup = PipelineSetup(name="p1", type=MockPipeline, adaptive_fn=fn)

        with pytest.raises(TypeError, match=r"p1'.*not an engine task"):
            manager.submit_new_pipelines([setup])

        # Nothing started: the whole batch is checked first.
        assert manager.pipeline_tasks == {}

    async def test_bare_coroutine_function_names_its_kind(self, mock_flow):
        manager = ImpressManager(mock_flow, use_colors=False)
        manager.logger = Mock()

        async def not_a_task(pipeline):
            pass

        setup = PipelineSetup(name="p1", type=MockPipeline, adaptive_fn=not_a_task)
        with pytest.raises(TypeError, match="plain coroutine function"):
            manager.submit_new_pipelines([setup])

    async def test_no_adaptive_fn_is_allowed(self, mock_flow):
        manager = ImpressManager(mock_flow, use_colors=False)
        manager.logger = Mock()
        manager._check_adaptive_fns(
            [PipelineSetup(name="p1", type=MockPipeline, adaptive_fn=None)]
        )

    async def test_exception_still_releases_barrier(self):
        flow = LocalBackendFlow()
        manager = ImpressManager(flow, use_colors=False)
        manager.logger = Mock()

        async def raises(pipeline):
            raise ValueError("bad decision")

        pipeline = _adaptive_pipeline(fn=flow.function_task(backend="local")(raises))
        await manager._run_adaptive_fn(pipeline)
        manager.logger.adaptive_failed.assert_called_once()
        assert pipeline._adaptive_barrier.is_set()
