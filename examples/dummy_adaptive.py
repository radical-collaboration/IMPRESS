import asyncio
import random
from typing import Any

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress import ImpressManager

from concurrent.futures import ThreadPoolExecutor
from radical.asyncflow import LocalExecutionBackend, WorkflowEngine


class DummyProteinPipeline(ImpressBasePipeline):
    # ImpressManager spreads a setup's `config` dict into keyword arguments,
    # so the lineage fields arrive as keywords, not as one `configs` dict.
    def __init__(self, name: str, flow: Any, generation: int = 1,
                 parent_name: str = 'root', max_generations: int = 3, **kwargs):
        self.iter_seqs: str = 'MKFLVLACGT'
        self.generation: int = generation
        self.parent_name: str = parent_name
        self.max_generations: int = max_generations
        super().__init__(name, flow, **kwargs)

    def register_pipeline_tasks(self) -> None:
        @self.auto_register_task()
        async def sequence_analysis(*args, **kwargs) -> str:
            return f"/bin/echo 'Analyzing' && /bin/date"

        @self.auto_register_task()
        async def fitness_evaluation(*args, **kwargs) -> str:
            return f"/bin/echo 'Evaluating' && /bin/date"

        @self.auto_register_task()
        async def optimization_step(*args, **kwargs) -> str:
            return f"/bin/echo 'Optimizing' && /bin/date"

    async def run(self) -> None:

        self.logger.pipeline_log('Seq started')
        await self.sequence_analysis()
        self.logger.pipeline_log('Seq finished')

        self.logger.pipeline_log('Fit started')
        await self.fitness_evaluation()
        self.logger.pipeline_log('Fit finished')
        
        await self.run_adaptive_step(wait=True)
        
        self.logger.pipeline_log('Optimization started')
        await self.optimization_step()
        self.logger.pipeline_log('Optimization finished')

    async def finalize(self) -> None:
        pass


# Set in run(), once the engine exists.  A child pipeline inherits the same
# declared task as its parent: ImpressManager takes an engine task, not a bare
# function, so the raw coroutine below cannot be passed on directly.
adaptive_task = None


async def adaptive_optimization_strategy(pipeline: DummyProteinPipeline) -> None:
    if pipeline.generation >= pipeline.max_generations or random.random() >= 0.5:
        return

    new_name = f"{pipeline.name}_g{pipeline.generation + 1}"
    new_config = {
        'name': new_name,
        'type': type(pipeline),
        'config': {
            'generation': pipeline.generation + 1,
            'parent_name': pipeline.name,
            'max_generations': pipeline.max_generations,
        },
        'adaptive_fn': adaptive_task
    }
    pipeline.submit_child_pipeline_request(new_config)


async def run() -> None:
    global adaptive_task

    execution_backend = await LocalExecutionBackend(ThreadPoolExecutor())
    flow = await WorkflowEngine.create(backend=execution_backend)
    manager: ImpressManager = ImpressManager(flow)

    # The engine's only backend is a thread pool, so the callback is declared
    # on the default one.  It mutates the live pipeline, which is why it must
    # not be a process pool.
    adaptive_task = flow.function_task(adaptive_optimization_strategy)

    pipeline_setups = [PipelineSetup(
        name=f'p{i}',
        type=DummyProteinPipeline,
        adaptive_fn=adaptive_task)  for i in range(1, 4)]

    try:
        await manager.start(pipeline_setups=pipeline_setups)
    finally:
        await flow.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
