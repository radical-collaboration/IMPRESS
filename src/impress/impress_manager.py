import typeguard

from radical.flow import WorkflowEngine
## from .impress_pipeline import BasePipeline

class ImpressManager:
    def __init__(self, execution_backend) -> None:
        self.active_pipelines = []
        self.asyncflow = WorkflowEngine(backend = execution_backend)

    async def start(self, pipeline_setups: list):

        # we will start the async loop sometime
        submitted_pipelines = self.submit_new_pipeline(pipeline_setups)
        futures = self.run_concurrent_pipelines()

        return futures

    def submit_new_pipeline(self, pipeline_setups):
        new_pipelines = []
        for p in pipeline_setups:
            new_pipelines.append(p['type'](name=p['name'],
                                           config=p['config'],
                                           flow=self.asyncflow))

        self.active_pipelines.extend(new_pipelines)

        return new_pipelines

    async def run_concurrent_pipelines(self):
        """Run multiple pipelines concurrently"""
        results = await asyncio.gather(*[pipe.run() for pipe in self.active_pipelines])
