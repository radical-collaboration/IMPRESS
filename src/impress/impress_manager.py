import asyncio
import os
import tempfile
from collections.abc import Awaitable
from typing import Any, Callable, Optional, Union

from radical.asyncflow import WorkflowEngine

from .pipelines.impress_pipeline import ImpressBasePipeline
from .pipelines.setup import PipelineSetup
from .utils.logger import ImpressLogger


class ImpressManager:
    """
    Manages the execution of multiple pipelines with adaptive optimization.

    Coordinates pipeline lifecycle, adaptive function execution, and child pipeline
    creation in an asynchronous environment.
    """

    def __init__(
        self,
        execution_backend: Any,
        use_colors: bool = True,
        telemetry_config: Optional[dict[str, Any]] = None,
        telemetry_subscribers: Optional[list[Callable]] = None,
    ) -> None:
        """
        Initialize the ImpressManager.

        Args:
            execution_backend: Backend for workflow execution
            use_colors: Whether to use colors in logging output
            telemetry_config: kwargs forwarded to flow.start_telemetry() (e.g.
                checkpoint_path, resource_poll_interval). Pass None to disable.
            telemetry_subscribers: Callables registered via telemetry.subscribe()
                immediately after telemetry starts.
        """
        self.execution_backend: Any = execution_backend
        self.pipeline_tasks: dict[ImpressBasePipeline, asyncio.Task] = {}
        self.adaptive_tasks: dict[ImpressBasePipeline, asyncio.Task] = {}
        self.new_pipeline_buffer: list[PipelineSetup] = []
        self.logger: ImpressLogger = ImpressLogger(use_colors=use_colors)
        self._telemetry_config: dict[str, Any] = telemetry_config or {}
        self._telemetry_subscribers: list[Callable] = telemetry_subscribers or []
        self.telemetry: Any = None
        self.flow: Optional[WorkflowEngine] = None

    def _normalize_pipeline_setup(
        self, setup: Union[dict[str, Any], PipelineSetup]
    ) -> PipelineSetup:
        """
        Normalize pipeline setup to PipelineSetup object.

        Args:
            setup: Either a dictionary or PipelineSetup object

        Returns:
            PipelineSetup object
        """
        if isinstance(setup, dict):
            return PipelineSetup.from_dict(setup)
        elif isinstance(setup, PipelineSetup):
            return setup
        else:
            raise ValueError(f"Expected dict or PipelineSetup, got {type(setup)}")

    def submit_new_pipelines(
        self, pipeline_setups: list[Union[dict[str, Any], PipelineSetup]]
    ) -> None:
        """
        Submit new pipelines for execution.

        Args:
            pipeline_setups: List of pipeline configuration
            dictionaries or PipelineSetup objects

        Raises:
            ValueError: If pipeline type is not a subclass
            of ImpressBasePipeline
        """
        if self.flow is None:
            raise RuntimeError(
                "ImpressManager.start() must be called before submit_new_pipelines()"
            )
        for setup_input in pipeline_setups:
            # Normalize to PipelineSetup object
            setup = self._normalize_pipeline_setup(setup_input)

            # Create pipeline instance with config and kwargs merged
            pipeline_kwargs = {**setup.config, **setup.kwargs}
            pipeline: ImpressBasePipeline = setup.type(
                name=setup.name, flow=self.flow, **pipeline_kwargs
            )

            pipeline._adaptive_fn = setup.adaptive_fn

            self.logger.pipeline_started(pipeline.name)

            task: asyncio.Task = asyncio.create_task(pipeline.run())
            self.pipeline_tasks[pipeline] = task

    async def _run_adaptive_fn(self, pipeline: ImpressBasePipeline) -> None:
        """
        Run adaptive function for a pipeline in the background.

        The adaptive function updates the pipeline's
        submit_child_pipeline_request property.

        Args:
            pipeline: Pipeline to run adaptive function for
        """
        try:
            self.logger.adaptive_started(pipeline.name)
            adaptive_fn: Optional[Callable[[ImpressBasePipeline], Awaitable[None]]] = (
                getattr(pipeline, "_adaptive_fn", None)
            )
            if adaptive_fn:
                await adaptive_fn(pipeline)
                self.logger.adaptive_completed(pipeline.name)
        except Exception as e:
            self.logger.adaptive_failed(pipeline.name, str(e))
        finally:
            pipeline.invoke_adaptive_step = False
            pipeline._adaptive_barrier.set()

    async def start(
        self, pipeline_setups: list[Union[dict[str, Any], PipelineSetup]]
    ) -> None:
        """
        Start the pipeline manager and execute all pipelines.

        Manages the complete lifecycle of pipelines including:
        - Initial pipeline submission
        - Adaptive function execution
        - Child pipeline creation
        - Pipeline completion and cleanup

        Args:
            pipeline_setups: List of initial pipeline
            configurations (dicts or PipelineSetup objects)
        """
        self.logger.separator("IMPRESS MANAGER STARTING")

        # Write asyncflow session dirs to /tmp (node-local, no quota) instead of
        # cwd on scratch, which exhausts inodes over many runs.
        _session_base = os.environ.get("IMPRESS_SESSION_DIR", tempfile.gettempdir())
        self.flow = await WorkflowEngine.create(
            backend=self.execution_backend,
            work_dir=_session_base,
        )

        try:
            if self._telemetry_config:
                self.telemetry = await self.flow.start_telemetry(
                    **self._telemetry_config
                )
                for fn in self._telemetry_subscribers:
                    self.telemetry.subscribe(fn)

            self.logger.manager_starting(len(pipeline_setups))

            self.submit_new_pipelines(pipeline_setups)

            while True:
                any_activity: bool = False
                completed_pipelines: list[tuple] = []

                for pipeline, pipeline_future in list(self.pipeline_tasks.items()):
                    # Check if pipeline needs adaptive step and isn't running one yet
                    if (
                        getattr(pipeline, "invoke_adaptive_step", False)
                        and pipeline not in self.adaptive_tasks
                    ):
                        adaptive_task: asyncio.Task = asyncio.create_task(
                            self._run_adaptive_fn(pipeline)
                        )
                        self.adaptive_tasks[pipeline] = adaptive_task
                        any_activity = True

                    # Check if pipeline has new config ready
                    config: Optional[dict[str, Any]] = (
                        pipeline.get_child_pipeline_request()
                    )

                    if config:
                        self.logger.child_pipeline_submitted(
                            config["name"], pipeline.name
                        )
                        # Convert dict to PipelineSetup for consistency
                        child_setup = PipelineSetup.from_dict(config)
                        self.new_pipeline_buffer.append(child_setup)
                        any_activity = True

                    # Check if parent should be killed
                    if getattr(pipeline, "kill_parent", False):
                        self.logger.pipeline_killed(pipeline.name)
                        pipeline_future.cancel()
                        completed_pipelines.append((pipeline, pipeline_future))
                        continue

                    # Check if pipeline is done - but only mark as completed
                    # if adaptive task is also done
                    if pipeline_future.done():
                        # Adaptive task still running — wait before marking completed
                        if pipeline in self.adaptive_tasks:
                            adaptive_task = self.adaptive_tasks[pipeline]
                            if not adaptive_task.done():
                                continue

                        completed_pipelines.append((pipeline, pipeline_future))

                # Clean up completed pipelines - but only if their
                # adaptive tasks are also done
                actually_completed: list[ImpressBasePipeline] = []
                for pipeline, future in completed_pipelines:
                    # Double-check: only clean up if adaptive task is
                    # done or doesn't exist
                    if pipeline in self.adaptive_tasks:
                        adaptive_task = self.adaptive_tasks[pipeline]
                        if not adaptive_task.done():
                            continue
                        self.adaptive_tasks.pop(pipeline)

                    self.pipeline_tasks.pop(pipeline, None)
                    exc = None
                    if future.done() and not future.cancelled():
                        try:
                            exc = future.exception()
                        except Exception:
                            pass
                    if exc is not None:
                        self.logger.pipeline_failed(pipeline.name, exc)
                    else:
                        self.logger.pipeline_completed(pipeline.name)
                    actually_completed.append(pipeline)

                completed_pipelines = actually_completed

                # Clean up completed adaptive tasks
                completed_adaptive: list[ImpressBasePipeline] = []
                for pipeline, adaptive_task in list(self.adaptive_tasks.items()):
                    if adaptive_task.done():
                        completed_adaptive.append(pipeline)

                for pipeline in completed_adaptive:
                    self.adaptive_tasks.pop(pipeline, None)

                # Submit new pipelines; capture count before clearing so
                # activity_summary reports the real number submitted.
                if self.new_pipeline_buffer:
                    buffered_count = len(self.new_pipeline_buffer)
                    self.submit_new_pipelines(self.new_pipeline_buffer)
                    self.new_pipeline_buffer.clear()
                    any_activity = True
                else:
                    buffered_count = 0

                # Log activity summary periodically
                if any_activity:
                    self.logger.activity_summary(
                        len(self.pipeline_tasks),
                        len(self.adaptive_tasks),
                        buffered_count,
                    )

                # Exit condition
                if (
                    not self.pipeline_tasks
                    and not self.new_pipeline_buffer
                    and not self.adaptive_tasks
                ):
                    self.logger.manager_exiting()
                    self.logger.separator("IMPRESS MANAGER FINISHED")
                    break

                if not any_activity:
                    await asyncio.sleep(0.5)
        finally:
            await self.flow.shutdown()
