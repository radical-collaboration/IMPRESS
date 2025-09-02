
from pty import spawn
from agnostic_agent import LLMAgent
from .utils import SYSTEM_PROMPT, calculate_volatility, calculate_trend

from pydantic import BaseModel, Field
from typing import List, Dict

import logging 

logger = logging.getLogger(__name__)

class Schema(BaseModel):
      spawn_new_pipeline: bool 
      confidence: float
      reasoning: str

class AgentObserver():
      pipelines_rejected = 0
      pipelines_aproved = 0
      def __init__(self) -> None:
            self.agent_ : LLMAgent =  LLMAgent(
                  llm_backend="openrouter",
                  agent_name="PipelineReviewer",
                  model_name="google/gemini-2.5-pro",
                  sys_instructions=SYSTEM_PROMPT,
                  response_schema=Schema
            )
      async def prompt(self, *args, **kwargs):
            response = await self.agent_.prompt(*args, **kwargs)
            spawn_new_pipeline = response.parsed_response.spawn_new_pipeline
            if spawn_new_pipeline:
                  self.pipelines_aproved += 1
            else:
                  self.pipelines_rejected += 1
            return response

llm_agent = AgentObserver()
pipelines_decisions: Dict[str, Dict[str, str]] = {} 

async def adaptive_criteria(protein_name:str, score_history: List[float], pipeline) -> bool:
    """
    Determine if protein quality has degraded, requiring pipeline migration.
    
    Uses an AI agent with historical analysis tools for decision-making.
    
    Args:
        protein_name: The name of the protein being evaluated.
        score_history: A list of all scores for this protein from previous passes.
        pipeline: The complete parent pipeline object.
        
    Returns:
        True if a new pipeline should be spawned, False otherwise.
    """

    trend = calculate_trend(score_history)
    volatility = calculate_volatility(score_history)


    context = {
        "protein_name": protein_name,
        "score_history": score_history,
        "scores_trend": trend,
        "scores_volatility": volatility,
        "current_pass": pipeline.passes,
        "max_passes": pipeline.max_passes,
        "current_sub_pipeline_order": pipeline.sub_order,
        "max_sub_pipelines": 3, # Hardcoded value
        "current_sequence_rank": pipeline.seq_rank
    }
    
    llm_message = f"Evaluate the performance of protein `{protein_name}`\
                   . Here is the context: {context}\
                    Should I spawn a new pipeline for it?"

    llm_response = await llm_agent.prompt(message=llm_message) 
    spawn_new_pipeline_decision = llm_response.parsed_response.spawn_new_pipeline
    confidence = llm_response.parsed_response.confidence
    if llm_response.reasoning:
      reasoning = llm_response.reasoning
    else:
      reasoning = llm_response.parsed_response.reasoning

    logger.info(f"Agent decision for {protein_name}: "
                f"Spawn New = {spawn_new_pipeline_decision}. "
                f"Confidence =  {confidence}"
                f"Reasoning =  {reasoning}")

    key_name = f"{protein_name}_pass_{pipeline.passes}"
    pipelines_decisions[key_name] = {"approved_new_pipeline": spawn_new_pipeline_decision,
                                         "reasoning": reasoning, 
                                         "confidence": confidence}
    return spawn_new_pipeline_decision
