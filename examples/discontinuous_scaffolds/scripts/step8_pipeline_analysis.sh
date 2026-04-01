#!/bin/bash
set -euo pipefail

# Step 8: Pipeline analysis + plot campaign
# Args: $1=scripts_path $2=chai_out_dir $3=output_csv $4=output_dir $5=mcsa_pdb_dir $6=island_counts_csv $7=rmsd_threshold

scripts_path="$1"
chai_out_dir="$2"
output_csv="$3"
output_dir="$4"
mcsa_pdb_dir="$5"
island_counts_csv="$6"
rmsd_threshold="$7"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$scripts_path/analysis.py" \
    "$chai_out_dir" \
    --output "$output_csv" \
    --input-pdb-dir "$mcsa_pdb_dir"

#python "$scripts_path/plot_campaign.py" \
#    "$output_csv" \
#    "$island_counts_csv" \
#    --output-dir "$output_dir" \
#    --threshold "$rmsd_threshold"
