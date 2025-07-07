# Initialize manager
import copy
import asyncio
import random
from typing import Dict, Any, Optional

from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager
from radical.asyncflow import ThreadExecutionBackend


class DummyProteinPipeline(ImpressBasePipeline):

    def __init__(self, name, flow, configs={}, **kwargs):
        self.iter_seqs = 'MKFLVLACGT'
        self.generation = configs.get('generation', 1)
        self.parent_name = configs.get('parent_name', 'root')
        self.max_generations = configs.get('max_generations', 3)

        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self):

        @self.auto_register_task()
        async def sequence_analysis(*args, **kwargs):
            return f"/bin/echo '[{self.name}] Gen-{self.generation}: Analyzing {len(self.iter_seqs)} protein sequences' && /bin/date"

        @self.auto_register_task()
        async def fitness_evaluation(*args, **kwargs):
            return f"/bin/echo '[{self.name}] Gen-{self.generation}: Evaluating fitness scores' && /bin/date"

        @self.auto_register_task()
        async def optimization_step(*args, **kwargs):
            return f"/bin/echo '[{self.name}] Gen-{self.generation}: Running optimization algorithms' && /bin/date"

    async def run(self):
        print(f"\n🧬 [{self.name}] Starting Generation {self.generation} (Parent: {self.parent_name})")
        
        # Step 1: Sequence Analysis
        analysis_res = await self.sequence_analysis()
        print(f'[{self.name}] {analysis_res}')
        
        # Step 2: Fitness Evaluation
        fitness_res = await self.fitness_evaluation()
        print(f'[{self.name}] {fitness_res}')
        
        # Decision point: Should we create new pipelines?
        # This will ask the manager to invoke the adaptive function
        # The adaptive function will update self.submit_child_pipeline_request if a new pipeline should be created
        await self.trigger_and_wait_adaptive()

        # Step 3: Final optimization
        opt_res = await self.optimization_step()
        print(f'[{self.name}] {opt_res}')
        
        print(f"✅ [{self.name}] Pipeline completed")


async def run_dummy_pipelines():

    async def adaptive_optimization_strategy(pipeline: DummyProteinPipeline):
        """
        A dummy 50% chance strategy with generation limit
        Now updates pipeline.submit_child_pipeline_request instead of returning a value
        """

        print(f"📊 [{pipeline.name}] Gen-{pipeline.generation} deciding...")

        # Don't exceed generation limit
        if pipeline.generation >= pipeline.max_generations:
            print(f"🛑 [{pipeline.name}] Max generations reached")
            return  # Don't set submit_child_pipeline_request, so no new pipeline will be created

        # Simple 50% chance to create new pipeline
        if random.random() < 0.5:
            new_name = f"{pipeline.name}_g{pipeline.generation + 1}"

            new_pipe_config = {
                'name': new_name,
                'type': type(pipeline),
                'config': {
                    'generation': pipeline.generation + 1,
                    'parent_name': pipeline.name,
                    'max_generations': pipeline.max_generations,
                },
                'adaptive_fn': adaptive_optimization_strategy
            }

            print(f"🚀 [{pipeline.name}] Creating new pipeline: {new_name}")

            # Update pipeline's submit_child_pipeline_request property
            pipeline.submit_child_pipeline_request(new_pipe_config)
        else:
            print(f"⏸️  [{pipeline.name}] Skipping pipeline creation")
            # Don't set submit_child_pipeline_request, so no new pipeline will be created


    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    await manager.start(pipeline_setups=[{'name': 'p1', 'config': {}, 
                                          'type': DummyProteinPipeline,
                                          'adaptive_fn': adaptive_optimization_strategy}])

if __name__ == "__main__":
    asyncio.run(run_dummy_pipelines())
