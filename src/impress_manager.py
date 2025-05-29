import typeguard

from radical.flow import WorkflowEngine
from .impress_pipeline import BasePipeline

class ImpressManager:
    def __init__(self, execution_backend: RadicalExecutionBackend) -> None:
        self.active_pipelines = []
        self.asyncflow = WorkflowEngine(backend = execution_backend)

    def start(self, pipeline: BasePipeline, config: dict):
        self.active_pipelines.append(pipeline)
        return pipeline

    def submit_new_pipeline(self, pipeline: BasePipeline, config: dict):
        new_pipeline = pipeline.__class__(config)
        self.active_pipes.append(new_pipeline)
        return new_pipeline

    async def run_pipeline(self, pipeline):
        pass

    async def run_concurrent_pipelines(self, count=2):
        """Run multiple pipelines concurrently"""
        pipelines = [self.create_pipeline(name) for name in self.pipeline_names[:count]]
        results = await asyncio.gather(*[self.run_pipeline(pipe) for pipe in pipelines])

