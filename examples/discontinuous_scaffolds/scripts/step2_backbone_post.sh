#!/bin/bash
set -euo pipefail

# Step 2: Backbone postprocessing — CIF.GZ → PDB (in-place)
# Args: $1=scripts_path $2=rfd3_out_dir

scripts_path="$1"
rfd3_out_dir="$2"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$scripts_path/cif_to_pdb.py" \
    --input-dir "$rfd3_out_dir" \
    --output-dir "$rfd3_out_dir"
