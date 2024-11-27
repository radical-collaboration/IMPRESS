#!/bin/bash
export BASE_DIR=/u/ja961/IMPRESS
#export WORK_DIR=$BASE_DIR/IMPRESS
#export AF_INPUTS=$BASE_DIR/alphafold/inputs
#export AF_OUTPUTS=$BASE_DIR/alphafold/outputs
export AF_ETC=$BASE_DIR/alphafold/etc
#export AF_CONTAINER=/scratch/bblj/matitov/alphafold/alphafold_delta.sif
export AF_CONTAINER=/scratch/rhaas/SUP-5301/alphafold.sif
export AF_DB=/scratch/rhaas/SUP-5301/database
echo $BASE_DIR
# mkdir -p $BASE_DIR/alphafold/inputs $BASE_DIR/alphafold/outputs
# cat > $BASE_DIR/alphafold/inputs/test.fasta <<EOF
# >3SFJ_1|Chains A, C|Tax1-binding protein 3|Homo sapiens (9606)
# VTAVVQRVEIHKLRQGENLILGFSIGGGIDQDPSQNPFSEDKTDKGIYVTRVSEGGPAEIAGLQIGDKIMQVNGWDMTMVTHDQARKRLTKRSEEVVRLLVTRQ
# >3SFJ_2|Chains B, D|decameric peptide iCAL36|
# ANSRWPTSII
# EOF
#--pdb_seqres_database_path=$AF_DB/pdb_seqres/pdb_seqres.txt
#module load anaconda3_gpu
#source activate rp
input_fasta_file=$1
output_data_dir=$2
singularity run -B $input_fasta_file -B $output_data_dir -B $AF_ETC:/etc -B $AF_DB:/data --pwd /app/alphafold --nv $AF_CONTAINER \
    --data_dir=/data \
    --uniref90_database_path=/data/uniref90/uniref90.fasta \
    --mgnify_database_path=/data/mgnify/mgy_clusters_2022_05.fa \
    --template_mmcif_dir=/data/pdb_mmcif/mmcif_files/ \
    --obsolete_pdbs_path=/data/pdb_mmcif/obsolete.dat \
    --fasta_paths=$input_fasta_file \
    --output_dir=$output_data_dir \
    --model_preset=multimer \
    --db_preset=reduced_dbs \
    --small_bfd_database_path=/data/small_bfd/bfd-first_non_consensus_sequences.fasta \
    --uniprot_database_path=/data/uniprot/uniprot.fasta \
    --pdb_seqres_database_path=/data/pdb_seqres/pdb_seqres.txt \
    --max_template_date=2020-12-01 \
    --use_gpu_relax=True
