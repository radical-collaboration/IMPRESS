import asyncio
from .utils.logger import ImpressLogger
from radical.asyncflow import WorkflowEngine
from .pipelines.impress_pipeline import ImpressBasePipeline

class ImpressManager:
    def __init__(self, execution_backend, use_colors=True):
        self.flow = WorkflowEngine(backend=execution_backend)
        self.pipeline_tasks = {}  # {pipeline: task}
        self.adaptive_tasks = {}  # {pipeline: adaptive_task}
        self.new_pipeline_buffer = []
        self.logger = ImpressLogger(use_colors=use_colors)

    def submit_new_pipelines(self, pipeline_setups):
        for setup in pipeline_setups:
            if not isinstance(setup['type'], type) or not issubclass(setup['type'], ImpressBasePipeline):
                raise ValueError(f"Expected an ImpressBasePipeline subclass, got {type(setup['type'])}")

            pipeline = setup['type'](name=setup['name'],
                                     flow=self.flow,
                                     **setup.get('config', {}))

            pipeline._adaptive_fn = setup.get('adaptive_fn')
            
            # Log pipeline creation
            self.logger.pipeline_started(pipeline.name)

            # invoke the pipeline execution but do not wait/block for it
            task = asyncio.create_task(pipeline.run())
            self.pipeline_tasks[pipeline] = task

    async def _run_adaptive_fn(self, pipeline):
        """Run adaptive function in background - pipeline will update its own submit_child_pipeline_request property"""
        try:
            self.logger.adaptive_started(pipeline.name)
            adaptive_fn = getattr(pipeline, '_adaptive_fn', None)
            if adaptive_fn:
                await adaptive_fn(pipeline)  # Adaptive function handles setting pipeline.submit_child_pipeline_request
                self.logger.adaptive_completed(pipeline.name)
        except Exception as e:
            self.logger.adaptive_failed(pipeline.name, str(e))
            # Let the pipeline handle the error, don't interfere with submit_child_pipeline_request
        finally:
            # Always clear the invoke flag and set the barrier
            pipeline.invoke_adaptive_step = False
            pipeline._adaptive_barrier.set()

    async def start(self, pipeline_setups: list):
        self.logger.separator("IMPRESS MANAGER STARTING")
        self.logger.manager_starting(len(pipeline_setups))
        
        self.submit_new_pipelines(pipeline_setups)

        while True:
            any_activity = False
            completed_pipelines = []

            for pipeline, pipeline_future in list(self.pipeline_tasks.items()):
                # Check if pipeline needs adaptive step and isn't already running one
                if (getattr(pipeline, 'invoke_adaptive_step', False) and 
                    pipeline not in self.adaptive_tasks):
                    
                    # Start adaptive function in background
                    adaptive_task = asyncio.create_task(self._run_adaptive_fn(pipeline))
                    self.adaptive_tasks[pipeline] = adaptive_task
                    any_activity = True

                # Check if pipeline has new config ready
                config = pipeline.get_child_pipeline_request()

                if config:
                    self.logger.child_pipeline_submitted(config['name'], pipeline.name)
                    self.new_pipeline_buffer.append(config)
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
                            # Pipeline is done but adaptive task is still running
                            # Don't mark as completed yet, just continue to next iteration
                            continue

                    # Pipeline is done and either no adaptive task or adaptive task is also done
                    completed_pipelines.append(pipeline)

            # Clean up completed pipelines - but only if their adaptive tasks are also done
            actually_completed = []
            for pipeline in completed_pipelines:
                # Double-check: only clean up if adaptive task is done or doesn't exist
                if pipeline in self.adaptive_tasks:
                    adaptive_task = self.adaptive_tasks[pipeline]
                    if not adaptive_task.done():
                        # Adaptive task still running, don't clean up yet
                        continue
                    # Adaptive task is done, clean it up
                    self.adaptive_tasks.pop(pipeline)
                
                # Safe to clean up pipeline now
                self.pipeline_tasks.pop(pipeline, None)
                self.logger.pipeline_completed(pipeline.name)
                actually_completed.append(pipeline)

            # Update completed_pipelines to only include actually completed ones
            completed_pipelines = actually_completed

            # Clean up completed adaptive tasks
            completed_adaptive = []
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
