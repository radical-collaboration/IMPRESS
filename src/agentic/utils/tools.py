# tools.py

from langchain.tools import tool, ToolRuntime
from langchain.messages import ToolMessage
import os
import subprocess

from .state import *

@dataclass
class Context:
    """Runtime context schema."""
    base_path: str = os.getcwd()
    input_dir: str = os.path.join(base_path, 'inputs')
    output_dir: str = os.path.join(base_path, 'outputs')
    input_pdb_filename: str
    mpnn_script: str = 'mpnn_wrapper.py'
    mpnn_num_seqs: int = 10
    name: str
    
# TODO: do we need this?
#@tool
#def get_input_backbone(runtime: ToolRuntime[PipelineContext]) -> str:
#    """Get an input backbone structure.

# run mpnn - s1
@tool
def run_mpnn(runtime: ToolRuntime[Context]) -> Command[Literal["task_sequence_generator"]]:
    """Predict sequence with ProteinMPNN.

    Args:
        input_pdb_path: location of the input PDB file
        output_dir: target location for outputs
        chain: PDB chain ID for sequence prediction
    """
    base_path = runtime.context.basepath
    input_dir = runtime.context.input_dir
    output_dir = runtime.context.output_dir
    input_pdb_filename = runtime.context.input_pdb_filename
    mpnn_script = runtime.context.mpnn_script
    mpnn_num_seqs = runtime.context
    
    input_pdb_path = os.path.join(input_dir, input_pdb_filename)
    mpnn_path = os.path.join(base_path, mpnn_script)
#    chain = "A" if self.passes == 1 else "B"
    chain = "A"
    
    result = subprocess.run([
        f"python3 {mpnn_script}",
        f"-pdb={input_pdb_path}",
        f"-out={output_dir}",
        f"-mpnn={mpnn_path}",
        f"-seqs={mpnn_num_seqs}",
        f"-is_monomer=0",
        f"-chains={chain}"
    ])
    
    return Command(
        update = {
            "messages": ToolMessage(content=result, tool_call_id=tool_call["id"]),
            "task_list": "run_mpnn"
        },
        goto = "task_sequence_generator"
    )


# score mpnn - s2
@tool
def score_mpnn(state: PipelineState, runtime: ToolRuntime[Context]) -> Command[Literal["make_fasta_file"]]:
    """Rank sequences."""
    base_path = runtime.context.basepath
    input_dir = runtime.context.input_dir
    output_dir = runtime.context.output_dir
    input_pdb_filename = runtime.context.input_pdb_filename
    pass_num = state.get("pass_num")
    job_seqs_dir = os.path.join(output_dir,f"job_{pass_num}/seqs")
    
    for file_name in os.listdir(job_seqs_dir):
        seqs = []
        with open(os.path.join(job_seqs_dir, file_name)) as fd:
            lines = fd.readlines()[2:]  # Skip first two lines
            
        score = None
        for line in lines:
            line = line.strip()
            if line.startswith(">"):
                score = float(line.split(",")[2].replace(" score=", ""))
            else:
                seqs.append([line, score])
                
        seqs.sort(key=lambda x: x[1])  # Sort by score
    return Command(
        update = {
            "top_sequence": seqs[0],
            "messages": ToolMessage(content=result, tool_call_id=tool_call["id"]),
            "task_list": "score_mpnn"
        },
        goto = "make_fasta_file"
    )
#        self.iter_seqs[file_name.split(".")[0]] = seqs
#    score = random.random()
#    return f"The current score is {score}."


# fasta prep = s3
@tool
def make_fasta_file(state: PipelineState, runtime: ToolRuntime[Context]) -> Command[Literal["run_alphafold"]]:
    """Make a fasta file with chains: A: a designed binder and B: a PDZ domain."""
    output_dir = os.path.join(runtime.context.output_dir, "af", "fasta")
    pdb_id = runtime.context.input_pdb_filename.split(".")[0]
    design_seq = state.get("top_sequence")
    pep_seq = "EGYQDYEPEA"
    fasta_path = os.path.join(output_dir, f"{pdb_id}.fa")
    with open(fasta_path, "w") as f:
        f.write(f">pdz\n{design_seq}\n>pep\n{pep_seq}\n")
    return Command(
        update = {
            "top_sequence_fasta_filepath": fasta_filepath,
            "messages": ToolMessage(content=result, tool_call_id=tool_call["id"]),
        },
        goto = "task_sequence_generator"
    )


# run alphafold - s4
@tool
def run_alphafold(runtime: ToolRuntime[Context]) -> str:
    """Run AlphaFold to predict a fold for the given sequence."""
    base_path = runtime.context.base_path
    output_dir = runtime.context.output_dir
    target_fasta = state.get("top_sequence_fasta_filepath")
    result = subprocess.run([
        f"/bin/bash {base_path}/af2_multimer_reduced.sh",
        f"{output_dir}/af/fasta/",
        f"{target_fasta}.fa",
        f"{output_dir}/af/prediction/dimer_models/"
    ])
    return Command(
        update = {
            "messages": ToolMessage(content=result, tool_call_id=tool_call["id"]),
            "task_list": "run_alphafold"
        },
        goto = "task_sequence_generator"
    )


# get score - s5
@tool
def score_alphafold(runtime: ToolRuntime[Context]) -> str:
    """Get AlphaFold scores."""
    base_path = runtime.context.base_path
    output_dir = runtime.context.output_dir
    pass_num = state.get("pass_num")
    result = subprocess.run([
        f"python3 {base_path}/plddt_extract_pipeline.py",
        f"--path={base_path}",
        f"--iter={pass_num}",
        f"--out={output_dir}/af/prediction"
    ])
    return Command(
        update = {
            "messages": ToolMessage(content=result, tool_call_id=tool_call["id"]),
            "task_list": "score_alphafold"
        },
        goto = "task_sequence_generator"
    )


