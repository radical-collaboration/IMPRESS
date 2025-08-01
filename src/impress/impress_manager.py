import asyncio

from radical.asyncflow import WorkflowEngine

from typing import Dict, List, Any, Optional, Callable, Awaitable, Union
from .utils.logger import ImpressLogger
from .pipelines.setup import PipelineSetup
from .pipelines.impress_pipeline import ImpressBasePipeline


class ImpressManager:
    """
    Manages the execution of multiple pipelines with adaptive optimization.
    
    Coordinates pipeline lifecycle, adaptive function execution, and child pipeline
    creation in an asynchronous environment.
    """
    
    def __init__(self, execution_backend: Any, use_colors: bool = True) -> None:
        """
        Initialize the ImpressManager.
        
        Args:
            execution_backend: Backend for workflow execution
            use_colors: Whether to use colors in logging output
        """
        self.execution_backend: Any = execution_backend
        self.pipeline_tasks: Dict[ImpressBasePipeline, asyncio.Task] = {}
        self.adaptive_tasks: Dict[ImpressBasePipeline, asyncio.Task] = {}
        self.new_pipeline_buffer: List[PipelineSetup] = []
        self.logger: ImpressLogger = ImpressLogger(use_colors=use_colors)

    def _normalize_pipeline_setup(self, setup: Union[Dict[str, Any], PipelineSetup]) -> PipelineSetup:
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

    def submit_new_pipelines(self, pipeline_setups: List[Union[Dict[str, Any], PipelineSetup]]) -> None:
        """
        Submit new pipelines for execution.
        
        Args:
            pipeline_setups: List of pipeline configuration dictionaries or PipelineSetup objects
            
        Raises:
            ValueError: If pipeline type is not a subclass of ImpressBasePipeline
        """
        for setup_input in pipeline_setups:
            # Normalize to PipelineSetup object
            setup = self._normalize_pipeline_setup(setup_input)
            
            # Create pipeline instance with config and kwargs merged
            pipeline_kwargs = {**setup.config, **setup.kwargs}
            pipeline: ImpressBasePipeline = setup.type(
                name=setup.name,
                flow=self.flow,
                **pipeline_kwargs
            )

            pipeline._adaptive_fn = setup.adaptive_fn

            self.logger.pipeline_started(pipeline.name)

            task: asyncio.Task = asyncio.create_task(pipeline.run())
            self.pipeline_tasks[pipeline] = task

    async def _run_adaptive_fn(self, pipeline: ImpressBasePipeline) -> None:
        """
        Run adaptive function for a pipeline in the background.
        
        The adaptive function updates the pipeline's submit_child_pipeline_request property.
        
        Args:
            pipeline: Pipeline to run adaptive function for
        """
        try:
            self.logger.adaptive_started(pipeline.name)
            adaptive_fn: Optional[Callable[[ImpressBasePipeline], Awaitable[None]]] = getattr(
                pipeline, '_adaptive_fn', None
            )
            if adaptive_fn:
                await adaptive_fn(pipeline)
                self.logger.adaptive_completed(pipeline.name)
        except Exception as e:
            self.logger.adaptive_failed(pipeline.name, str(e))
        finally:
            pipeline.invoke_adaptive_step = False
            pipeline._adaptive_barrier.set()

    async def start(self, pipeline_setups: List[Union[Dict[str, Any], PipelineSetup]]) -> None:
        """
        Start the pipeline manager and execute all pipelines.

        Manages the complete lifecycle of pipelines including:
        - Initial pipeline submission
        - Adaptive function execution
        - Child pipeline creation
        - Pipeline completion and cleanup

        Args:
            pipeline_setups: List of initial pipeline configurations (dicts or PipelineSetup objects)
        """
        self.logger.separator("IMPRESS MANAGER STARTING")

        self.flow: WorkflowEngine = await WorkflowEngine.create(backend=self.execution_backend)

        self.logger.manager_starting(len(pipeline_setups))

        self.submit_new_pipelines(pipeline_setups)

        while True:
            any_activity: bool = False
            completed_pipelines: List[ImpressBasePipeline] = []

            for pipeline, pipeline_future in list(self.pipeline_tasks.items()):
                # Check if pipeline needs adaptive step and isn't already running one
                if (getattr(pipeline, 'invoke_adaptive_step', False) and 
                    pipeline not in self.adaptive_tasks):
                    
                    adaptive_task: asyncio.Task = asyncio.create_task(
                        self._run_adaptive_fn(pipeline)
                    )
                    self.adaptive_tasks[pipeline] = adaptive_task
                    any_activity = True

                # Check if pipeline has new config ready
                config: Optional[Dict[str, Any]] = pipeline.get_child_pipeline_request()

                if config:
                    self.logger.child_pipeline_submitted(config['name'], pipeline.name)
                    # Convert dict to PipelineSetup for consistency
                    child_setup = PipelineSetup.from_dict(config)
                    self.new_pipeline_buffer.append(child_setup)
                    any_activity = True

                # Check if parent should be killed
                if getattr(pipeline, 'kill_parent', False):
                    self.logger.pipeline_killed(pipeline.name)
                    pipeline_future.cancel()
                    completed_pipelines.append(pipeline)
                    continue

                # Check if pipeline is done - but only mark as completed if adaptive task is also done
                if pipeline_future.done():
                    # If there's an adaptive task running, don't mark as completed yet
                    if pipeline in self.adaptive_tasks:
                        adaptive_task = self.adaptive_tasks[pipeline]
                        if not adaptive_task.done():
                            continue

                    completed_pipelines.append(pipeline)

            # Clean up completed pipelines - but only if their adaptive tasks are also done
            actually_completed: List[ImpressBasePipeline] = []
            for pipeline in completed_pipelines:
                # Double-check: only clean up if adaptive task is done or doesn't exist
                if pipeline in self.adaptive_tasks:
                    adaptive_task = self.adaptive_tasks[pipeline]
                    if not adaptive_task.done():
                        continue
                    self.adaptive_tasks.pop(pipeline)

                self.pipeline_tasks.pop(pipeline, None)
                self.logger.pipeline_completed(pipeline.name)
                actually_completed.append(pipeline)

            completed_pipelines = actually_completed

            # Clean up completed adaptive tasks
            completed_adaptive: List[ImpressBasePipeline] = []
            for pipeline, adaptive_task in list(self.adaptive_tasks.items()):
                if adaptive_task.done():
                    completed_adaptive.append(pipeline)

            for pipeline in completed_adaptive:
                self.adaptive_tasks.pop(pipeline, None)

            # Submit new pipelines
            if self.new_pipeline_buffer:
                self.submit_new_pipelines(self.new_pipeline_buffer)
                self.new_pipeline_buffer.clear()
                any_activity = True

            # Log activity summary periodically
            if any_activity:
                self.logger.activity_summary(
                    len(self.pipeline_tasks), 
                    len(self.adaptive_tasks), 
                    len(self.new_pipeline_buffer)
                )

            # Exit condition
            if not self.pipeline_tasks and not self.new_pipeline_buffer and not self.adaptive_tasks:
                self.logger.manager_exiting()
                self.logger.separator("IMPRESS MANAGER FINISHED")
                break

            if not any_activity:
                await asyncio.sleep(0.5)
