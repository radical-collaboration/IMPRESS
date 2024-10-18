# Installation instructions per platform

## Delta (NCSA)

```shell
export BASE_DIR=/scratch/bblj/matitov
export WORK_DIR=$BASE_DIR/impress
```

### Virtual environment

```shell
module load anaconda3_gpu

conda create -y -p $WORK_DIR/ve.impress python=3.9
eval "$(conda shell.posix hook)"
conda activate $WORK_DIR/ve.impress
```

RADICAL-Pilot (from RADICAL-Cybertools)
```shell
conda install -y -c conda-forge radical.pilot
```

PyRosetta
```shell
conda config --add channels https://conda.rosettacommons.org
conda install -y pyrosetta  # size: 1.4GB
```

### AlphaFold2

AlphaFold2 (AF) is not installed system-wise on Delta, but it is available 
through the corresponding container and its databases are uploaded into a 
shared space.

Delta adapted Dockerfile:
https://github.com/rhaas80/alphafold
(original: https://github.com/google-deepmind/alphafold/blob/main/docker/Dockerfile)

### Test individual packages

#### AlphaFold2

```shell
# af2 container
export AF_CONTAINER=/scratch/rhaas/SUP-5301/alphafold.sif
# af2 databases
export AF_DB=/scratch/rhaas/SUP-5301/database
# user-defined related directories
export AF_INPUTS=$BASE_DIR/alphafold/inputs
export AF_OUTPUTS=$BASE_DIR/alphafold/outputs
export AF_ETC=$BASE_DIR/alphafold/etc

# for test purposes local container was used
#   git clone https://github.com/rhaas80/alphafold
#   cd alphafold
#   docker build --no-cache -f docker/Dockerfile -t alphafold_delta .
#   docker buildx create --use --name alphafold_builder
#   docker buildx build --output=type=registry --platform linux/amd64 \
#                       -t mtitov/alphafold_delta -f docker/Dockerfile .
# locate at: /scratch/bblj/matitov/alphafold/alphafold_delta.sif

singularity run -B $AF_INPUTS:/inputs -B $AF_OUTPUTS:/outputs -B $AF_ETC:/etc \
                -B $AF_DB:/data --pwd /app/alphafold --nv $AF_CONTAINER \
    --data_dir=/data \
    --uniref90_database_path=/data/uniref90/uniref90.fasta \
    --mgnify_database_path=/data/mgnify/mgy_clusters_2022_05.fa \
    --template_mmcif_dir=/data/pdb_mmcif/mmcif_files/ \
    --obsolete_pdbs_path=/data/pdb_mmcif/obsolete.dat \
    --fasta_paths=/inputs/test.fasta \
    --output_dir=/outputs \
    --model_preset=multimer \
    --db_preset=reduced_dbs \
    --small_bfd_database_path=/data/small_bfd/bfd-first_non_consensus_sequences.fasta \
    --pdb_seqres_database_path=/data/pdb_seqres/pdb_seqres.txt \
    --uniprot_database_path=/data/uniprot/uniprot.fasta \
    --max_template_date=2020-12-01 \
    --use_gpu_relax=True


singularity run -B $AF_INPUTS:/inputs -B $AF_OUTPUTS:/outputs -B $AF_ETC:/etc \
                -B $AF_DB:/data --pwd /app/alphafold --nv $AF_CONTAINER \
    --data_dir=/data \
    --uniref90_database_path=/data/uniref90/uniref90.fasta \
    --mgnify_database_path=/data/mgnify/mgy_clusters_2022_05.fa \
    --template_mmcif_dir=/data/pdb_mmcif/mmcif_files/ \
    --obsolete_pdbs_path=/data/pdb_mmcif/obsolete.dat \
    --fasta_paths=/inputs/test.fasta \
    --output_dir=/outputs \
    --model_preset=multimer \
    --db_preset=full_dbs \
    --bfd_database_path=/data/bfd/bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt \
    --pdb_seqres_database_path=/data/pdb_seqres/pdb_seqres.txt \
    --uniprot_database_path=/data/uniprot/uniprot.fasta \
    --uniref30_database_path=/data/uniref30/UniRef30_2021_03 \
    --max_template_date=2020-12-01 \
    --use_gpu_relax=True
```

