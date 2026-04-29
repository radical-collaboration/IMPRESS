#!/bin/bash
set -euo pipefail

# AlphaFold2 structure prediction via LocalColabFold (pixi)
# Args: $1=colabfold_path $2=short_fasta $3=output_dir

colabfold_path="$1"
short_fasta="$2"
output_dir="$3"

module load cuda
source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

pixi run --manifest-path "$colabfold_path" \
    colabfold_batch \
    --model-type alphafold2 \
    --rank auto \
    --random-seed 999 \
    --save-all \
    --debug-logging \
    "$short_fasta" \
    "$output_dir"
