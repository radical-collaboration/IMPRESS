#!/bin/bash
#
# Protein Binding Pipeline — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch (only SBATCH_ACCOUNT and SCRATCH are required;
# the rest default to standard Delta locations):
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export SCRATCH=/scratch/<allocation>
#
# Example:
#   sbatch delta_gpu_run.sh
#
# Account: set SBATCH_ACCOUNT=<project>-delta-gpu before calling sbatch
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=02:00:00
#SBATCH --job-name=impress_protein
#SBATCH --mail-user=mg2347@soe.rutgers.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err
# NOTE: logs/ must exist before sbatch is called.  Create it once with:
#   mkdir -p <protein_binding_dir>/logs

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set — job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: SCRATCH is not set."
    echo "       export SCRATCH=/scratch/<allocation> && sbatch delta_gpu_run.sh"
    exit 1
fi

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_VENV="${IMPRESS_VENV:-${HOME}/ve/impress}"
unset SLURM_EXPORT_ENV
source "${IMPRESS_VENV}/bin/activate"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths (adjust for your allocation) ───────────────────────────────────
export MPNN_PATH="${MPNN_PATH:-${SCRATCH}/${USER}/ProteinMPNN}"
export AF2_DATABASE="${AF2_DATABASE:-${SCRATCH}/${USER}/alphafold_database}"
export AF2_SIF="${AF2_SIF:-${SCRATCH}/${USER}/alphafold.sif}"
# Boltz lives in a separate Python 3.12 conda env (boltz 2.x requires numpy<2.0,
# scipy==1.13.1 etc. which have no Python 3.13 wheels).
export BOLTZ_VENV="${BOLTZ_VENV:-${HOME}/ve/boltz}"
# Boltz model weight cache — kept in home dir; scratch inode quota can't hold
# the 45K CCD molecule files that boltz extracts from mols.tar on first run.
export BOLTZ_CACHE_DIR="${BOLTZ_CACHE_DIR:-${HOME}/boltz}"
mkdir -p "${BOLTZ_CACHE_DIR}"

# ── IMPRESS paths ─────────────────────────────────────────────────────────────
export IMPRESS_SCRIPTS_DIR="${IMPRESS_SCRIPTS_DIR:-${SCRATCH}/${USER}/IMPRESS/examples/protein_binding}"
# IMPRESS_BASE_DIR: parent of prod_in/ — pipeline builds prod_in/<name>_in from here
export IMPRESS_BASE_DIR="${IMPRESS_BASE_DIR:-${SCRATCH}/${USER}/IMPRESS_inputs}"
export IMPRESS_OUTPUT_DIR="${IMPRESS_OUTPUT_DIR:-${SCRATCH}/${USER}/IMPRESS_outputs}"

# IMPRESS_TEST_MODE=1: 2 pipelines, max_passes=1, no child pipelines.
# Runs a single MPNN → score → AF2 cycle to verify end-to-end path.
# Set before sbatch:  IMPRESS_TEST_MODE=1 sbatch delta_gpu_run.sh
export IMPRESS_TEST_MODE="${IMPRESS_TEST_MODE:-0}"
echo "TEST_MODE:         ${IMPRESS_TEST_MODE}"

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="${IMPRESS_SCRIPTS_DIR}"
cd "${WORKDIR}"
mkdir -p logs

# ── Run ───────────────────────────────────────────────────────────────────────
# asyncflow session dirs now go to /tmp (node-local, no quota) via
# IMPRESS_SESSION_DIR; no need to clean them from cwd.

# -s = single-node Dragon runtime; -m = multi-node (uses MPI/OFI fabric).
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

rm -f ddict_orc*

echo "Running: dragon ${DRAGON_MODE} run_protein_binding.py  (nodes=${SLURM_NNODES:-1})"
dragon ${DRAGON_MODE} run_protein_binding.py

echo "=== Protein Binding pipeline done: $(date) ==="
