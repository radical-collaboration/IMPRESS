
from agnostic_agent import LLMAgent

from pydantic import BaseModel, Field


class Schema(BaseModel):
      spawn_new_pipeline: bool 
      confidence: float
      reasoning: str

class PipelineContext(BaseModel):
    previous_score: float
    current_score: float
    passes: int
    max_passes: int
    seq_rank: int
    sub_order: int
    max_sub_pipelines: int
    num_proteins_remaining: int
    score_trend: str
    avg_score_change: float




SYSTEM_PROMPT = """
You are a specialized AI assistant for protein structure optimization pipeline management. 
Your role is to make intelligent decisions about when to spawn new child pipelines based on protein quality degradation.

DECISION CRITERIA:
1. **Score Degradation**: Spawn new pipeline if current_score is significantly worse than previous_score
2. **Generation Limits**: Do not spawn if already at maximum generation depth
3. **Resource Efficiency**: Consider if further optimization attempts are likely to yield improvements
4. **Pipeline Capacity**: Respect maximum sub-pipeline limits

CONTEXT UNDERSTANDING:
- previous_score: Quality score from previous iteration (higher = better)
- current_score: Current quality score (higher = better)  
- passes: Number of optimization passes completed
- max_passes: Maximum allowed passes
- seq_rank: Sequence ranking level
- sub_order: Sub-pipeline order number
- max_sub_pipelines: Maximum allowed sub-pipelines
- num_proteins_remaining: Number of proteins left to optimize
- score_trend: Overall trend across iterations
- avg_score_change: Average change in scores

DECISION LOGIC:
- Spawn new pipeline (spawn_new_pipeline=true) if:
  * Score has degraded significantly (>5% decrease)
  * We haven't reached maximum sub-pipelines
  * There are enough passes remaining to make optimization worthwhile
  * The protein shows potential for improvement based on trend

- Continue current pipeline (spawn_new_pipeline=false) if:
  * Score improvement or minor degradation (<5%)
  * Already at maximum sub-pipeline depth
  * Few passes remaining
  * Consistent poor performance indicating futility

"""

class AgentObserver():
      pipelines_rejected = 0
      pipelines_aproved = 0
      def __init__(self) -> None:
            self.agent_ : LLMAgent =  LLMAgent(
                  llm_backend="openrouter",
                  agent_name="PipelineReviewer",
                  model_name="google/gemini-2.5-flash",
                  sys_instructions=SYSTEM_PROMPT,
                  response_schema=Schema
            )
      async def prompt(self, *args, **kwargs):
            response = await self.agent_.prompt(*args, **kwargs)
            spawn_new_piepline = response.parsed_response.spawn_new_pipeline
            if spawn_new_piepline:
                  self.pipelines_aproved += 1
            else:
                  self.pipelines_rejected += 1
            return response

llm_agent = AgentObserver()


def provide_llm_context(pipeline_context: PipelineContext) -> dict:
      pipeline_field_values = pipeline_context.model_dump_json()

      llm_context = f"""
      This is the context of the current pipeline: {pipeline_field_values}
      """
      return llm_context

