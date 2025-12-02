# state.py

from dataclasses import dataclass
from typing_extensions import Annotated
from operator import add
from langchain.messages import AnyMessage
from langgraph.graph import END

@dataclass
class NextTaskClassification:
    next_task: Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END]

@dataclass
class PipelineState:
    messages: Annotated[list[AnyMessage], add]
    llm_calls: int
    pipeline_uid: int = None
    input_path: str
    input_structure: str
    decision: str
    task_list: Annotated[list[str], add]
    sequence_scores_list: Annotated[list[float], add]
    fold_scores_list: Annotated[list[float], add]
    previous_fold_score: float = None
    pass_num: int = 1
    max_passes: int = 4
    fasta_list_2: list[str] = []
    top_sequence: str
    top_sequence_fasta_file: str


