#!/bin/bash
set -euo pipefail

# Step 4: AlphaFold2 multimer prediction via ColabFold
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"

module load modtree/gpu
module load cuda/12.8.0
module load gcc/11.2.0
#source /anvil/scratch/x-mason/IMPRESS/.venv/bin/activate
source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

pixi run --manifest-path /anvil/scratch/x-mason/localcolabfold \
    colabfold_batch \
    --model-type alphafold2_multimer_v3 \
    --max-template-date 2020-12-01 \
    --rank multimer \
    --random-seed 999 \
    --save-all \
    --debug-logging \
    "$fasta_path" \
    "$output_dir"
