import asyncio
from radical.asyncflow import WorkflowEngine

class ImpressManager:
    def __init__(self, execution_backend) -> None:
        self.flow = WorkflowEngine(backend=execution_backend)
        self.active_pipelines = []

    def submit_new_pipelines(self, pipeline_setups):
        """Submit new pipelines and add to active list."""
        new_pipelines = []
        for p in pipeline_setups:
            pipeline = p['type'](name=p['name'], flow=self.flow, **p.get('config', {}))
            adaptive_fn = p.get('adaptive_fn')
            pipeline._adaptive_fn = adaptive_fn  # Store it in pipeline for later use
            self.active_pipelines.append(pipeline)
            new_pipelines.append(pipeline)
        return new_pipelines

    async def run_pipeline(self, pipeline):
        """Run a single pipeline and return its result and reference."""
        await pipeline.run()
        return pipeline

    async def start(self, pipeline_setups: list):
        self.submit_new_pipelines(pipeline_setups)

        while True:
            if not self.active_pipelines:
                print("No active pipelines. Sleeping...")
                await asyncio.sleep(1)
                continue

            futures = [self.run_pipeline(p) for p in self.active_pipelines]
            finished = await asyncio.gather(*futures)
            self.active_pipelines = []

            new_pipelines = []
            for pipeline in finished:
                adaptive_fn = getattr(pipeline, '_adaptive_fn', None)
                if adaptive_fn:
                    new_pipe_config = await adaptive_fn(pipeline)
                    if new_pipe_config:
                        print(f"Submitting new pipeline: {new_pipe_config['name']} originating from {pipeline.name}")
                        new_pipelines.append(new_pipe_config)

            if not new_pipelines:
                print("No new pipelines to submit. Exiting.")
                break

            self.submit_new_pipelines(new_pipelines)
