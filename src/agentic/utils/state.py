# state.py

from dataclasses import dataclass
from typing_extensions import Annotated
from operator import add
from langchain.messages import AnyMessage
from langgraph.graph import START, END
from langchain_openai import ChatOpenAI
from typing_extensions import Literal, TypedDict
import os
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

# pydantic
class NextTaskSchema(BaseModel):
    next_task: Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END] = Field(
        None, description="Next task decisions available to the router."
    )

# typeddict
#class NextTaskSchema(TypedDict):
#    next_task: Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END] = Field(
#        None, description="Next task decisions available to the router."
#    )

# json
NextTaskSchema = ToolStrategy({
    "type": "object", 
    "title": "NextTaskSchema",
    "description": "Next task decisions available to the router.",
    "properties": {
        "next_task": {
            "type": "string",
            "enum": [
                "run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END
                ],
            "description": "The next task to be run"
        }
    },
    "required": ["next_task"]
})


@dataclass
class RuntimeContext:
    """Runtime context schema."""
    pipeline_name: str
    pipeline_uid: int | None
    base_path: str = os.getcwd()
    input_dir: str = os.path.join(base_path, 'inputs')
    output_dir: str = os.path.join(base_path, 'outputs')
    mpnn_script: str = 'mpnn_wrapper.py'
    mpnn_num_seqs: int = 10
    model_path: str = "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
    inference_server_url: str = "http://localhost:8010/v1"

@dataclass
class PipelineState:
    """State of the pipeline."""
    messages: Annotated[list[AnyMessage], add]
    input_pdb_filename: str
    sequence_scores_list: Annotated[list[float], add]
    fold_scores_list: Annotated[list[float], add]
#    fasta_list_2: list[str]
    task_list: Annotated[list[str], add]
    next_task: Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END]
    previous_task: Literal[START, "run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold"] = START 
    input_dir: str = "inputs"
    previous_fold_score: float = None
    decision: str = None
    llm_calls: int = 0
    pass_num: int = 1
    max_passes: int = 4
    top_sequence: str = None
    top_sequence_fasta_file: str = None


