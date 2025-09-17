#!/bin/bash
# run ligandmpnn

pdb_path=$1
output_dir=$2
lmpnn_dir=$3

echo "A16" > fixed_residues.txt
FIXED=`cat fixed_residues.txt`
set -x
python $lmpnn_dir/run.py \
    --model_type "ligand_mpnn" \
    --checkpoint_path_sc $lmpnn_dir/model_params/ligandmpnn_sc_v_32_002_16.pt \
    --checkpoint_ligand_mpnn $lmpnn_dir/model_params/ligandmpnn_v_32_010_25.pt \
    --seed 111 \
    --pdb_path $pdb_path \
    --out_folder $output_dir \
    --pack_side_chains 1 \
    --number_of_batches 1 \
    --batch_size 1 \
    --number_of_packs_per_design 1 \
    --pack_with_ligand_context 1 \
    --fixed_residues "$FIXED" \
    --repack_everything 1 \
    --temperature 0.1
#    --bias_AA "A:10.0"


