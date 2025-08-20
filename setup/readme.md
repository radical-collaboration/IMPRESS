# Installation instructions

## A. Platform specific steps

### Delta (NCSA)

```shell
export BASE_DIR=/scratch/bblj/matitov
export WORK_DIR=$BASE_DIR/impress

# ensure that the working directory is created
mkdir -p $WORK_DIR

# load python module (DeltaGPU specific)
module load anaconda3_gpu

# AlphaFold2 container and databases
export AF_CONTAINER=/scratch/rhaas/SUP-5301/alphafold.sif
export AF_DB=/scratch/rhaas/SUP-5301/database
```

**NOTE:** AlphaFold2 (AF) is not installed system-wise on Delta, but it is
available through the corresponding container and its databases are uploaded 
into a shared space. GitHub repo for the Delta adapted Dockerfile:
https://github.com/rhaas80/alphafold

**NOTE:** For test purposes "local" AF container was used (located at: 
`/scratch/bblj/matitov/alphafold/alphafold_delta.sif`)

```shell
# steps to build local (own) container
git clone https://github.com/rhaas80/alphafold
cd alphafold
docker build --no-cache -f docker/Dockerfile -t mtitov/alphafold_delta .
docker buildx create --use --name alphafold_builder
docker buildx build --output=type=registry --platform linux/amd64 \
                    -t mtitov/alphafold_delta -f docker/Dockerfile .
```

## B. Environment setup

```shell
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

# OR use a corresponding file with the dependencies:
#   conda env update -p $WORK_DIR/ve.impress --file environment.yml
```
- AlphaFold2 Docker: https://github.com/google-deepmind/alphafold/tree/main/docker
- ProteinMPNN: https://github.com/dauparas/ProteinMPNN

## C. Test individual tools

Platform specific acquiring resources using an interactive job:
- **Delta**
  ```shell
  srun --time=00:10:00 --nodes=1 --tasks-per-node=1 --cpus-per-task=64 \
       --exclusive --account=bblj-delta-gpu --partition=gpuA100x4 --gpus=4 \
       --mem=0 --pty /bin/bash
  # load python module
  module load anaconda3_gpu
  ```

**NOTE:** before running any tests, virtual environment should be activated
```shell
eval "$(conda shell.posix hook)"
conda activate $WORK_DIR/ve.impress
```

### AlphaFold2

```shell
export AF_INPUTS=$BASE_DIR/alphafold/inputs
export AF_OUTPUTS=$BASE_DIR/alphafold/outputs
export AF_ETC=$BASE_DIR/alphafold/etc

mkdir -p $BASE_DIR/alphafold/inputs $BASE_DIR/alphafold/outputs
cat > $BASE_DIR/alphafold/inputs/test.fasta <<EOF
>3SFJ_1|Chains A, C|Tax1-binding protein 3|Homo sapiens (9606)
VTAVVQRVEIHKLRQGENLILGFSIGGGIDQDPSQNPFSEDKTDKGIYVTRVSEGGPAEIAGLQIGDKIMQVNGWDMTMVTHDQARKRLTKRSEEVVRLLVTRQ
>3SFJ_2|Chains B, D|decameric peptide iCAL36|
ANSRWPTSII
EOF

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

### PyRosetta

```shell
cd $WORK_DIR
# get PDB file for test purposes
wget https://files.rcsb.org/download/3SFJ.pdb -O test.pdb
```

```python
from pyrosetta import init, pose_from_pdb
init()
# available within the IMPRESS package
from joey_utils import fast_relax_mover
pose = pose_from_pdb('test.pdb')
fr = fast_relax_mover()
fr.apply(pose)
pose.dump_pdb('OUTPUT')
```

### ProteinMPNN

```shell
cd $WORK_DIR
git clone https://github.com/dauparas/ProteinMPNN.git
cd ProteinMPNN/examples
chmod +x submit_example_1.sh
# remove SLURM related lines in the test script:
#    sed -i 2,8d submit_example_1.sh
./submit_example_1.sh  # simple monomer example
```

