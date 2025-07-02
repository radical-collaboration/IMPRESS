import copy
import asyncio
import random

from radical.asyncflow import ThreadExecutionBackend

from impress import ImpressBasePipeline
from impress.impress_manager import ImpressManager


class DummyProteinPipeline(ImpressBasePipeline):

    def __init__(self, name, flow, configs={}, **kwargs):
        self.flow = flow
        self.iter_seqs = None
        self.current_scores = None
        self.previous_scores = None

        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
        self.current_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}
        self.previous_scores = {f"protein_{i}": i * 10 for i in range(1, 4)}

        super().__init__(name, flow, **configs, **kwargs)

    def register_pipeline_tasks(self):

        @self.auto_register_task()
        async def s1(*args, **kwargs):
            return "/bin/echo I am S1 executed at && /bin/date"

        @self.auto_register_task()
        async def s2(*args, **kwargs):
            return "/bin/echo I am S2 executed at && /bin/date"

        @self.auto_register_task()
        async def s3(*args, **kwargs):
            return "/bin/echo I am S3 executed at && /bin/date"

    async def run(self):

        s1_res = await self.s1()
        s2_res = await self.s2()

        print(f'[{self.name}] {s1_res}')
        print(f'[{self.name}] {s2_res}')

        # this will ask the manager to invoke the adaptive
        # while respecting execution flow of the pipeline stages

        s3_res = await self.s3()

        print(f'[{self.name}] {s3_res}')


async def run_dummy_pipelines():

    manager = ImpressManager(execution_backend=ThreadExecutionBackend({}))

    await manager.start(pipeline_setups=[{'name': 'p1', 'config': {}, 
                                          'type': DummyProteinPipeline},
                                         {'name': 'p2', 'config': {}, 
                                          'type': DummyProteinPipeline},
                                         {'name': 'p3', 'config': {},
                                          'type': DummyProteinPipeline}])

asyncio.run(run_dummy_pipelines())