
from agnostic_agent import LLMAgent

from pydantic import BaseModel, Field


class Schema(BaseModel):
      spawn_new_pipeline: bool 

class PipelineContext(BaseModel):
      previous_score: float = Field(description="The score from the previous generation/iteration")
      current_score: float = Field(description="The score from the current generation/iteration")
      generation: int = Field(description="The current generation number in the optimization process")

SYSTEM_PROMPT = f"""
You are an AI assistant designed to make decisions for a protein optimization pipeline. 
Your task is to determine whether to spawn a new child pipeline based on the provided context. 
A new pipeline should only be created if it is likely to lead to further improvements, and the maximum generation limit has not been reached.

Based on these values make a decision if you should proceed with the current pipeline or not: {PipelineContext.model_json_schema()}

"""

llm_agent = LLMAgent(
      llm_backend="openrouter",
      agent_name="PipelineReviewer",
      model_name="google/gemini-2.5-flash",
      sys_instructions=SYSTEM_PROMPT,
      response_schema=Schema
)

def provide_llm_context(pipeline_context: PipelineContext) -> dict:
      pipeline_field_values = pipeline_context.model_dump_json()

      llm_context = f"""
      This is the context of the current pipeline: {pipeline_field_values}
      """
      return llm_context

