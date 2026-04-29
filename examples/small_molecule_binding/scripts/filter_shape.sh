#!/bin/bash
set -euo pipefail

# Interface shape complementarity analysis via PyRosetta
# Args: $1=pdb_directory $2=shape_output $3=ligand_params_path $4=interface_values_output

pdb_directory="$1"
shape_output="$2"
ligand_params_path="$3"
interface_values_output="$4"

SCRIPT_DIR="$(dirname "$0")"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python "$SCRIPT_DIR/filter_shape.py" \
    "$pdb_directory" \
    "$shape_output" \
    "$ligand_params_path" \
    "$interface_values_output"
