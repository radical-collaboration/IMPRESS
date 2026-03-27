#!/bin/bash
set -euo pipefail

# Step 5: Sequence postprocessing — split_seqs
# Args: $1=scripts_path $2=seqs_dir $3=split_dir

scripts_path="$1"
seqs_dir="$2"
split_dir="$3"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$scripts_path/split_seqs.py" \
    --input_dir "$seqs_dir" \
    --output_dir "$split_dir"
