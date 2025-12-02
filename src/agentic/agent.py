# agent.py

from langgraph.graph import StateGraph, START
from langgraph.types import Command

from .utils.nodes import *

# build graph and compile
impress_builder = StateGraph(PipelineState)

# Add nodes
impress_builder.add_node("task_sequence_generator", task_sequence_generator)
impress_builder.add_node("run_mpnn", run_mpnn)
impress_builder.add_node("score_mpnn", score_mpnn)
impress_builder.add_node("make_fasta_file", make_fasta_file)
impress_builder.add_node("run_alphafold", run_alphafold)
impress_builder.add_node("score_alphafold", score_alphafold)

# Add edges to connect nodes
impress_builder.add_edge(START, "task_sequence_generator")

# Compile workflow
impress_workflow = impress_builder.compile()

# Show the workflow
display(Image(impress_workflow.get_graph().draw_mermaid_png()))


# invoke with input structure
for chunk in impress_workflow.stream(
    {
        "messages": [
            {
                "role": "user",
                "content": "What does Lilian Weng say about types of reward hacking?",
            }
        ]
    }
):
    for node, update in chunk.items():
        print("Update from node", node)
        update["messages"][-1].pretty_print()
        print("\n\n")
