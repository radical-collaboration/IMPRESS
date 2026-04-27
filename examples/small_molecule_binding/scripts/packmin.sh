#!/bin/bash
set -euo pipefail

# Side-chain packing and minimization via PyRosetta
# Args: $1=pdb_path $2=lig_path $3=output_dir

pdb_path="$1"
lig_path="$2"
output_dir="$3"

SCRIPT_DIR="$(dirname "$0")"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$SCRIPT_DIR/packmin.py" \
    "$pdb_path" \
    -lig "$lig_path" \
    --out_dir "$output_dir"
