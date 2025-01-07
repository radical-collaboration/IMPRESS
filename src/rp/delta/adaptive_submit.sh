#!/bin/bash

#SBATCH --job-name  "impress.rct"
#SBATCH --output    "slurm.rct.out"
#SBATCH --error     "slurm.rct.err"
#SBATCH --partition "gpuA100x4"
#SBATCH --time      48:00:00
#SBATCH --ntasks    4
#SBATCH --gres      gpu:4
#SBATCH --mem       64G
#SBATCH --export    NONE
#SBATCH --exclusive
#SBATCH --account   bblj-delta-gpu
unset SLURM_EXPORT_ENV
module load anaconda3_gpu
eval "$(conda shell.posix hook)"
source activate /u/ja961/ve.impress/

export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python radical_pipeline_adaptive.py
