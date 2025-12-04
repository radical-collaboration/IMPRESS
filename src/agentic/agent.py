# agent.py

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langgraph.runtime import Runtime
from utils.nodes import task_sequence_generator
from utils.state import RuntimeContext, PipelineState
from utils.tools import run_mpnn, score_mpnn, make_fasta_file, run_alphafold, score_alphafold
import os
from IPython.display import Image, display

#def make_impress(state, context):
#    return(
#        StateGraph(state,context)
#        .add_node("task_sequence_generator", task_sequence_generator)
#        .add_node("run_mpnn", run_mpnn)
#        .add_node("score_mpnn", score_mpnn)
#        .add_node("make_fasta_file", make_fasta_file)
#        .add_node("run_alphafold", run_alphafold)
#        .add_node("score_alphafold", score_alphafold)
#        .add_edge(START, "task_sequence_generator")
#        .compile()
#    )

def route_decision(state: PipelineState):
    # Return the node name you want to visit next
    if state["decision"] == "run_mpnn":
        return "run_mpnn"
    elif state["decision"] == "score_mpnn":
        return "score_mpnn"
    elif state["decision"] == "run_alphafold":
        return "run_alphafold"
    elif state["decision"] == "make_fasta_file":
        return "make_fasta_file"
    elif state["decision"] == END:
        return END
    
impress_workflow = (
    StateGraph(PipelineState,RuntimeContext)
    .add_node("task_sequence_generator", task_sequence_generator)
    .add_node("run_mpnn", run_mpnn)
    .add_node("score_mpnn", score_mpnn)
    .add_node("make_fasta_file", make_fasta_file)
    .add_node("run_alphafold", run_alphafold)
    .add_node("score_alphafold", score_alphafold)
    .add_edge(START, "task_sequence_generator")
    .add_conditional_edges(
        "task_sequence_generator",
        route_decision,
        {  # Name returned by route_decision : Name of next node to visit
            "run_mpnn": "run_mpnn",
            "score_mpnn": "score_mpnn",
            "run_alphafold": "run_alphafold",
            "score_alphafold": "score_alphafold",
            "make_fasta_file": "make_fasta_file",
            END: END,
        },
    )
    .compile()
)

#if __name__ == "__main__":    
#    impress_workflow = make_impress(PipelineState, ModelContext)
 
#    display(Image(impress_workflow.get_graph().draw_mermaid_png()))

context = RuntimeContext(pipeline_name = "p1", pipeline_uid = 1)

for chunk in impress_workflow.stream(
    {
        "messages": [{"role": "user", "content": "Run the workflow on the given file.",}],
        "input_pdb_filename": "6v7q.pdb",
        "next_task": START,
        "task_list": [START]
    },
    context = context,
#    stream_mode = "debug"
):
    print(chunk)
#    for node, update in chunk.items():
#        print("Update from node", node)
#        update["messages"].pretty_print()
#        print("\n\n")

#    for update in chunk.values():
#        for message in update.messages:
#            message.pretty_print()
#    for node, update in chunk.items():
#        print("Update from node", node)
#        update["messages"][-1].pretty_print()
#        print("\n\n")
        
