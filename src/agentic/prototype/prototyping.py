#!/usr/bin/env python
# coding: utf-8

# In[ ]:


from dataclasses import dataclass
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.structured_output import ToolStrategy

MYLLM="/path/to/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.1-8B-Instruct/snapshots/0e9e39f249a16976918f6564b8830bc894c89659/"
inference_server_url = "http://localhost:8010/v1"
chatmodel = ChatOpenAI(
    model=MYLLM,
    openai_api_key="EMPTY",
    openai_api_base=inference_server_url,
    temperature=0.2,
    streaming=True,
    max_tokens=100
)


# In[ ]:


########################## CONTEXT
# 'Context' is for static data, things like user context and fixed parameters.
#@dataclass
#class Context:
#    """Custom runtime context schema."""
#    user_id: str


# In[ ]:


########################## MEMORY
# 'Memory' is for persisting conversations (maybe this affects tool loop bugs?)
# In prod this should be a db
checkpointer = InMemorySaver()
#checkpointer = None
# # # # # # 


# In[ ]:


########################## STATE

# The task generator agent needs to know prior tasks and scores to make a decision.
# But those don't need to be in the agent state.
#from langchain.agents import AgentState
#from langchain.agents.middleware import AgentMiddleware

#class CustomState(AgentState):
#    previous_task: None
#    previous_mpnn_score: None
#    previous_alphafold_score: None

#class CustomMiddleware(AgentMiddleware):
#    state_schema = CustomState
#    tools = [tool1, tool2]


# In[ ]:


########################## NON-LLM TOOLS
@tool
def get_input_backbone(runtime: ToolRuntime[PipelineContext]) -> str:
    """Get an input backbone structure.

    Args:


    """
    #TODO logic for get input
    pipeline_info = runtime.context.pipeline_info
    pipeline_id = pipeline_info.pipeline_id
    backbone_structure_file = pipeline_info.backbone_structure_file

    return f"The input backbone structure is as follows: {(1,2,3),(4,5,6)}"

# run mpnn - s1
@tool
def run_mpnn(runtime: ToolRuntime[Context]) -> str:
    """Predict sequence with ProteinMPNN.

    Args:
        input_dir: target location for inputs
        output_dir: target location for outputs
    """
    # mpnn_script = os.path.join(self.base_path, "mpnn_wrapper.py")
    # output_dir = os.path.join(self.output_path_mpnn, f"job_{self.passes}")

    # chain = "A" if self.passes == 1 else "B"
    # input_path = self.input_path if self.passes == 1 else self.output_path_af

    # return (
    #     f"python3 {mpnn_script} "
    #     f"-pdb={input_path} "
    #     f"-out={output_dir} "
    #     f"-mpnn={self.mpnn_path} "
    #     f"-seqs={self.num_seqs} "
    #     f"-is_monomer=0 "
    #     f"-chains={chain}"
    # )
    sequence = "ABCDEF"
    return f"The predicted sequence is {sequence}."

# score mpnn - s2
@tool
def score_mpnn(runtime: ToolRuntime[Context]) -> str:
    """Rank sequences."""
    # job_seqs_dir = f"{self.output_path_mpnn}/job_{self.passes}/seqs"

    # for file_name in os.listdir(job_seqs_dir):
    #     seqs = []
    #     with open(os.path.join(job_seqs_dir, file_name)) as fd:
    #         lines = fd.readlines()[2:]  # Skip first two lines

    #     score = None
    #     for line in lines:
    #         line = line.strip()
    #         if line.startswith(">"):
    #             score = float(line.split(",")[2].replace(" score=", ""))
    #         else:
    #             seqs.append([line, score])

    #     seqs.sort(key=lambda x: x[1])  # Sort by score
    #     self.iter_seqs[file_name.split(".")[0]] = seqs
    score = random.random()
    return f"The current score is {score}."

# fasta prep = s3
@tool
def preprocess_mpnn_outputs(runtime: ToolRuntime[Context]) -> str:
    """Make fasta."""
    #TODO: make fasta
    return "a fasta file"

# run alphafold - s4
@tool
def run_alphafold(runtime: ToolRuntime[Context]) -> str:
    """Run AlphaFold to predict a fold for the given sequence."""
    #TODO: make run af2
#    cmd = (
#        f"/bin/bash {self.base_path}/af2_multimer_reduced.sh "
#        f"{self.output_path}/af/fasta/ "
#        f"{target_fasta}.fa "
#        f"{self.output_path}/af/prediction/dimer_models/ "
#    )

