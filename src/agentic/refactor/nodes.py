# nodes.py

import asyncio
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from state import PipelineState, NextTaskSchema


MODELS = {
    "llama3.2": "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.2-1B-Instruct/snapshots/9213176726f574b556790deb65791e0c5aa438b6",
    "mistral": "/home/mason/exdrive/.cache/huggingface/hub/hub/models--mistralai--Ministral-3-3B-Instruct-2512/snapshots/7e1b52c2f4d55005fd9f204f5e6303b0cd50e94b",
    "llama3.1": "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
}


def get_llm(state: PipelineState) -> ChatOpenAI:
    """
    Initialize the LLM for routing decisions.
    Uses local inference server with configurable model.
    """
    model_path = state.get("model_path", MODELS["llama3.2"])
    inference_server_url = state.get("inference_server_url", "http://localhost:8010/v1")
    
    return ChatOpenAI(
        model=model_path,
        openai_api_key="EMPTY",
        openai_api_base=inference_server_url,
        temperature=0.2,
        max_tokens=100
    )


async def task_sequence_generator(state: PipelineState) -> PipelineState:
    """
    Async Router node: Use LLM to determine next protein task.
    
    Analyzes the current pipeline state and decides which task to execute next:
    - run_mpnn: Generate protein sequences
    - score_mpnn: Score generated sequences
    - make_fasta_file: Prepare FASTA for AlphaFold
    - run_alphafold: Fold the top sequence
    - score_alphafold: Score the folded structure
    - END: Terminate the workflow
    """
    model = get_llm(state)
    
    # Get current state information
    task_list = state.get("task_list", [])
    previous_task = state.get("previous_task", "START")
    previous_fold_score = state.get("previous_fold_score")
    current_fold_score = state.get("current_fold_score")
    pass_num = state.get("pass_num", 1)
    max_passes = state.get("max_passes", 4)
    
    # Build the system prompt
    task_generator_system_prompt = """You are a planner responsible for choosing the next task
in an ongoing protein design workflow, or for choosing to end the workflow.

## The workflow tasks
The workflow is a sequence of protein tasks, but you choose only one at a time. 
The task options are:
* run_mpnn - Generate sequences with ProteinMPNN
* score_mpnn - Rank and select best sequence
* make_fasta_file - Prepare FASTA file for AlphaFold
* run_alphafold - Predict protein structure
* score_alphafold - Score the folded structure
* END - Terminate the workflow

## Task sequencing rules
Your choice of task is determined by the previous task:
- START should be followed by 'run_mpnn'
- 'run_mpnn' outputs sequences and should be followed by 'score_mpnn'
- 'score_mpnn' outputs the highest-confidence sequence and should be followed by 'make_fasta_file'
- 'make_fasta_file' prepares input and should be followed by 'run_alphafold'
- 'run_alphafold' outputs folded structures and should be followed by 'score_alphafold'
- After 'score_alphafold', compare current and previous fold scores:
  * If current_fold_score > previous_fold_score (or previous is None): go to 'run_mpnn' for another pass
  * If previous_fold_score >= current_fold_score: choose 'END' (no improvement)
  * If max_passes reached: choose 'END'

Choose the next task and explain your reasoning clearly."""

    # Build the user prompt with current state
    task_generator_user_prompt = f"""Current pipeline state:
Previous task: {previous_task}
Pass number: {pass_num} of {max_passes}
Previous fold score: {previous_fold_score}
Current fold score: {current_fold_score}
Task history: {task_list}

What should be the next task?"""
    
    # Create prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", task_generator_system_prompt),
        ("user", task_generator_user_prompt)
    ])
    
    # Get structured output
    try:
        structured_llm = model.with_structured_output(NextTaskSchema)
        chain = prompt | structured_llm
        
        # Async invoke
        decision = await chain.ainvoke({})
        
        next_task = decision.next_task
        reasoning = decision.reasoning
        
        print(f"LLM Decision: {next_task} - {reasoning}")
        
    except Exception as e:
        print(f"Warning: LLM routing failed ({str(e)}), using fallback logic")
        next_task, reasoning = await fallback_routing(state)
    
    # Update state
    return {
        **state,
        "decision": next_task,
        "next_task": next_task,
        "previous_task": previous_task,
        "task_list": [next_task],
        "messages": [f"Router: Selected {next_task}. Reasoning: {reasoning}"],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


async def fallback_routing(state: PipelineState) -> tuple[str, str]:
    """
    Async fallback rule-based routing if LLM fails.
    """
    await asyncio.sleep(0)  # Make it truly async
    
    task_list = state.get("task_list", [])
    previous_task = state.get("previous_task", "START")
    pass_num = state.get("pass_num", 1)
    max_passes = state.get("max_passes", 4)
    previous_fold_score = state.get("previous_fold_score")
    current_fold_score = state.get("current_fold_score")
    
    # Rule-based routing
    if previous_task == "START":
        return "run_mpnn", "Starting first pass with sequence generation"
    
    elif previous_task == "score_alphafold":
        # Check if we should continue or end
        if pass_num >= max_passes:
            return "END", "Maximum passes reached"
        elif previous_fold_score is not None and current_fold_score is not None:
            if current_fold_score <= previous_fold_score:
                return "END", "No improvement in fold score"
        return "run_mpnn", "Continuing to next pass"
    
    elif previous_task == "run_mpnn":
        return "score_mpnn", "Score the generated sequences"
    
    elif previous_task == "score_mpnn":
        return "make_fasta_file", "Prepare FASTA for AlphaFold"
    
    elif previous_task == "make_fasta_file":
        return "run_alphafold", "Fold the top sequence"
    
    elif previous_task == "run_alphafold":
        return "score_alphafold", "Score the folded structure"
    
    else:
        return "END", "Unknown state, terminating"


def route_to_task(state: PipelineState) -> str:
    """
    Conditional edge function that determines which node to route to
    based on the router's decision.
    """
    decision = state.get("decision", "END")
    
    if decision == "END":
        return "END"
    else:
        return decision
