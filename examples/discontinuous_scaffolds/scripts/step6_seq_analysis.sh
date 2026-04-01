#!/bin/bash
set -euo pipefail

# Step 6: Sequence analysis + plot
# Args: $1=scripts_path $2=seqs_split_dir $3=output_csv $4=output_dir $5=island_counts_csv

scripts_path="$1"
seqs_split_dir="$2"
output_csv="$3"
output_dir="$4"
island_counts_csv="$5"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$scripts_path/analysis_sequence.py" \
    "$seqs_split_dir" \
    --output "$output_csv"

#python "$scripts_path/plot_sequence_analysis.py" \
#    "$output_csv" \
#    "$island_counts_csv" \
#    --output-dir "$output_dir"