#    return cmd
    return "AlphaFold ran successfully."

# get score - s5
@tool
def score_alphafold(runtime: ToolRuntime[Context]) -> str:
    """Get AlphaFold scores."""
    #TODO: make extract plddt
#    return (
#        f"python3 {self.base_path}/plddt_extract_pipeline.py "
#        f"--path={self.base_path} "
#        f"--iter={self.passes} "
#        f"--out={self.name}"
#    )
    plddt = random.random()
    return "The current plDDT is {plddt}"


# In[ ]:


########################## DEFINING: SYSTEM PROMPTS

MPNN_RUNNER_AGENT_PROMPT = (
    "You are a computational assistant who runs "
    "the program called ProteinMPNN. "
    "ProteinMPNN is a tool for protein sequence prediction. "
    "You have access to a tool called run_mpnn. "
    "Use run_mpnn to run the program ProteinMPNN. "
    "Check to make sure you call the tool only once. "
)
MPNN_SCORING_AGENT_PROMPT = (
    "You are a computational assistant who runs "
    "a program to calculate confidence scores, given a protein sequence. "
    "The scoring program reports model confidence of sequences produced by ProteinMPNN. "
    "You have access to a tool called score_mpnn. "
    "Use score_mpnn to run the scoring program."
    "Check to make sure you call the tool only once. "
)
ALPHAFOLD_RUNNER_AGENT_PROMPT = (
    "You are a computational assistant who runs "
    "the program called AlphaFold. "
    "AlphaFold is a tool for protein fold prediction. "
    "You have access to a tool called run_alphafold. "
    "Use run_alphafold to run the program AlphaFold."
    "Check to make sure you call the tool only once. "
)
ALPHAFOLD_SCORING_AGENT_PROMPT = (
    "You are a computational assistant who runs "
    "a program to calculate confidence scores, given a folded protein structure. "
    "The scoring program reports model confidence of folded structures produced by AlphaFold. "
    "You have access to a tool called score_alphafold. "
    "Use score_alphafold to run the scoring program."
    "Check to make sure you call the tool only once. "
)
PIPELINE_AGENT_PROMPT = (
    "You are a computational assistant who directs tool agents to perform work. "
    "You receive work instructions from the Task Sequence Generator Agent. "
    "Based on those instructions, you use one of your tools. "
    "You have access to five tools: "
    "get_input_backbone, "
    "call_mpnn_runner_agent, call_alphafold_runner_agent, "
    "call_mpnn_scoring_agent, and call_alphafold_scoring_agent. "
    "Use the tool that matches the instruction given to you by the Task Sequence Generator Agent. "
    "Check to make sure you call only one tool per incoming instruction. "
)
TASK_GENERATOR_AGENT_PROMPT = (
    "You are a planner responsible for choosing the next task in an ongoing protein design workflow, "
    "or for choosing to stop the workflow. "
    "The workflow itself is a sequence of protein design tasks, but you choose only one at a time. "
    "The five tasks available to you are: get_input_backbone, "
    "sequence prediction, sequence scoring, fold prediction, and fold scoring. "
    "You also have access to parameters describing the workflow while it is in process. "
    "The parameters available to you are: "
    "current iteration number, maximum iteration number, and previous fold score. "
    "Your choice of task is determined by the results from the previous task. "
    "Backbone selection outputs a protein backbone structure and should be followed by sequence prediction. "
    "Sequence prediction outputs a set of protein sequences and should be followed by sequence scoring. "
    "Sequence scoring outputs the sequence score of the highest-confidence sequence information and should be followed by fold prediction. "
    "Fold prediction outputs a set of folded protein structures and should be followed by fold scoring. "
    "Fold scoring outputs the fold score of the current highest-confidence folded protein structure. "
    "The task you choose after fold scoring will depend on a comparison "
    "between the current fold score and the previous fold score. "
    "If the current fold score is higher than the previous fold score, "
    "then the next task should be backbone selection. "
    "If the previous score is higher, then stop. "
    "You have access to one tool: call_pipeline_agent. Call this tool with your chosen task as the input."
)


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* MPNN RUNNER AGENT
mpnn_runner_agent = create_agent(
    model=chatmodel,
    system_prompt=MPNN_RUNNER_AGENT_PROMPT,
    tools=[run_mpnn],
#    context_schema=Context,
#    checkpointer=checkpointer
)
@tool(
    "call_mpnn_runner_agent",
    description=(
        "This agent runs the program ProteinMPNN. "
        "Given a protein backbone structure, it returns a protein sequence."
    )
)
def call_mpnn_runner_agent(query: str):
    result = mpnn_runner_agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    return result["messages"][-1].content


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* ALPHAFOLD RUNNER AGENT
alphafold_runner_agent = create_agent(
    model=chatmodel,
    system_prompt=ALPHAFOLD_RUNNER_AGENT_PROMPT,
    tools=[run_alphafold],
#    context_schema=Context,
#    checkpointer=checkpointer
)
@tool(
    "call_alphafold_runner_agent",
    description=(
        "This agent runs the program Alphafold. "
        "Given a protein sequence, it returns a folded protein structure."
    )
)
def call_alphafold_runner_agent(query: str):
    result = alphafold_runner_agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    return result["messages"][-1].content


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* MPNN SCORING AGENT
mpnn_scoring_agent = create_agent(
    model=chatmodel,
    system_prompt=MPNN_SCORING_AGENT_PROMPT,
    tools=[run_mpnn],
#    context_schema=Context,
#    checkpointer=checkpointer
)
@tool(
    "call_mpnn_scoring_agent",
    description=(
        "This agent scores the outputs of the program ProteinMPNN. "
        "Given a ProteinMPNN output sequence, it returns a score."
    )
)
def call_mpnn_scoring_agent(query: str):
    result = mpnn_scoring_agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    return result["messages"][-1].content


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* ALPHAFOLD SCORING AGENT
alphafold_scoring_agent = create_agent(
    model=chatmodel,
    system_prompt=ALPHAFOLD_SCORING_AGENT_PROMPT,
    tools=[run_mpnn],
#    context_schema=Context,
#    checkpointer=checkpointer
)
@tool(
    "call_alphafold_scoring_agent",
    description=(
        "This agent scores the outputs of the program AlphaFold. "
        "Given an AlphaFold output structure, it returns a score."
    )
)
def call_alphafold_scoring_agent(query: str):
    result = alphafold_scoring_agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    return result["messages"][-1].content


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* PIPELINE AGENT (ROUTER)
# Unique pipeline agents are instantiated on each input at runtime.
# Pipeline agents are initialized and their context manager is instantiated.
# Context (the conversation) to be trimmed and replaced with a task history e.g.
# {name, pipeline_id, base_path, input_path, input_structure, task_list, scores_list}
pipeline_agent = create_agent(
    model=chatmodel,
    system_prompt=PIPELINE_AGENT_PROMPT,
    tools=[get_input_backbone, call_mpnn_runner_agent, call_alphafold_runner_agent,
        call_mpnn_scoring_agent, call_alphafold_scoring_agent],
#    context_schema=Context,
#    checkpointer=checkpointer
)
@tool(
    "call_pipelne_agent",
    description=(
        "This agent uses tools to complete protein design tasks. "
    )
)
def call_pipeline_agent(query: str):
    result = pipeline_agent.invoke({
        "messages": [{"role": "user", "content": query}]
    })
    return result["messages"][-1].content


