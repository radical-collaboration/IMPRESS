#!/bin/bash
set -euo pipefail

# Step 4: Sequence prediction via LigandMPNN
# Args: $1=mpnn_dir $2=output_dir $3=lmpnn_pdb_multi_json $4=lmpnn_fixed_res_json

mpnn_dir="$1"
output_dir="$2"
lmpnn_pdb_multi_json="$3"
lmpnn_fixed_res_json="$4"
num_batches="$5"

source /ocean/projects/dmr170002p/hooten/LigandMPNN/.venv/bin/activate

python "$mpnn_dir/run.py" \
    --model_type ligand_mpnn \
    --checkpoint_path_sc "$mpnn_dir/model_params/ligandmpnn_sc_v_32_002_16.pt" \
    --checkpoint_ligand_mpnn "$mpnn_dir/model_params/ligandmpnn_v_32_010_25.pt" \
    --seed 111 \
    --out_folder "$output_dir" \
    --number_of_batches "$num_batches" \
    --batch_size 1 \
    --temperature 0.1 \
    --pdb_path_multi "$lmpnn_pdb_multi_json" \
    --fixed_residues_multi "$lmpnn_fixed_res_json"
