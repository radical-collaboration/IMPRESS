# nodes.py

from dataclasses import dataclass
from langchain_openai import ChatOpenAI

from .state import *
from .tools import *

# define context schema
@dataclass
class ContextSchema:
    MYLLM: str = "/path/to/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
    inference_server_url: str = "http://localhost:8010/v1"
    model = ChatOpenAI(
        model=MYLLM,
        openai_api_key="EMPTY",
        openai_api_base=inference_server_url,
        temperature=0.2,
        streaming=True,
        max_tokens=100
    )

#*#*#*#*#*#*#*#*#*#*#*#*#* TASK SEQUENCE GENERATOR NODE (PLANNER-ROUTER)
def task_sequence_generator(state: PipelineState, runtime: Runtime[ContextSchema]) -> Command[Literal["run_mpnn", "score_mpnn", "run_alphafold", "score_alphafold", END]]:
    """Use LLM to determine next protein task then route accordingly.
    
    """
    model = runtime.context.model
    task_list = state.get("task_list")
    model_task_choice = model.with_structured_output(NextTaskClassification)

#    messages = state["messages"]
    
    task_generator_prompt = f"""
    You are a planner responsible for choosing the next task
    in an ongoing protein design workflow, or for choosing to end the workflow. 
    The workflow is a sequence of protein tasks, but you choose only one at a time. 
    The five tasks options are: 
    run_mpnn, score_mpnn, run_alphafold, score_alphafold, and END. 
    Your choice of task is determined by the results from the previous task. 
    run_mpnn outputs a set of sequences and should be followed by score_mpnn. 
    score_mpnn outputs the sequence score of the highest-confidence sequence information and should be followed by run_alphafold. 
    run_alphafold outputs a set of folded protein structures and should be followed by score_alphafold. 
    score_alphafold outputs the fold score of the current highest-confidence folded protein structure. 
    The task you choose after score_alphafold will depend on a comparison 
    between the current fold score and the previous fold score.     
    If the current fold score is higher than the previous fold score, 
    or if the previous fold score is None, 
    then score_alphafold should be followed by backbone selection. 
    If the previous score is higher, then stop.

    The previous task is {state.get("task_list")[-1]}.
    The previous fold score is {state.get("previous_fold_score")}
    Decide which task should come next.
    """

    decision = model_task_choice.invoke(task_generator_prompt)

    if decision['next_task'] == 'run_mpnn':
        goto = "run_mpnn"
    elif decision['next_task'] == 'score_mpnn':
        goto = "score_mpnn"
    elif decision['next_task'] == 'run_alphafold':
        goto = "run_alphafold"
    elif decision['next_task'] == 'score_alphafold':
        goto = "score_alphafold"
    else:
        goto = END

    return Command(
        update={"decision": decision['next_task']},
        goto=goto
    )


