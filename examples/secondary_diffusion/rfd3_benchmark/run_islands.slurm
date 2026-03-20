#!/bin/bash
#SBATCH -N 1
#SBATCH -p GPU-shared
#SBATCH --gpus-per-node=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH -A dmr170002p
#SBATCH --time=00:30:00
#SBATCH --job-name isles
#SBATCH --mail-user=mh1314@scarletmail.rutgers.edu
#SBATCH --mail-type=ALL

set -e

source /jet/home/hooten/.bashrc

#source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate
#FOUNDRYFILEPATH=/ocean/projects/dmr170002p/hooten/foundry.sif
#RFDINPUTFILEPATH=mcsa_41_oneinput_corrected.json
#RFDOUTPUTDIR=outputs_rfd3
#apptainer exec --nv $FOUNDRYFILEPATH rfd3 design \
#out_dir=$RFDOUTPUTDIR \
#inputs=$RFDINPUTFILEPATH \
#skip_existing=False \
#prevalidate_inputs=True \
#diffusion_batch_size=10

#LMPNNINPUTFILEPATH=lmpnn_batch_config.json
#LMPNNOUTPUTDIR=outputs_lmpnn
#MPNNDIR=/ocean/projects/dmr170002p/hooten/LigandMPNN
#source /ocean/projects/dmr170002p/hooten/LigandMPNN/.venv/bin/activate
#python $MPNNDIR/run.py \
#--model_type \"ligand_mpnn\" \
#--checkpoint_path_sc $MPNNDIR/model_params/ligandmpnn_sc_v_32_002_16.pt \
#--checkpoint_ligand_mpnn $MPNNDIR/model_params/ligandmpnn_v_32_010_25.pt \
#--seed 111 \
#--json_path $LMPNNINPUTFILEPATH \
#--out_folder $LMPNNOUTPUTDIR \
#--number_of_batches 8 \
#--batch_size 1 \
#--temperature 0.1 

CHAIOUTPUTDIR=chai1_outputs
CHAIINPUTDIR=outputs_lmpnn/seqs_split_small
source /ocean/projects/dmr170002p/hooten/chai-lab/.venv/bin/activate
python chai_batch.py \
--input_dir $CHAIINPUTDIR \
--output_dir $CHAIOUTPUTDIR \
--use_msa_server
