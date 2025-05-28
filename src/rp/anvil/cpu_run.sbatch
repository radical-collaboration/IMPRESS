#!/bin/sh -l
  
#SBATCH -A <your allocation>
#SBATCH --partition debug   #wholenode
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --time=30:00:00
#SBATCH --job-name impress_cpu
#SBATCH --mail-user=<your email address>  
#SBATCH --mail-type=ALL    # When to send emails (BEGIN, END, FAIL, ALL)

module load anaconda
source activate base
conda activate /anvil/scratch/$USER/impress/ve.impress

# export RADICAL_PROFILE="TRUE"
# export RADICAL_REPORT="TRUE"
# export RADICAL_LOG_LVL="DEBUG"

python /anvil/scratch/$USER/impress/IMPRESS/src/rp/anvil/radical_pipeline_adaptive.py
