#!/bin/bash
set -euo pipefail

# Sequence design via LigandMPNN
# Args: $1=mpnn_dir $2=pdb_path $3=output_dir $4=n_batches $5=fixed_residues (or "")

mpnn_dir="$1"
pdb_path="$2"
output_dir="$3"
n_batches="$4"
batch_size="$5"
fixed_residues="${6:-}"

source /anvil/projects/x-nairr240405/mason/LigandMPNN/.venv/bin/activate

python "$mpnn_dir/run.py" \
    --model_type "ligand_mpnn" \
    --checkpoint_path_sc "$mpnn_dir/model_params/ligandmpnn_sc_v_32_002_16.pt" \
    --checkpoint_ligand_mpnn "$mpnn_dir/model_params/ligandmpnn_v_32_010_25.pt" \
    --seed 111 \
    --pdb_path "$pdb_path" \
    --out_folder "$output_dir" \
    --pack_side_chains 1 \
    --number_of_batches "$n_batches" \
    --batch_size "$batch_size" \
    --number_of_packs_per_design 1 \
    --pack_with_ligand_context 1 \
    --repack_everything 1 \
    --temperature 0.1 \
    ${fixed_residues:+--fixed_residues "$fixed_residues"}
