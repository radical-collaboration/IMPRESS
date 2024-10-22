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

```shell
# RADICAL-Pilot (from RADICAL-Cybertools)
conda install -y radical.pilot -c conda-forge
# PyRosetta
conda install -y pyrosetta -c https://conda.rosettacommons.org  # size: 1.4GB
# Torch (for ProteinMPNN)
conda install -y pytorch torchaudio torchvision cudatoolkit=11.3 -c pytorch
```

- AlphaFold2 (AF) is not installed system-wise on Delta, but it is available 
through the corresponding container and its databases are uploaded into a 
shared space.  GitHub repo for the Delta adapted Dockerfile:
https://github.com/rhaas80/alphafold
(original: https://github.com/google-deepmind/alphafold/blob/main/docker/Dockerfile)

- ProteinMPNN GitHub repo: https://github.com/dauparas/ProteinMPNN

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
#   docker build --no-cache -f docker/Dockerfile -t mtitov/alphafold_delta .
#   docker buildx create --use --name alphafold_builder
#   docker buildx build --output=type=registry --platform linux/amd64 \
#                       -t mtitov/alphafold_delta -f docker/Dockerfile .
# located at: /scratch/bblj/matitov/alphafold/alphafold_delta.sif

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

#### PyRosetta

```shell
# virtual environment should be already activated
#   module load anaconda3_gpu
#   eval "$(conda shell.posix hook)"
#   conda activate $WORK_DIR/ve.impress

cd $WORK_DIR
mkdir -p joey_utils
```

```python
from pyrosetta import *
init()
from joey_utils import fast_relax_mover
pose=pose_from_pdb('FILEPATH')
fr=fast_relax_mover()
fr.apply(pose)
pose.dump_pdb('OUTPATH')
```

#### ProteinMPNN

```shell
# virtual environment should be already activated
#   module load anaconda3_gpu
#   eval "$(conda shell.posix hook)"
#   conda activate $WORK_DIR/ve.impress

cd $WORK_DIR
git clone https://github.com/dauparas/ProteinMPNN.git
cd ProteinMPNN/examples
./submit_example_1.sh  # simple monomer example
```
