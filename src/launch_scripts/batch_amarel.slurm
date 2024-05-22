#!/bin/sh

#SBATCH --job-name  "impress.rct"
#SBATCH --output    "slurm.rct.out"
#SBATCH --error     "slurm.rct.err"
#SBATCH --partition "p_sdk94_1"
#SBATCH --time      3-00:00:00
#SBATCH --ntasks    4
#SBATCH --gres      gpu:4
#SBATCH --mem       64G
#SBATCH --export    NONE
#SBATCH --exclusive

## venv activation
conda activate pyr
module load cuda/11.7.1

## RCT env
export RADICAL_PROFILE="TRUE"
export RADICAL_REPORT="TRUE"
export RADICAL_LOG_LVL="DEBUG"

python run_mpnn_entk.py

