#!/bin/bash
#
# Protein Binding Pipeline — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch:
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#
# Set WORK_DIR to your personal work directory before calling sbatch:
#
#   export WORK_DIR=/path/to/your/workdir
#   sbatch delta_gpu_run.sh
#
# Account: set SBATCH_ACCOUNT=<project>-delta-gpu before calling sbatch
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=192g
#SBATCH --time=00:30:00
#SBATCH --exclusive
#SBATCH --job-name=impress_protein
#SBATCH --mail-user=mgoliyad@gmail.com
#SBATCH --mail-type=ALL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err
# NOTE: logs/ must exist before sbatch is called.  Create it once with:
#   mkdir -p <protein_binding_dir>/logs
# NOTE: IMPRESS log output (including errors) goes to .out, not .err.
#   On failure, check logs/impress_<jobid>.out — the .err file will only
#   contain Python interpreter crashes or output from non-IMPRESS processes.

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set — job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

# ── Work directory ────────────────────────────────────────────────────────────
: "${WORK_DIR:?Set WORK_DIR before calling sbatch, e.g.: export WORK_DIR=/path/to/your/workdir}"

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_VENV="${WORK_DIR}/ve/impress"

module load cray-python
module load cray-mpich-abi

#source "${IMPRESS_VENV}/bin/activate"

# ── Tool paths ────────────────────────────────────────────────────────────────
export MPNN_PATH="${WORK_DIR}/ProteinMPNN"
if [ ! -x "${MPNN_PATH}/protein_mpnn_run.py" ]; then
    echo "WARNING: ProteinMPNN not found at ${MPNN_PATH}"
    echo "         Clone it manually: git clone https://github.com/dauparas/ProteinMPNN ${MPNN_PATH}"
    echo "         Or run delta_env_setup.sh first"
fi
# Boltz venv — separate venv with boltz[cuda] + rhapsody-py[dragon].
export BOLTZ_VENV="${WORK_DIR}/ve/boltz"
# Boltz model weight cache (45K CCD files).
export BOLTZ_CACHE_DIR="${WORK_DIR}/boltz"
mkdir -p "${BOLTZ_CACHE_DIR}"

source "${BOLTZ_VENV}/bin/activate"

# ── IMPRESS paths ─────────────────────────────────────────────────────────────
export IMPRESS_SCRIPTS_DIR="${WORK_DIR}/IMPRESS/examples/protein_binding"
# IMPRESS_BASE_DIR: parent of prod_in/ — pipeline builds prod_in/<name>_in from here
export IMPRESS_BASE_DIR="${WORK_DIR}/IMPRESS_inputs"
export IMPRESS_OUTPUT_DIR="${WORK_DIR}/IMPRESS_outputs"

# IMPRESS_BACKEND: "dragon" (default, multi-node HPC) or "local" (single-node,
# ProcessPoolExecutor — useful for development / non-Dragon clusters).
# Set before sbatch:  IMPRESS_BACKEND=local sbatch delta_gpu_run.sh
export IMPRESS_BACKEND="${IMPRESS_BACKEND:-dragon}"
echo "IMPRESS_BACKEND:   ${IMPRESS_BACKEND}"

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="${IMPRESS_SCRIPTS_DIR}"
cd "${WORKDIR}"
mkdir -p logs

# IMPRESS_SESSION_DIR: asyncflow session dir — runinfo, captured task
# stdout/stderr (.stdout/.stderr per task UID).  Must be on Lustre so files
# survive the job and can be reviewed after failures.
export IMPRESS_SESSION_DIR="${IMPRESS_SESSION_DIR:-${WORKDIR}/logs/sessions}"
mkdir -p "${IMPRESS_SESSION_DIR}"

# ── Run ───────────────────────────────────────────────────────────────────────

# -s = single-node Dragon runtime; -m = multi-node (uses MPI/OFI fabric).
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

#rm  -rf "${WORK_DIR}/IMPRESS_outputs/"*

if [ "${IMPRESS_BACKEND}" = "dragon" ]; then
    # ── System library paths (Delta-specific, required by Dragon) ─────────────────
    export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
    export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
    export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
    export FAB_BUILD_LIB=/opt/cray/libfabric/2.3.1/lib64
    export FAB_INCLUDE=/opt/cray/libfabric/2.3.1/include
    export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

    dragon-config add --ofi-runtime-lib="${FAB_LIB}"
    dragon-config add --ofi-build-lib="${FAB_BUILD_LIB}"
    dragon-config add --ofi-include="${FAB_INCLUDE}"
    export OPENBLAS_NUM_THREADS=1

    echo "Running: dragon ${DRAGON_MODE} run_protein_binding.py  (nodes=${SLURM_NNODES:-1})"
    dragon ${DRAGON_MODE} boltz_test.py   #run_protein_binding.py
else
    echo "Running: python3 run_protein_binding.py  (backend=${IMPRESS_BACKEND})"
    python3 run_protein_binding.py
fi

echo "=== Protein Binding pipeline done: $(date) ==="
