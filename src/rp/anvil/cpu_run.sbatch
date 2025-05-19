#!/bin/sh -l
  
#SBATCH -A <your allocation>
#SBATCH --partition wholenode
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=128  
#SBATCH --time=48:00:00
#SBATCH --job-name impress_cpu
#SBATCH --mail-user=email address>   
#SBATCH --mail-type=ALL    # When to send emails (BEGIN, END, FAIL, ALL)

module load anaconda
source activate base
conda activate /anvil/scratch/$USER/impress/ve.impress

export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python /anvil/scratch/$USER/impress/IMPRESS/src/rp/anvil/radical_pipeline_adaptive.py
