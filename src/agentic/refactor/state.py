# state.py

from typing import TypedDict, Literal, Annotated
from operator import add
from pydantic import BaseModel, Field


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
