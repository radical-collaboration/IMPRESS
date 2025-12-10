# agent.py

"""
Async LangGraph-based Protein Design Pipeline
Orchestrates MPNN sequence generation and AlphaFold structure prediction
"""

import os
import asyncio
from langgraph.graph import StateGraph, END, START
from state import PipelineState
from nodes import task_sequence_generator, task_sequence_generator_json, route_to_task
from tools import (
    run_mpnn_node,
    score_mpnn_node,
    make_fasta_file_node,
    run_alphafold_node,
    score_alphafold_node
)


def create_protein_pipeline(use_json_parsing: bool = True):
    """
    Creates and compiles the async protein design pipeline graph.
    
    Args:
        use_json_parsing: If True, uses manual JSON parsing (more compatible).
                         If False, uses with_structured_output (requires model support).
    
    Graph structure:
    - Router (task_sequence_generator) determines next task
    - Conditionally routes to one of five tool nodes or END
    - Each tool node executes and returns to router for next decision
    """
    
    # Initialize the graph with state schema
    workflow = StateGraph(PipelineState)
    
    # Add the router node - choose implementation based on flag
    router_func = task_sequence_generator_json if use_json_parsing else task_sequence_generator
    workflow.add_node("task_sequence_generator", router_func)
    
    # Add the five tool nodes
    workflow.add_node("run_mpnn", run_mpnn_node)
    workflow.add_node("score_mpnn", score_mpnn_node)
    workflow.add_node("make_fasta_file", make_fasta_file_node)
    workflow.add_node("run_alphafold", run_alphafold_node)
    workflow.add_node("score_alphafold", score_alphafold_node)
    
    # Set entry point to router
    workflow.set_entry_point("task_sequence_generator")
    
    # Add conditional edges from router to each tool
    workflow.add_conditional_edges(
        "task_sequence_generator",
        route_to_task,
        {
            "run_mpnn": "run_mpnn",
            "score_mpnn": "score_mpnn",
            "make_fasta_file": "make_fasta_file",
            "run_alphafold": "run_alphafold",
            "score_alphafold": "score_alphafold",
            "END": END
        }
    )
    
    # Add edges from each tool back to router
    # This creates a loop where router decides next action after each tool
    workflow.add_edge("run_mpnn", "task_sequence_generator")
    workflow.add_edge("score_mpnn", "task_sequence_generator")
    workflow.add_edge("make_fasta_file", "task_sequence_generator")
    workflow.add_edge("run_alphafold", "task_sequence_generator")
    workflow.add_edge("score_alphafold", "task_sequence_generator")
    
    # Compile the graph
    app = workflow.compile()
    
    return app


def initialize_pipeline_state(
    input_pdb_filename: str,
    pipeline_name: str = "protein_pipeline",
    pipeline_uid: int = 1,
    base_path: str = None,
    max_passes: int = 4,
    mpnn_num_seqs: int = 10,
    model_path: str = None,
    inference_server_url: str = "http://localhost:8010/v1"
) -> PipelineState:
    """
    Initialize the pipeline state with required configuration.
    
    Args:
        input_pdb_filename: Name of the input PDB file
        pipeline_name: Name identifier for the pipeline
        pipeline_uid: Unique ID for this pipeline run
        base_path: Base directory for the project
        max_passes: Maximum number of optimization passes
        mpnn_num_seqs: Number of sequences to generate with MPNN
        model_path: Path to the LLM model
        inference_server_url: URL for the inference server
    
    Returns:
        Initialized PipelineState dictionary
    """
    if base_path is None:
        base_path = os.getcwd()
    
    if model_path is None:
        model_path = "/home/mason/exdrive/.cache/huggingface/hub/hub/models--meta-llama--Llama-3.2-1B-Instruct/snapshots/9213176726f574b556790deb65791e0c5aa438b6"
    
    input_dir = os.path.join(base_path, 'inputs')
    output_dir = os.path.join(base_path, 'outputs')
    
    # Create directories if they don't exist
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    return {
        # Messages and tracking
        "messages": [],
        "llm_calls": 0,
        
        # Input/output paths
        "input_pdb_filename": input_pdb_filename,
        "input_dir": input_dir,
        
        # Task management
        "task_list": [],
        "next_task": "START",
        "previous_task": "START",
        "decision": "",
        
        # Scores
        "sequence_scores_list": [],
        "fold_scores_list": [],
        "previous_fold_score": None,
        "current_fold_score": None,
        
        # Pass management
        "pass_num": 1,
        "max_passes": max_passes,
        
        # Sequences and structures
        "top_sequence": "",
        "top_sequence_fasta_file": "",
        
        # Runtime context
        "pipeline_name": pipeline_name,
        "pipeline_uid": pipeline_uid,
        "base_path": base_path,
        "output_dir": output_dir,
        "mpnn_script": "mpnn_wrapper.py",
        "mpnn_num_seqs": mpnn_num_seqs,
        "model_path": model_path,
        "inference_server_url": inference_server_url
    }