# In[ ]:


#*#*#*#*#*#*#*#*#*#*#*#*#* TASK SEQUENCE GENERATOR AGENT (PLANNER)
task_sequence_generator_agent = create_agent(
    model=chatmodel,
    system_prompt=TASK_GENERATOR_AGENT_PROMPT,
    tools=[call_pipeline_agent],
#    context_schema=Context,
#    checkpointer=checkpointer
)


# In[ ]:


########################## TESTING: GET BACKBONE

# Run agent
# `thread_id` is a unique identifier for a given conversation.
# Note that we can continue the conversation using the same `thread_id`.
# i.e. by passing the same config to multiple agent invocations.
config = {"configurable": {"thread_id": "1"}}

TEST_PROMPT = (
    "Get an input backbone coordinates by calling get_input_backbone()."
)
for step in pipeline_agent.stream(
    {"messages": [{"role": "user", "content": TEST_PROMPT}]}
):
    for update in step.values():
        for message in update.get("messages", []):
            message.pretty_print()




# In[ ]:


########################## TESTING: MPNN RUNNER
config = {"configurable": {"thread_id": "1"}}

TEST_PROMPT = (
    "Get a predicted protein sequence by calling the tool run_mpnn."
)
for step in mpnn_runner_agent.stream(
    {"messages": [{"role": "user", "content": TEST_PROMPT}]}
):
    for update in step.values():
        for message in update.get("messages", []):
            message.pretty_print()




# In[ ]:




