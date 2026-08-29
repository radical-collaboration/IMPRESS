#!/bin/bash
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=4
#SBATCH --cpus-per-task=16
#SBATCH --gpus=4
#SBATCH --exclusive
#SBATCH --time=00:30:00
#SBATCH --job-name=impress_protein
#SBATCH --mail-user=mariya.goliyad@rutgers.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err

set -e

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH}

# ── Paths — edit these when moving to a different system ─────────────────────
: "${SCRATCH:?SCRATCH is not set (e.g. export SCRATCH=/scratch/bblj)}"
export MPNN_PATH="$SCRATCH/$USER/ProteinMPNN"
# Switch activation command below if using conda instead of venv
IMPRESS_PRE_EXEC="source $HOME/ve/impress/bin/activate"
export AF2_DATABASE="/scratch/rhaas/SUP-5301/database"
export AF2_SIF="/scratch/rhaas/SUP-5301/alphafold.sif"
export IMPRESS_INPUT_DIR="$SCRATCH/$USER/IMPRESS_inputs/prod_in"
export IMPRESS_OUTPUT_DIR="$SCRATCH/$USER/IMPRESS_outputs"
export IMPRESS_SCRIPTS_DIR="$SCRATCH/$USER/IMPRESS/examples/protien_binding_usecase"

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="$SCRATCH/$USER/IMPRESS/examples/protien_binding_usecase"
cd "$WORKDIR"
mkdir -p logs

eval "$IMPRESS_PRE_EXEC"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Run ───────────────────────────────────────────────────────────────────────
rm -rf asyncflow.session.*
dragon -s run_protein_binding.py
