
from PipelineAgent import PipelineAgent

class ProteinBindingPipelineAgent(PipelineAgent):
    def __init__(self, name, configs=None, **kwargs):
        # Execution metadata
        if configs is None:
            configs = {}
        self.name = name
        self.pipeline_id: int = kwargs.get("pipeline_id")
        self.base_path = kwargs.get("base_path", os.getcwd())
        self.input_path = os.path.join(self.base_path, f"{self.name}_in")
        self.input_structure: str = kwargs.get("input_structure")
        self.task_list = ['START',]
        self.scores_list = {}
    
    def run(self):
        pipeline_agent = create_agent(
            model=chatmodel,
            system_prompt=PIPELINE_AGENT_PROMPT,
            tools=[get_input_backbone, call_mpnn_runner_agent, call_alphafold_runner_agent,
                call_mpnn_scoring_agent, call_alphafold_scoring_agent],
            #    context_schema=Context,
            #    checkpointer=checkpointer
            )

