from impress import ImpressManager
from impress import ImpressBasePipeline

class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, step_id=None, configs={}, **kwargs):

        self.name = name
        self.flow = flow
        self.configs = configs
        self.current_scores = {}
        self.step_id = kwargs.get('step_id', 1)
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
            return "/bin/echo I am S1"
        self.s1 = s1

        @self.flow.executable_task
        async def s2(*args, **kwargs):
            return "/bin/echo I am S2"
        self.s2 = s2

        @self.flow.executable_task
        async def s3(*args, **kwargs):
            return "/bin/echo I am S3"
        self.s3 = s3

    async def get_scores(self):
        return {'c_scores': self.current_scores,
                'p_scores': self.previous_scores}

    async def finalize(self):
        return

    async def run(self):
        next_step = self.step_id + 1

        print(f'Next Step ID: {next_step}')

        if next_step == 1:
            print(f'Executing S1 of {self.name}')
            s1_result = await self.s1()
            print(s1_result)
        elif next_step == 2:
            print(f'Executing S2 of {self.name}')
            s2_result = await self.s2()
            print(s2_result)
        elif next_step == 3:
            if self.iterations < 3:
                print(f'Executing S1 of {self.name}')
                s1_result = await self.s1()
                print(s1_result)
            else:
                print(f'Executing S3 of {self.name}')
                s3_result = await self.s3()
                print(s3_result)
        else:
            print(f'Finalizing pipeline {self.name}')
            self.finalize()
