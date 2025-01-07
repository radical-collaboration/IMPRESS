#!/bin/bash

# have this *first* since they change the WORK env variable in jobs
# module reset
# module load cuda/12.3.0

set -e
set -x

# work and upperdir need to be on same file system
WORK=/tmp/work
UPPER=/tmp/upper
mkdir -p $WORK $UPPER

export XLA_PYTHON_CLIENT_PREALLOCATE="false"
export XLA_PYTHON_CLIENT_MEM_FRACTION=".75"
export XLA_PYTHON_CLIENT_ALLOCATOR="platform"

# the input fasta file in inputs/
#INPUT=3SFJ_1.fasta     # <-- Change this to your fasta file

  #-B database.squashfs:/database:image-src=/
INPUT_FASTA_FILE_DIR=$1
INPUT_FASTA_FILE_NAME=$2
OUTPUT_DATA_DIR=$3

apptainer run --nv \
  --bind $INPUT_FASTA_FILE_DIR:/fasta \
  --bind $OUTPUT_DATA_DIR:/dimer_models \
  --bind /scratch/rhaas/SUP-5301/database:/database \
  /scratch/rhaas/SUP-5301/alphafold.sif \
  --data_dir=/database \
  --uniref90_database_path=/database/uniref90/uniref90.fasta \
  --mgnify_database_path=/database/mgnify/mgy_clusters_2022_05.fa \
  --template_mmcif_dir=/database/pdb_mmcif/mmcif_files/ \
  --obsolete_pdbs_path=/database/pdb_mmcif/obsolete.dat \
  --fasta_paths=/fasta/$INPUT_FASTA_FILE_NAME \
  --output_dir=/dimer_models \
  --model_preset=multimer \
  --db_preset=reduced_dbs \
  --small_bfd_database_path=/database/small_bfd/bfd-first_non_consensus_sequences.fasta \
  --uniprot_database_path=/database/uniprot/uniprot.fasta \
  --pdb_seqres_database_path=/database/pdb_seqres/pdb_seqres.txt \
  --max_template_date=2020-12-01 \
  --use_gpu_relax=True
