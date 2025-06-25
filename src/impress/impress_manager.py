import asyncio
from radical.asyncflow import WorkflowEngine
from .pipelines.impress_pipeline import ImpressBasePipeline

class ImpressManager:
    def __init__(self, execution_backend):
        self.flow = WorkflowEngine(backend=execution_backend)
        self.pipeline_tasks = {}  # {pipeline: task}
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

    async def start(self, pipeline_setups: list):
        
        self.submit_new_pipelines(pipeline_setups)

        while True:
            any_activity = False

            for pipeline, task in list(self.pipeline_tasks.items()):
                if getattr(pipeline, 'invoke_adaptive_step', False):
                    adaptive_fn = getattr(pipeline, '_adaptive_fn', None)
                    if adaptive_fn:
                        print(f"Checking adaptive function for {pipeline.name}")
                        config = await adaptive_fn(pipeline)

                        pipeline.invoke_adaptive_step = False
                        pipeline._adaptive_barrier.set()  # unblock pipeline execution

                        if config:
                            config['adaptive_fn'] = adaptive_fn
                            print(f"Submitting new pipeline: {config['name']} from {pipeline.name}")
                            self.new_pipeline_buffer.append(config)
                            any_activity = True

                # If the task is done, remove it
                if task.done():
                    self.pipeline_tasks.pop(pipeline)

            if self.new_pipeline_buffer:
                self.submit_new_pipelines(self.new_pipeline_buffer)
                self.new_pipeline_buffer.clear()
                any_activity = True

            if not self.pipeline_tasks and not self.new_pipeline_buffer:
                print("All pipelines finished. Exiting.")
                break

            if not any_activity:
                await asyncio.sleep(0.5)
