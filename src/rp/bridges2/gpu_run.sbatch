#!/bin/sh -l
  
#SBATCH -A <your GPU allocation>
#SBATCH --partition=GPU-shared
#SBATCH --nodes=1
#xSBATCH --gpus=v100-32:8   
#SBATCH --gres      gpu:4   
#SBATCH --ntasks 20
#SBATCH --cpus-per-task=1
#SBATCH --time=20:00:00
#SBATCH --job-name bridges2_gpu
#SBATCH --mail-user=<your email address>   
#SBATCH --mail-type=ALL      # When to send emails (BEGIN, END, FAIL, ALL)

unset SLURM_EXPORT_ENV
module load anaconda3
source activate base
conda activate /jet/home/$USER/impress/ve.impress

export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python /jet/home/$USER/impress/IMPRESS/src/rp/bridges2/radical_pipeline_adaptive.py