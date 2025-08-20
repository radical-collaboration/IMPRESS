import asyncio
import random
from typing import Dict, Any

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager

from concurrent.futures import ThreadPoolExecutor
from radical.asyncflow import ConcurrentExecutionBackend


class DummyProteinPipeline(ImpressBasePipeline):
    def __init__(self, name: str, flow: Any, configs: Dict[str, Any] = {}, **kwargs):
        self.iter_seqs: str = 'MKFLVLACGT'
        self.generation: int = configs.get('generation', 1)
        self.parent_name: str = configs.get('parent_name', 'root')
        self.max_generations: int = configs.get('max_generations', 3)
        super().__init__(name, flow, **configs, **kwargs)

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
        'adaptive_fn': adaptive_optimization_strategy
    }
    pipeline.submit_child_pipeline_request(new_config)


async def run() -> None:
    execution_backend = await ConcurrentExecutionBackend(ThreadPoolExecutor())
    manager: ImpressManager = ImpressManager(execution_backend)

    pipeline_setups = [PipelineSetup(name=f'p{i}',
                                     type=DummyProteinPipeline,
                                     adaptive_fn=adaptive_optimization_strategy)  for i in range(1, 4)]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(run())
