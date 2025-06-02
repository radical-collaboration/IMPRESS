from impress import ImpressManager
from impress import ImpressBasePipeline

class ProteinBindingPipeline(ImpressBasePipeline):
    def __init__(self, name, flow, step_id=None, configs={}, **kwargs):

        self.flow = flow
        self.configs = configs
        self.current_scores = {}
        self.step_id = kwargs.get('step_id', 1)
        self.previous_scores = kwargs.get('previous_score', {})

        super().__init__(name, **configs)

    @self.flow.executable_task
    @staticmethod
    async def s1(*args, **kwargs):
        return "s1"

    @self.flow.executable_task
    @staticmethod
    async def s2(*args, **kwargs):
        return "s2"

    @self.flow.executable_task
    @staticmethod
    async def s3(*args, **kwargs):
        return "s3"

    async get_scores(self):
        return {'c_scores': self.current_scores,
                'p_scores': self.previous_scores}

    async def finalize(self):
        return

    async run(self):
        next_step = self.step_id + 1

        if next_step == 1:
            s1_result = await s1()
        elif next_step == 2:
            s2_result = await s2()
        elif next_step == 3:
            if self.iterations < 3:
                s1_result = await s1()
            else:
                s3_result = await s3()
        else:
            self.finalize()
