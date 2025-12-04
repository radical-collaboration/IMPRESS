# agent.py

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langgraph.runtime import Runtime
#from utils.nodes import task_sequence_generator
from utils.state import RuntimeContext, PipelineState
from utils.tools import run_mpnn, score_mpnn, make_fasta_file, run_alphafold, score_alphafold
from langchain_openai import ChatOpenAI
import os
from IPython.display import Image, display
from dataclasses import dataclass
from typing_extensions import Literal, TypedDict
from langchain.messages import SystemMessage
from pydantic import BaseModel, Field


#class Route(BaseModel):
#    step: Literal["poem", "story", "joke"] = Field(
#        None, description="The next step in the routing process"
#    )

#class Division(TypedDict):
#    name: str = Field(description="The division name (e.g Chapter 1, Section 1.1, etc...)")
#    description: str = Field(description="one sentence description of the division")
#    instructions: str = Field(description="A few sentences of instructions on what to write for this division and in what style")
#    word_count: int = Field(description="The word count of the division")
    
#class NextTaskSchema(TypedDict):
#    next_task: Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END] = Field(
#        None, description="Next task decisions available to the router."
#    )

TaskSchema = {
    "type": "object",
    "title": "next_task schema",
    "description": "Next task decisions available to the router.",
    "properties": {
        "next_task": {
            "type": Literal[
                "run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END
                ],
            "description": "The next task to be run"
        }
    },
    "required": ["next_task"]
}

MODELS = {
    "llama3.2": "/home/mason/exdrive/.cache/huggingface/hub/hub/\
models--meta-llama--Llama-3.2-1B-Instruct/\
snapshots/9213176726f574b556790deb65791e0c5aa438b6",
    "mistral": "/home/mason/exdrive/.cache/huggingface/hub/hub/models--mistralai--Ministral-3-3B-Instruct-2512/snapshots/7e1b52c2f4d55005fd9f204f5e6303b0cd50e94b",
    "llama3.1": "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"

}

MYLLM = MODELS["llama3.2"] 
#MYLLM: str = "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
inference_server_url: str = "http://localhost:8010/v1"
MODEL = ChatOpenAI(
    model=MYLLM,
    openai_api_key="EMPTY",
    openai_api_base=inference_server_url,
    temperature=0.2,
    streaming=True,
    max_tokens=30
)

model_task_choice = MODEL.with_structured_output(
    schema = TaskSchema,
    method = "json_schema",
    include_raw = True,
    strict=True)

task_generator_system_prompt = f"""
You are a planner responsible for choosing the next task
in an ongoing protein design workflow, or for choosing to end the workflow. 

## The workflow tasks
The workflow is a sequence of protein tasks, but you choose only one at a time. 
The five tasks options are fixed, and are as follows:
* run_mpnn
* score_mpnn
* run_alphafold
* score_alphafold
* END
When prompted with the previous task, you must respond with a choice that matches one of these.

## Response formatting
Your response should consist only of one of the task options. 
Do not include any additional information.
Do not add any punctuation.
Respond in two words or less.

## Choosing the right task
Your choice of task is determined by the results from the previous task. 
If it is the first task, then the previous task will be START and 
'run_mpnn' should be run. 'run_mpnn' should also be run 
after any task that outputs a candidate protein backbone structure with an 
undefined sequence.
'run_mpnn' outputs a set of sequences and should be followed by 'score_mpnn'. 
'score_mpnn' outputs the sequence score of the highest-confidence sequence information and should be followed by 'run_alphafold'. 
'run_alphafold' outputs a set of folded protein structures and should be followed by 'score_alphafold'. 
'score_alphafold' outputs the fold score of the current highest-confidence folded protein structure. 
The task you choose after 'score_alphafold' will depend on a comparison 
between the current fold score and the previous fold score.     
If the current fold score is higher than the previous fold score, 
or if the previous fold score is None, 
then 'score_alphafold' should be followed by sequence prediction. 
If the previous fold score is higher than the current fold score, then choose END.

## Examples
Here are some examples:

1)
previous task: run_alphafold
your response: score_alphafold

2)
previous task: score_alphafold
current score: 1
previous score: 0.2
your response: run_mpnn

"""

task_generator_prompt = f"""The previous task was 'score_mpnn'. 
    Decide which task should come next.
"""
#task_generator_prompt = "you are responsible for choosing the next task. choose a program suitable for predicting protein sequences."
s_prompt = SystemMessage(task_generator_system_prompt)
h_prompt = SystemMessage(task_generator_prompt)    
response = MODEL.invoke([s_prompt, h_prompt])

print(response)
#response["structured_response"]

#for chunk in impress_workflow.stream(
#    {
#        "messages": [{"role": "user", "content": "Run the workflow on the given file.",}],
#        "input_pdb_filename": "6v7q.pdb",
#        "next_task": START,
#        "task_list": [START]
#    },
#    context = context,
#    stream_mode = "debug"
#):
#    print(chunk)
#    for node, update in chunk.items():
#        print("Update from node", node)
#        update["messages"][-1].pretty_print()
#        print("\n\n")
