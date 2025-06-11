# Installation instructions

## A. Platform specific steps

### Bridges2
```shell
export BASE_DIR=/jet/home//$USER
mkdir $BASE_DIR/impress
export WORK_DIR=$BASE_DIR/impress
mkdir $WORK_DIR/inputs
mkdir $WORK_DIR/outputs
cd $WORK_DIR
git clone git@github.com:radical-collaboration/IMPRESS.git
git checkout feature/bridges2_af2
```

# Environment Setup

```shell
module load anaconda
conda create -y -p $WORK_DIR/ve.impress python=3.9
conda activate $WORK_DIR/ve.impress
```

```shell
# Required for pandas.read_pickle
conda install jax=0.3.25
# biopandas are required for plddt_extract_pipeline.py 
conda install -y biopandas -c conda-forge
# RADICAL-Pilot (from RADICAL-Cybertools)
conda install -y radical.pilot -c conda-forge
# cudatoolkit for GPU support
conda install cudatoolkit=11.3 -c conda-forge
# PyRosetta
conda install -y pyrosetta -c https://conda.rosettacommons.org  # size: 1.4GB
# Torch (for ProteinMPNN)
conda install -y pytorch torchaudio torchvision cudatoolkit -c pytorch 

# OR use a corresponding file with the dependencies:
#   conda env update -p $WORK_DIR/ve.impress --file environment.yml
```

**NOTE:** AlphaFold2 (AF) is not installed on bridges2, so we have built it from Docker image:

```shell
cd /ocean/projects/dmr170002p/goliyad
singularity build --disable-cache alphafold.sif docker://mtitov/alphafold_delta
ls -ltr alphafold.sif
-rwxr-xr-x 1 goliyad dmr170002p 7937445888 Jun  4 11:14 alphafold.sif

```

### Alphafold test

```shell
# Copy the input file before running AlphaFold for testing.
cp $WORK_DIR/IMPRESS/src/setup/test.fasta $WORK_DIR/inputs

singularity run --nv \
  --bind $WORK_DIR/inputs/test.fasta:/fasta \
  --bind $WORK_DIR/outputs:/dimer_models \
  --bind /ocean/datasets/community/alphafold/v2.3.2/:/database \
  /ocean/projects/dmr170002p/goliyad/alphafold.sif  \
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
   --use_gpu_relax=False \
   --num_multimer_predictions_per_model=1 
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

### Running sbatch jobs on Bridges2

For full documentation, visit the
https://www.psc.edu/resources/bridges-2/user-guide/


```shell

# Customize one of example of Slurm job submission file as needed 
https://github.com/radical-collaboration/IMPRESS/blob/feature/bridges2_af2/src/rp/bridges2/gpu_run.sbatch 
https://github.com/radical-collaboration/IMPRESS/blob/feature/bridges2_af2/src/rp/bridges2/cpu_run.sbatch 

# Submit the job using the following command
sbatch <script name> 

```