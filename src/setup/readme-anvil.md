# Installation instructions

## A. Platform specific steps

### Anvil (Purdue)
```shell
export BASE_DIR=/anvil/scratch/$USER
mkdir $BASE_DIR/impress
export WORK_DIR=$BASE_DIR/impress
mkdir $WORK_DIR/inputs
mkdir $WORK_DIR/outputs
cd $WORK_DIR
git clone git@github.com:radical-collaboration/IMPRESS.git
git checkout fix/anvil_netface
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

**NOTE:** AlphaFold2 (AF) is installed system-wise on Anvil, and can be used by
loading the designated modules below:

```shell
module load  biocontainers/default
module load  alphafold/2.3.1
```

### Alphafold V2

```shell
# Copy the input file before running AlphaFold for testing.
cp $WORK_DIR/IMPRESS/src/setup/test.fasta $WORK_DIR/inputs

# run_alphafold.sh is available in the $PATH once you load the modules above
/usr/bin/singularity exec --nv /apps/biocontainers/images/tacc_alphafold:2.3.1.sif run_alphafold.sh \
--db_preset=full_dbs \
--fasta_paths=$WORK_DIR/inputs/test.fasta \
--output_dir=$WORK_DIR/outputs \
--bfd_database_path=/anvil/datasets/alphafold/db_20230311/bfd/bfd_metaclust_clu_complete_id30_c90_final_seq.sorted_opt \
--data_dir=/anvil/datasets/alphafold/db_20230311/ \
--uniref90_database_path=/anvil/datasets/alphafold/db_20230311/uniref90/uniref90.fasta \
--mgnify_database_path=/anvil/datasets/alphafold/db_20230311/mgnify/mgy_clusters_2022_05.fa \
--uniref30_database_path=/anvil/datasets/alphafold/db_20230311/uniref30/UniRef30_2021_03 \
--pdb_seqres_database_path=/anvil/datasets/alphafold/db_20230311/pdb_seqres/pdb_seqres.txt \
--uniprot_database_path=/anvil/datasets/alphafold/db_20230311/uniprot/uniprot.fasta \
--template_mmcif_dir=/anvil/datasets/alphafold/db_20230311/pdb_mmcif/mmcif_files \
--obsolete_pdbs_path=/anvil/datasets/alphafold/db_20230311/pdb_mmcif/obsolete.dat \
--hhblits_binary_path=/usr/bin/hhblits \
--hhsearch_binary_path=/usr/bin/hhsearch \
--kalign_binary_path=/usr/bin/kalign \
--max_template_date=2022-12-01 \
--use_gpu_relax=True \
--model_preset=multimer \
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

### Running jobs on Anvil

For full documentation, visit the
https://www.rcac.purdue.edu/knowledge/anvil/run

```shell

# Log in to Anvil
ssh -l my-x-anvil-username anvil.rcac.purdue.edu
```

Running an Interactive Job on Anvil

```shell

# Start an Interactive Session
# Check your allocation name on the Anvil dashboard, then run:
sinteractive -p wholenode -N <number of nodes> -n <number of cores> -A oneofyourallocations

# Load Required Modules and Activate Environment
module load biocontainers/default
module load alphafold/2.3.1
module load anaconda
conda activate $WORK_DIR/ve.impress

# Run the script
python <script name>
```

Running a Batch Job with sbatch

```shell

# Customize one of example of Slurm job submission file as needed 
https://github.com/radical-collaboration/IMPRESS/blob/feature/anvil_af2/src/rp/anvil/gpu_run.sbatch 
https://github.com/radical-collaboration/IMPRESS/blob/feature/anvil_af2/src/rp/anvil/cpu_run.sbatch 

# Submit the job using the following command
sbatch <script name> 

```