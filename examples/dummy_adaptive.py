import asyncio
import random
from typing import Dict, Any

from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager
from radical.asyncflow import ThreadExecutionBackend


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
        await self.sequence_analysis()
        await self.fitness_evaluation()
        await self.run_adaptive_step(wait=True)
        await self.optimization_step()


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
    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    pipeline_setups = [
        {
            'name': f'p{i}',
            'config': {},
            'type': DummyProteinPipeline,
            'adaptive_fn': adaptive_optimization_strategy
        }
        for i in range(1, 4)
    ]

    await manager.start(pipeline_setups=pipeline_setups)


if __name__ == "__main__":
    asyncio.run(run())