async def run_pipeline_async(input_pdb_filename: str, verbose: bool = True, use_json_parsing: bool = True):
    """
    Async execute the complete protein design pipeline.
    
    Args:
        input_pdb_filename: Name of the input PDB file
        verbose: Whether to print detailed execution logs
        use_json_parsing: Use manual JSON parsing (True) vs with_structured_output (False)
    """
    # Create the pipeline graph
    pipeline = create_protein_pipeline(use_json_parsing=use_json_parsing)
    
    # Initialize state
    initial_state = initialize_pipeline_state(input_pdb_filename)
    
    if verbose:
        print("=" * 70)
        print("Protein Design Pipeline - Starting (Async)")
        print("=" * 70)
        print(f"Input PDB: {input_pdb_filename}")
        print(f"Max Passes: {initial_state['max_passes']}")
        print(f"MPNN Sequences per Pass: {initial_state['mpnn_num_seqs']}")
        print(f"Router Mode: {'JSON Parsing' if use_json_parsing else 'Structured Output'}")
        print("=" * 70)
    
    # Run the pipeline with streaming
    try:
        async for chunk in pipeline.astream(initial_state):
            if verbose:
                for node_name, node_state in chunk.items():
                    print(f"\n🔄 Node: {node_name}")
                    if "messages" in node_state and node_state["messages"]:
                        for msg in node_state["messages"]:
                            print(f"  📝 {msg}")
        
        # Get final state
        final_state = await pipeline.ainvoke(initial_state)
        
        if verbose:
            print("\n" + "=" * 70)
            print("Pipeline Execution Complete")
            print("=" * 70)
            
            print("\n📊 Summary:")
            print(f"  • Total LLM Calls: {final_state.get('llm_calls', 0)}")
            print(f"  • Tasks Executed: {len(final_state.get('task_list', []))}")
            print(f"  • Final Pass: {final_state.get('pass_num', 1) - 1}")
            print(f"  • Top Sequence: {final_state.get('top_sequence', 'N/A')[:50]}...")
            print(f"  • Best Fold Score: {final_state.get('current_fold_score', 'N/A')}")
            
            if final_state.get("fold_scores_list"):
                print(f"\n  Fold Score History: {final_state['fold_scores_list']}")
            
            print("=" * 70)
        
        return final_state
        
    except Exception as e:
        print(f"\n❌ Pipeline failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise


def run_pipeline(input_pdb_filename: str, verbose: bool = True, use_json_parsing: bool = True):
    """
    Synchronous wrapper for async pipeline execution.
    
    Args:
        input_pdb_filename: Name of the input PDB file
        verbose: Whether to print detailed execution logs
        use_json_parsing: Use manual JSON parsing (True) vs with_structured_output (False)
    """
    return asyncio.run(run_pipeline_async(input_pdb_filename, verbose, use_json_parsing))


async def stream_pipeline_async(input_pdb_filename: str):
    """
    Stream the pipeline execution with real-time updates.
    
    Args:
        input_pdb_filename: Name of the input PDB file
    
    Yields:
        Dictionary chunks with node updates
    """
    pipeline = create_protein_pipeline()
    initial_state = initialize_pipeline_state(input_pdb_filename)
    
    print("=" * 70)
    print("Streaming Pipeline Execution")
    print("=" * 70)
    
    async for chunk in pipeline.astream(initial_state):
        print(f"\n📦 Chunk: {chunk}")
        yield chunk
    
    print("\n" + "=" * 70)
    print("Stream Complete")
    print("=" * 70)


async def main_async():
    """
    Async main entry point for the protein design pipeline.
    """
    # Example usage
    input_pdb = "6v7q.pdb"
    
    # Check if input file exists
    input_path = os.path.join(os.getcwd(), "inputs", input_pdb)
    if not os.path.exists(input_path):
        print(f"⚠️  Warning: Input file not found at {input_path}")
        print("Creating placeholder for demonstration...")
        os.makedirs(os.path.dirname(input_path), exist_ok=True)
        with open(input_path, "w") as f:
            f.write("# Placeholder PDB file\n")
    
    # Run the pipeline
    final_state = await run_pipeline_async(input_pdb, verbose=True)
    
    return final_state


def main():
    """
    Synchronous main entry point.
    """
    return asyncio.run(main_async())


if __name__ == "__main__":
    # You can also use the streaming version:
    # asyncio.run(stream_pipeline_async("6v7q.pdb"))
    
    main()
