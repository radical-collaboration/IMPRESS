import asyncio

from ..impress_manager import ImpressManager
from .impress_pipeline import ImpressBasePipeline

class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, step_id=None, configs={}, **kwargs):

        self.name = name
        self.flow = flow
        self.configs = configs
        self.kill_parent = False
        self.current_scores = {}

        self.step_id = kwargs.get('step_id', 1)
        self.sub_order = kwargs.get('sub_order', 0)
        self.iter_seqs = kwargs.get('iter_seqs', {})
        self.previous_scores = kwargs.get('previous_score', {})

        super().__init__(name, **configs)

        self.register_pipeline_tasks()

    def set_adaptive_flag(self, value: bool = True):
        self.invoke_adaptive_step = value
        if value:
            self._adaptive_barrier.clear()

    async def await_adaptive_unlock(self) -> any:
        """Pause until manager completes adaptive step and returns result."""

        print(f"[{self.name}] Waiting on adaptive barrier...")
        await self._adaptive_barrier.wait()
        print(f"[{self.name}] Resumed after adaptive step.")

    def get_current_config_for_next_pipeline(self):

        # Return a dict like those passed to `submit_new_pipelines`
        return {"name": "adaptively_generate_pipeline",
                "type": ProteinBindingPipeline}

    def register_pipeline_tasks(self):

        @self.flow.executable_task
        async def s1(*args, **kwargs):
            return "/bin/echo I am S1 executed at && /bin/date"
        self.s1 = s1

        @self.flow.executable_task
        async def s2(*args, **kwargs):
            return "/bin/echo I am S2 executed at && /bin/date"
        self.s2 = s2

        @self.flow.executable_task
        async def s3(*args, **kwargs):
            return "/bin/echo I am S3 executed at && /bin/date"
        self.s3 = s3

        @self.flow.executable_task
        async def s4(*args, **kwargs):
            return "/bin/echo I am S4 executed at && /bin/date"
        self.s4 = s4

        @self.flow.executable_task
        async def s5(*args, **kwargs):
            return "/bin/echo I am S5 executed at && /bin/date"
        self.s5 = s5

    async def get_scores_map(self):
        return {'c_scores': self.current_scores,
                'p_scores': self.previous_scores}

    async def finalize(self):
        return

    async def run(self):
        next_step = self.step_id + 1
        s1_res = await self.s1()
        s2_res = await self.s2()

        print(f'From pipeline: {self.name}: {s1_res}')
        print(f'From pipeline: {self.name}: {s2_res}')

        if s2_res:
            self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
            self.current_scores = {f"protein_{i}": i * 10 + self.step_id for i in range(1, 4)}
            self.previous_scores = {f"protein_{i}": i * 10 + self.sub_order for i in range(1, 4)}
            
            self.set_adaptive_flag(True)
            await self.await_adaptive_unlock()

        s3_res = await self.s3()
        s4_res = await self.s4()
        s5_res = await self.s5()

        print(f'From pipeline: {self.name}: {s3_res}')
        print(f'From pipeline: {self.name}: {s4_res}')
        print(f'From pipeline: {self.name}: {s5_res}')
