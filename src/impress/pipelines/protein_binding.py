from impress import ImpressManager
from impress import ImpressBasePipeline

class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, step_id=None, configs={}, **kwargs):

        self.name = name
        self.flow = flow
        self.configs = configs
        self.current_scores = {}
        self.step_id = kwargs.get('step_id', 1)
        self.sub_order = kwargs.get('sub_order', 0)
        self.iter_seqs = kwargs.get('iter_seqs', {})
        self.previous_scores = kwargs.get('previous_score', {})

        super().__init__(name, **configs)

        self.register_pipeline_tasks()
    
    def should_continue(self, result):
        return True

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

    async def get_scores_map(self):
        return {'c_scores': self.current_scores,
                'p_scores': self.previous_scores}

    async def finalize(self):
        return

    async def run(self):
        next_step = self.step_id + 1
        s1_res = await self.s1()
        s2_res = await self.s2()
        s3_res = await self.s3()

        print(f'From pipeline: {self.name}: I am {s1_res}')
        print(f'From pipeline: {self.name}: I am {s2_res}')
        print(f'From pipeline: {self.name}: I am {s3_res}')

        self.current_scores = {f"protein_{i}": i * 10 + self.step_id for i in range(1, 4)}
        self.previous_scores = {f"protein_{i}": i * 10 + self.sub_order for i in range(1, 4)}
        self.iter_seqs = {f"protein_{i}": f"sequence_{i}" for i in range(1, 4)}
