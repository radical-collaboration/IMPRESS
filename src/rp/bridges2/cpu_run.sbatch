#!/bin/sh -l
  
#SBATCH -A <your allocation>
#SBATCH --partition RM
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=128
#SBATCH --time=30:00:00
#SBATCH --job-name impress_cpu
#SBATCH --mail-user=<your email address>  
#SBATCH --mail-type=ALL    # When to send emails (BEGIN, END, FAIL, ALL)

unset SLURM_EXPORT_ENV
module load anaconda3
source activate base
conda activate /jet/home/$USER/impress/ve.impress

export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python /jet/home/$USER/impress/IMPRESS/src/rp/bridges2/radical_pipeline_adaptive.py
