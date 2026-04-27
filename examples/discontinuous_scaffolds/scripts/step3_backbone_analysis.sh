#!/bin/bash
set -euo pipefail

# Step 3: Backbone analysis + plot
# Args: $1=scripts_path $2=pdb_dir $3=output_csv $4=output_dir $5=island_counts_csv

scripts_path="$1"
pdb_dir="$2"
output_csv="$3"
output_dir="$4"
island_counts_csv="$5"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$scripts_path/analysis_backbone.py" \
    "$pdb_dir" \
    --output "$output_csv"

#python "$scripts_path/plot_backbone_analysis.py" \
#    "$output_csv" \
#    "$island_counts_csv" \
#    --output-dir "$output_dir"
