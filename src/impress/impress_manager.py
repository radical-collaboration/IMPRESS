import asyncio
from radical.flow import WorkflowEngine

class ImpressManager:
    def __init__(self, execution_backend) -> None:
        self.flow = WorkflowEngine(backend=execution_backend)
        self.active_pipelines = []

    def submit_new_pipelines(self, pipeline_setups):
        """Submit new pipelines and add to active list."""
        new_pipelines = []
        for p in pipeline_setups:
            pipeline = p['type'](name=p['name'], flow=self.flow, **p.get('config', {}))
            self.active_pipelines.append(pipeline)
            new_pipelines.append(pipeline)
        return new_pipelines

    async def run_pipeline(self, pipeline):
        """Run a single pipeline and return its result and reference."""
        result = await pipeline.run()
        return (pipeline, result)

    async def start(self, pipeline_setups: list):
        """Main loop: run pipelines, collect results, and spawn more."""
        # Submit initial pipelines
        self.submit_new_pipelines(pipeline_setups)

        while True:
            # Wait for all current pipelines to finish
            if not self.active_pipelines:
                print("No active pipelines. Sleeping...")
                await asyncio.sleep(1)
                continue

            # Run all current pipelines concurrently
            futures = [self.run_pipeline(p) for p in self.active_pipelines]
            finished = await asyncio.gather(*futures)

            # Clear completed pipelines
            self.active_pipelines = []

            # Evaluate results and conditionally add more pipelines
            new_pipelines = []
            for pipeline, result in finished:
                # FIXME: this should be provided by user, i.e,
                # a logic that should if to continue or not.
                if pipeline.should_continue(result):
                    new_pipeline = pipeline.get_current_config_for_next_pipeline()
                    new_pipelines.append(new_pipeline)

            # If no new work is added, break or wait
            if not new_pipelines:
                print("No new pipelines to submit. Exiting.")
                break

            # Submit new pipelines
            self.submit_new_pipelines(new_pipelines)
