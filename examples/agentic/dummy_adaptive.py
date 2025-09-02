import asyncio
import random
from typing import Dict, Any, List
import copy
import json

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager
from impress.utils.agentic import llm_agent, adaptive_criteria

from concurrent.futures import ThreadPoolExecutor
from radical.asyncflow import ConcurrentExecutionBackend

import logging

from impress.utils.agentic.agent import pipelines_decisions

logger = logging.getLogger(__name__)

class DummyProteinPipeline(ImpressBasePipeline):
    def __init__(self, name: str, flow: Any, configs: Dict[str, Any] = {}, **kwargs):
        self.iter_seqs: str = 'MKFLVLACGT'
        self.generation: int = configs.get('generation', 1)
        self.parent_name: str = configs.get('parent_name', 'root')
        self.max_generations: int = configs.get('max_generations', 3)
        self.score_history: List[float] = configs.get('score_history', [])
        super().__init__(name, flow, **configs, **kwargs)

    # Aliases to mirror real pipeline attributes expected by adaptive_criteria
    @property
    def passes(self) -> int:
        return self.generation

    @property
    def max_passes(self) -> int:
        return self.max_generations

    @property
    def sub_order(self) -> int:
        return max(0, self.generation - 1)

    @property
    def seq_rank(self) -> int:
        return 0

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
        # Loop until the maximum number of generations is reached
        while self.passes <= self.max_passes:
            self.logger.pipeline_log(f'Starting Generation {self.generation} '
                                     f'for pipeline {self.name}')

            # --- Run the tasks for the current generation ---
            self.logger.pipeline_log('Seq started')
            await self.sequence_analysis()
            self.logger.pipeline_log('Seq finished')

            self.logger.pipeline_log('Fit started')
            await self.fitness_evaluation()
            self.logger.pipeline_log('Fit finished')

            # --- Make the adaptive decision ---
            # This will now be called for generations 2 and 3
            await self.run_adaptive_step(wait=True)

            self.logger.pipeline_log('Optimization started')
            await self.optimization_step()
            self.logger.pipeline_log('Optimization finished')

            self.logger.pipeline_log(f'--- Generation {self.generation} Complete ---')

            # --- Manually advance to the next generation ---
            self.generation += 1

        self.logger.pipeline_log('Max generations reached. Finalizing.')
    
    def finalize(self):
        pass


async def adaptive_decision(pipeline: DummyProteinPipeline) -> None:
    if pipeline.generation > pipeline.max_generations:
        return

    current_score = random.random()

    pipeline.score_history.append(current_score)

    if pipeline.generation < 2:
        pipeline.logger.pipeline_log('Not enough data for adaptive decision, continuing.')
        return

    spawn_new_pipeline = await adaptive_criteria(pipeline.name, pipeline.score_history, pipeline)
    if not spawn_new_pipeline:
        return 

    if pipeline.generation < pipeline.max_generations:
        new_name = f"{pipeline.name}_g{pipeline.generation + 1}"
        new_config = {
            'name': new_name,
            'type': type(pipeline),
            'config': {
                'generation': pipeline.generation + 1,
                'parent_name': pipeline.name,
                'max_generations': pipeline.max_generations,
                "score_history": copy.deepcopy(pipeline.score_history)
            },
            'adaptive_fn': adaptive_decision
        }
        pipeline.submit_child_pipeline_request(new_config)


async def run() -> None:
    execution_backend = await ConcurrentExecutionBackend(ThreadPoolExecutor())
    manager: ImpressManager = ImpressManager(execution_backend)

    pipeline_setups = [PipelineSetup(name=f'p{i}',
                                     type=DummyProteinPipeline,
                                     adaptive_fn=adaptive_decision)  for i in range(1, 4)]

    await manager.start(pipeline_setups=pipeline_setups)

    log_filename = "agent_decisions.log"
    with open(log_filename, "w") as f:
        json.dump(pipelines_decisions, f, indent=4)

    logger.debug(f"AGENTIC RESULTS: \
        pipelines approved: {llm_agent.pipelines_aproved} \
        pipelines rejected: {llm_agent.pipelines_rejected}\
        -----------\
        APPROVDED PIPELINES OVERVIEW (length: {len(pipelines_decisions)}):\
        {pipelines_decisions}")



if __name__ == "__main__":
    asyncio.run(run())



