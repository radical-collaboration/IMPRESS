#!/bin/bash
set -euo pipefail

# Step 7: Fold prediction via Chai-lab
# Args: $1=scripts_path $2=input_dir $3=output_dir

scripts_path="$1"
input_dir="$2"
output_dir="$3"

source /ocean/projects/dmr170002p/hooten/chai-lab/.venv/bin/activate

python "$scripts_path/chai_batch.py" \
    --input_dir "$input_dir" \
    --output_dir "$output_dir" \
    --use_msa_server
