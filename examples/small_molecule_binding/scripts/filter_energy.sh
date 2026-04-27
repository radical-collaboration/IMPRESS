#!/bin/bash
set -euo pipefail

# Ligand energy filtering
# Args: $1=pdb_directory $2=output_file $3=output_energy_file $4=common_filenames_file $5=ligand_name

pdb_directory="$1"
output_file="$2"
output_energy_file="$3"
common_filenames_file="$4"
ligand_name="$5"

SCRIPT_DIR="$(dirname "$0")"

python "$SCRIPT_DIR/filter_energy.py" \
    "$pdb_directory" \
    "$output_file" \
    "$output_energy_file" \
    "$common_filenames_file" \
    "$ligand_name"
