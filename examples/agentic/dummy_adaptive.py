import asyncio
import random
from typing import Dict, Any

from impress import PipelineSetup
from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager
from impress import llm_agent, provide_llm_context 

from concurrent.futures import ThreadPoolExecutor
from radical.asyncflow import ConcurrentExecutionBackend

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)

class PipelineContextDummy(BaseModel):
    previous_score: float
    current_score: float
    generation: int

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
    
    def finalize():
        pass


async def adaptive_criteria(current_score: float, previous_score: float, pipeline: DummyProteinPipeline) -> bool:
    """
    Determine if protein quality has degraded requiring pipeline migration.
    
    Uses AI agent for decision-making.
    
    Args:
        current_score: Current protein structure quality score
        previous_score: Previous protein structure quality score
        pipeline: Complete pipeline object 
        
    Returns:
        True if quality has degraded, False otherwise
    """
    score_change = current_score - previous_score
    percent_change = (score_change / previous_score * 100) if previous_score != 0 else 0
    
    if percent_change > 2:
        trend = "improving"
    elif percent_change < -2:
        trend = "degrading"
    else:
        trend = "stable"
    
    context = PipelineContextDummy(
        previous_score=previous_score,
        current_score=current_score,
        generation=pipeline.generation,
    )
    
    llm_context = provide_llm_context(pipeline_context=context)
    llm_response = await llm_agent.prompt(message=llm_context)

    return llm_response.parsed_response.spawn_new_pipeline

async def adaptive_decision(pipeline: DummyProteinPipeline) -> None:
    if pipeline.generation >= pipeline.max_generations:
        return

    current_score = random.random()
    previous_score = random.random()

    spawn_new_pipeline = await adaptive_criteria(current_score, previous_score, pipeline)
    if not spawn_new_pipeline:
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

    logger.debug(f"AGENTIC RESULTS: \
        pipelines approved: {llm_agent.pipelines_aproved} \
        pipelines rejected: {llm_agent.pipelines_rejected}")



if __name__ == "__main__":
    asyncio.run(run())
