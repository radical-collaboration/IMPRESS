#!/bin/sh -l
  
#SBATCH -A <your allocation>-gpu
#SBATCH --partition=gpu-debug
#SBATCH --nodes=1
#SBATCH --gres=gpu:2            
#SBATCH --ntasks=64
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --job-name impress_gpu
#SBATCH --mail-user=<your email address>    
#SBATCH --mail-type=ALL      # When to send emails (BEGIN, END, FAIL, ALL)

unset SLURM_EXPORT_ENV
module load anaconda
source activate base
conda activate /anvil/scratch/$USER/impress/ve.impress

export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python /anvil/scratch/$USER/impress/IMPRESS/src/rp/anvil/radical_pipeline_adaptive.py
