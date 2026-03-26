#!/bin/bash
#SBATCH -N 1
#SBATCH -p GPU-shared
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=4
#SBATCH -A 
#SBATCH --time=16:00:00
#SBATCH --job-name isles
#SBATCH --mail-user=mh1314@scarletmail.rutgers.edu
#SBATCH --mail-type=ALL

set -e
source /jet/home/hooten/.bashrc


# 1 2 3 4
CHUNKNUM=5


# Step 1) Backbone generation
source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

FOUNDRYFILEPATH=/ocean/projects/dmr170002p/hooten/foundry.sif
RFDINPUTFILEPATH=mcsa_mod8-$CHUNKNUM.json
RFDOUTPUTDIR=outputs_rfd3

apptainer exec --nv $FOUNDRYFILEPATH rfd3 design \
out_dir=$RFDOUTPUTDIR \
inputs=$RFDINPUTFILEPATH \
skip_existing=False \
prevalidate_inputs=True \
diffusion_batch_size=10


# Step 2) Backbone postprocessing
source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python cif_to_pdb.py --input-dir outputs_rfd3/ --output-dir outputs_rfd3/


# Step 3) Sequence prediction
source /ocean/projects/dmr170002p/hooten/LigandMPNN/.venv/bin/activate

LMPNNOUTPUTDIR=outputs_lmpnn
MPNNDIR=/ocean/projects/dmr170002p/hooten/LigandMPNN

python $MPNNDIR/run.py \
--model_type "ligand_mpnn" \
--checkpoint_path_sc $MPNNDIR/model_params/ligandmpnn_sc_v_32_002_16.pt \
--checkpoint_ligand_mpnn $MPNNDIR/model_params/ligandmpnn_v_32_010_25.pt \
--seed 111 \
--out_folder $LMPNNOUTPUTDIR \
--number_of_batches 4 \
--batch_size 1 \
--temperature 0.1 \
--pdb_path_multi "./lmpnn_batch_jsons/batch_pdbs_mod8-${CHUNKNUM}.json" \
--fixed_residues_multi "./lmpnn_batch_jsons/batch_fixed_res_mod8-${CHUNKNUM}.json"



# Step 4) Sequence postprocessing
source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python split_seqs.py --input_dir outputs_lmpnn/seqs/ --output_dir outputs_lmpnn/seqs_split/



# Step 5) Fold prediction
source /ocean/projects/dmr170002p/hooten/chai-lab/.venv/bin/activate

CHAIINPUTDIR=outputs_lmpnn/seqs_split/
CHAIOUTPUTDIR=chai1_outputs

python chai_batch.py \
--input_dir $CHAIINPUTDIR \
--output_dir $CHAIOUTPUTDIR \
--use_msa_server
