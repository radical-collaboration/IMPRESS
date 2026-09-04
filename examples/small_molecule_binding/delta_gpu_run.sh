#!/bin/bash
#
# Small Molecule Binding Pipeline — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch (only SBATCH_ACCOUNT and SCRATCH are required;
# the rest default to standard Delta locations):
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export SCRATCH=/scratch/<allocation>
#
# Optional overrides (all have defaults based on SCRATCH/$USER):
#   export MPNN_DIR=/path/to/LigandMPNN
#   export COLABFOLD_PATH=/path/to/localcolabfold
#   export COLABFOLD_CACHE_DIR=/path/to/colabfold_cache
#
# Foundry container (RFD3):
#   The foundry sandbox is stored as a .tar.gz on scratch (built by pull_foundry.sh).
#   This script extracts it to /tmp at job start (no scratch quota cost) and removes
#   it on exit.  Override FOUNDRY_TAR to point to a different archive, or set
#   FOUNDRY_SIF_PATH directly to skip extraction entirely (e.g. a pre-extracted dir).
#
# Example:
#   sbatch delta_gpu_run.sh
#   sbatch delta_gpu_run.sh run_nonadaptive.py   # non-adaptive runner
#
# Account: set SBATCH_ACCOUNT=<project>-delta-gpu before calling sbatch
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=02:30:00
#SBATCH --job-name=impress_sm_binding
#SBATCH --mail-user=mg2347@soe.rutgers.edu
#SBATCH --mail-type=ALL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err
# NOTE: logs/ must exist before sbatch is called.  Create it once with:
#   mkdir -p <small_molecule_binding_dir>/logs

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
IMPRESS_VENV="${IMPRESS_VENV:-${HOME}/ve/small_mol}"
unset SLURM_EXPORT_ENV
source "${IMPRESS_VENV}/bin/activate"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths (read by SmallMoleculeBindingPipeline via env vars) ─────────────
# These are picked up by the pipeline's __init__ when not passed as kwargs.
export MPNN_DIR="${MPNN_DIR:-${SCRATCH}/${USER}/LigandMPNN}"

export COLABFOLD_PATH="${COLABFOLD_PATH:-${SCRATCH}/${USER}/localcolabfold}"

# ColabFold model weights cache — kept on scratch to avoid home quota exhaustion.
# Pre-download once on login node:
#   export COLABFOLD_CACHE_DIR=${SCRATCH}/${USER}/.cache/colabfold
#   python -c "from colabfold.download import download_alphafold_params; \
#              download_alphafold_params('alphafold2', '${COLABFOLD_CACHE_DIR}')"
export COLABFOLD_CACHE_DIR="${COLABFOLD_CACHE_DIR:-${SCRATCH}/${USER}/.cache/colabfold}"
mkdir -p "${COLABFOLD_CACHE_DIR}"

# ── Foundry sandbox: extract to /tmp at job start, clean up on exit ───────────
# Extracting to /tmp avoids the scratch quota. Compute nodes have ample /tmp
# space that is not quota-counted.  If FOUNDRY_SIF_PATH is already set (e.g.
# a pre-built .sif or a persistent sandbox on a large allocation), extraction
# is skipped entirely.
if [ -z "${FOUNDRY_SIF_PATH:-}" ]; then
    FOUNDRY_TAR="${FOUNDRY_TAR:-${SCRATCH}/${USER}/foundry_sandbox.tar.gz}"
    if [ ! -f "${FOUNDRY_TAR}" ]; then
        echo "ERROR: foundry sandbox tarball not found: ${FOUNDRY_TAR}"
        echo "       Build it first: sbatch pull_foundry.sh"
        exit 1
    fi
    _FOUNDRY_TMP="/tmp/foundry_${SLURM_JOB_ID:-$$}"
    echo "Extracting foundry sandbox from ${FOUNDRY_TAR} to ${_FOUNDRY_TMP} ..."
    mkdir -p "${_FOUNDRY_TMP}"
    tar -xzf "${FOUNDRY_TAR}" -C "${_FOUNDRY_TMP}" --strip-components=1
    export FOUNDRY_SIF_PATH="${_FOUNDRY_TMP}"
    # shellcheck disable=SC2064
    trap "echo 'Removing ${_FOUNDRY_TMP}'; rm -rf '${_FOUNDRY_TMP}'" EXIT
fi

echo "MPNN_DIR:          ${MPNN_DIR}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "COLABFOLD_PATH:    ${COLABFOLD_PATH}"
echo "COLABFOLD_CACHE:   ${COLABFOLD_CACHE_DIR}"

# ── Tool existence checks ──────────────────────────────────────────────────────
if [ ! -d "${MPNN_DIR}" ]; then
    echo "ERROR: MPNN_DIR does not exist: ${MPNN_DIR}"
    echo "       Clone LigandMPNN: git clone https://github.com/dauparas/LigandMPNN ${MPNN_DIR}"
    exit 1
fi

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="${IMPRESS_SCRIPTS_DIR:-${SCRATCH}/${USER}/IMPRESS/examples/small_molecule_binding}"
cd "${WORKDIR}"
mkdir -p logs

# IMPRESS_WORK_DIR: where pipeline task dirs (p1/, p2/, …) are written.
# Defaults to logs/ so all run artifacts stay out of the source tree and are
# covered by .gitignore.  Override to write outputs elsewhere.
export IMPRESS_WORK_DIR="${IMPRESS_WORK_DIR:-${WORKDIR}/logs}"
mkdir -p "${IMPRESS_WORK_DIR}"

# IMPRESS_TEST_MODE=1: 2 pipelines, inert thresholds, max_tasks=10.
# Runs one full rfd3→mpnn→fastrelax→filter_shape→af2 cycle to verify the
# end-to-end path without looping.  Set before sbatch:
#   IMPRESS_TEST_MODE=1 sbatch delta_gpu_run.sh
export IMPRESS_TEST_MODE="${IMPRESS_TEST_MODE:-0}"
echo "TEST_MODE:         ${IMPRESS_TEST_MODE}"

# ── Run ───────────────────────────────────────────────────────────────────────
# asyncflow session dirs now go to /tmp (node-local, no quota) via IMPRESS_SESSION_DIR.

# -s = single-node Dragon runtime; -m = multi-node (uses MPI/OFI fabric).
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

rm -f ddict_orc*

RUNNER="${1:-run_small_molecule_binding.py}"
echo "Running: dragon ${DRAGON_MODE} ${RUNNER}  (nodes=${SLURM_NNODES:-1})"
dragon ${DRAGON_MODE} "${RUNNER}"

echo "=== Small Molecule Binding pipeline done: $(date) ==="
