#!/bin/bash
export TF_FORCE_UNIFIED_MEMORY=1
export XLA_PYTHON_CLIENT_MEM_FRACTION=4.0
export DB_DIR="/projectsn/datasets/alphafold/dbs2022.03"
#export DB_DIR="/projects/community/alphafold/dbs"
export BIN_DIR="/projects/community/ai-fold/2021/bd387/envs/af2.2/bin/"
#export small_bfd_database_path="/projects/community/alphafold/dbs/reduced_dbs"
export PATH=/usr/lpp/mmfs/bin:/usr/local/bin:/usr/bin:/usr/local/sbin:/usr/sbin
module purge
module load gcc/11.2 openmpi
module use /projects/community/modulefiles
module load cuda/11.4.1
module load ai-fold
source activate af2.2

#module purge
#module use /projects/community/modulefiles
#module load singularity/3.6.4
#module load alphafold

input_fasta_file=$1
output_data_dir=$2

echo "--------------------------------" 
date
echo "--begin time---" 
bdate=$(date +%s)
echo $bdate 

echo "input fasta file"
echo $input_fasta_file
echo "Output data directory"
echo $output_data_dir

CUDA_VISIBLE_DEVICES=0
python /projects/community/ai-fold/2021/bd387/envs/af2.2/alphafold/run_alphafold.py \
    --data_dir=$DB_DIR \
    --uniref90_database_path=$DB_DIR/uniref90/uniref90.fasta \
    --mgnify_database_path=$DB_DIR/mgnify/mgy_clusters_2018_12.fa \
    --template_mmcif_dir=$DB_DIR/pdb_mmcif/mmcif_files/ \
    --obsolete_pdbs_path=$DB_DIR/pdb_mmcif/obsolete.dat \
    --fasta_paths=$input_fasta_file \
    --output_dir=$output_data_dir \
    --model_preset=multimer \
    --db_preset=reduced_dbs \
    --small_bfd_database_path=$DB_DIR/small_bfd/bfd-first_non_consensus_sequences.fasta \
    --pdb_seqres_database_path=$DB_DIR/pdb_seqres/pdb_seqres.txt \
    --uniprot_database_path=$DB_DIR/uniprot/uniprot.fasta \
    --max_template_date=2020-12-01 \
    --use_gpu_relax=TRUE \
    --num_multimer_predictions_per_model=2 \

    
    
    
    
#    --kalign_binary_path=$BIN_DIR/kalign \
#    --jackhmmer_binary_path=$BIN_DIR/jackhmmer \
#    --hhblits_binary_path=$BIN_DIR/hhblits \
#    --hhsearch_binary_path=$BIN_DIR/hhsearch \
#    --pdb_seqres_database_path=$DB_DIR/pdb_seqres/pdb_seqres.txt \
    
    
    
    
    
    
#singularity run -B $ALPHAFOLD_DATA_PATH:/data -B .:/etc --pwd /app/alphafold --nv $CONTAINERDIR/alphafoldmm.sif \
#    --data_dir=/data \
#    --uniref90_database_path=/data/uniref90/uniref90.fasta \
#    --mgnify_database_path=/data/mgnify/mgy_clusters_2018_12.fa \
#    --template_mmcif_dir=/data/pdb_mmcif/mmcif_files/ \
#    --obsolete_pdbs_path=/data/pdb_mmcif/obsolete.dat \
#    --fasta_paths=/home/ja961/Khare/PDZ_Domains/$input_fasta_file \
#    --output_dir=/scratch/ja961/$output_data_dir \
#    --model_preset=multimer \
#    --db_preset=reduced_dbs \
#    --small_bfd_database_path=/data/small_bfd/bfd-first_non_consensus_sequences.fasta \
#    --pdb_seqres_database_path=/data/pdb_seqres/pdb_seqres.txt \
#    --uniprot_database_path=/data/uniprot/uniprot.fasta \
#    --max_template_date=2020-12-01 \
#    --use_gpu_relax=FALSE \
#    --num_multimer_predictions_per_model=2
echo "--end Time---" 
edate=$(date +%s)
echo $edate 
echo "--time spend---" 
echo $(( $bdate - $edate ))
echo "--------------------------------"