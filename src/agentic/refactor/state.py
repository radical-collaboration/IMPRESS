# state.py

from typing import TypedDict, Literal, Annotated
from operator import add
from pydantic import BaseModel, Field

from radical.asyncflow import ConcurrentExecutionBackend
from radical.asyncflow import DragonTelemetryCollector
from radical.asyncflow import DragonVllmInferenceBackend
from radical.asyncflow import DragonExecutionBackendV3, WorkflowEngine
from radical.asyncflow.logging import init_default_logger

from flowgentic.langGraph.execution_wrappers import AsyncFlowType
from flowgentic.langGraph.main import LangraphIntegration
from flowgentic.langGraph.utils.supervisor import create_llm_router, supervisor_fan_out
from flowgentic.utils.llm_providers import ChatLLMProvider

import itertools

import multiprocessing as mp

class NextTaskSchema(BaseModel):
    """Pydantic schema for structured output from the router."""
    next_task: Literal["run_mpnn", "score_mpnn", "make_fasta_file", "run_alphafold", "score_alphafold", "END"] = Field(
        description="Next task to execute in the protein design workflow"
    )
    reasoning: str = Field(
        description="Explanation for why this task was selected"
    )


class PipelineState(TypedDict):
    """State schema for the protein design pipeline."""
    # Messages and tracking
    messages: Annotated[list[str], add]
    llm_calls: int
    
    # Input/output paths
    input_pdb_filename: str
    input_dir: str
    
    # Task management
    task_list: Annotated[list[str], add]
    next_task: str
    previous_task: str
    decision: str
    
    # Scores
    sequence_scores_list: Annotated[list[float], add]
    fold_scores_list: Annotated[list[float], add]
    previous_fold_score: float
    current_fold_score: float
    
    # Pass management
    pass_num: int
    max_passes: int
    
    # Sequences and structures
    top_sequence: str
    top_sequence_fasta_file: str
    
    # Runtime context (merged into state)
    pipeline_name: str
    pipeline_uid: int
    base_path: str
    output_dir: str
    mpnn_script: str
    mpnn_num_seqs: int
    model_path: str
    inference_server_url: str
    endpoint_cycle: itertools.cycle
