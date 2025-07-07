import asyncio
from radical.asyncflow import WorkflowEngine
from .pipelines.impress_pipeline import ImpressBasePipeline

class ImpressManager:
    def __init__(self, execution_backend):
        self.flow = WorkflowEngine(backend=execution_backend)
        self.pipeline_tasks = {}  # {pipeline: task}
        self.adaptive_tasks = {}  # {pipeline: adaptive_task}
        self.new_pipeline_buffer = []

    def submit_new_pipelines(self, pipeline_setups):
        for setup in pipeline_setups:

            if not isinstance(setup['type'], type) or not issubclass(setup['type'], ImpressBasePipeline):
                raise ValueError(f"Expected an ImpressBasePipeline subclass, got {type(setup['type'])}")

            pipeline = setup['type'](name=setup['name'],
                                     flow=self.flow,
                                     **setup.get('config', {}))

            pipeline._adaptive_fn = setup.get('adaptive_fn')

            # invoke the pipeline execution but do not wait/block for it
            task = asyncio.create_task(pipeline.run())
            self.pipeline_tasks[pipeline] = task

    async def _run_adaptive_fn(self, pipeline):
        """Run adaptive function in background - pipeline will update its own submit_child_pipeline_request property"""
        try:
            adaptive_fn = getattr(pipeline, '_adaptive_fn', None)
            if adaptive_fn:
                await adaptive_fn(pipeline)  # Adaptive function handles setting pipeline.submit_child_pipeline_request
                print(f"IMPRESS-Manager: Adaptive function completed for {pipeline.name}")
        except Exception as e:
            print(f'IMPRESS-Manager: Adaptive stage failed for {pipeline.name} with: {e}')
            # Let the pipeline handle the error, don't interfere with submit_child_pipeline_request
        finally:
            # Always clear the invoke flag and set the barrier
            pipeline.invoke_adaptive_step = False
            pipeline._adaptive_barrier.set()

    async def start(self, pipeline_setups: list):
        
        self.submit_new_pipelines(pipeline_setups)

        while True:
            any_activity = False
            completed_pipelines = []

            for pipeline, task in list(self.pipeline_tasks.items()):
                # Check if task is done first to avoid unnecessary work
                if task.done():
                    completed_pipelines.append(pipeline)
                    continue

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
                    print(f"IMPRESS-Manager: Submitting new pipeline: {config['name']} from {pipeline.name}")
                    self.new_pipeline_buffer.append(config)
                    any_activity = True

                # Check if parent should be killed
                if getattr(pipeline, 'kill_parent', False):
                    print(f'IMPRESS-Manager: Killing {pipeline.name} pipeline')
                    task.cancel()
                    completed_pipelines.append(pipeline)

            # Clean up completed pipelines and their adaptive tasks
            for pipeline in completed_pipelines:
                self.pipeline_tasks.pop(pipeline, None)
                # Cancel and remove any running adaptive task
                if pipeline in self.adaptive_tasks:
                    adaptive_task = self.adaptive_tasks.pop(pipeline)
                    if not adaptive_task.done():
                        adaptive_task.cancel()

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

            # Exit condition
            if not self.pipeline_tasks and not self.new_pipeline_buffer and not self.adaptive_tasks:
                print("IMPRESS-Manager: All pipelines finished. Exiting.")
                break

            if not any_activity:
                await asyncio.sleep(0.5)
