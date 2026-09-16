#!/bin/bash
#
# Small Molecule Binding ROME — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch:
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export WORK_DIR=/path/to/your/workdir
#   sbatch delta_gpu_run.sh
#
# Key env vars (all default relative to WORK_DIR):
#   WORK_DIR                — required; all tool paths default under here
#   MPNN_DIR                — dauparas/LigandMPNN checkout (inference + fine-tune target)
#   ROME_TRAINER            — mpnn (real fine-tune) | dummy (smoke test, default: mpnn)
#   ROME_MIN_SAMPLES        — corpus size before first training round (default: 8)
#   ROME_MAX_PASSES         — max design passes per pipeline (default: 10)
#   ROME_FALLBACK           — seconds to wait for Dragon result delivery before reading
#                             checkpoint from disk (default: 120; tuned for DDict race)
#   BOLTZ_CACHE             — Boltz-2 model weights cache
#   IMPRESS_N_PIPELINES     — number of top-level pipelines (default: 2)
#
# Foundry container (RFD3):
#   Stored as a .tar.gz under WORK_DIR (built by ../small_molecule_binding/pull_foundry.sh).
#   Extracted to /tmp at job start, cleaned up on exit.  Override FOUNDRY_TAR or
#   set FOUNDRY_SIF_PATH directly to skip extraction.
#
# Quick validation run (~2 h, exercises full ROME loop end to end):
#   IMPRESS_N_PIPELINES=2 ROME_MAX_PASSES=4 ROME_MIN_SAMPLES=2 sbatch delta_gpu_run.sh
#
# Smoke test (no real fine-tuning, verifies plumbing only):
#   ROME_TRAINER=dummy sbatch delta_gpu_run.sh
#
# Full run (~4 h):
#   sbatch delta_gpu_run.sh
#
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=04:00:00
#SBATCH --job-name=impress_smb_rome
#SBATCH --mail-user=mgoliyad@gmail.com
#SBATCH --mail-type=END,FAIL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err
# NOTE: create logs/ before sbatch: mkdir -p <this_dir>/logs

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set — job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

# ── Work directory ────────────────────────────────────────────────────────────
: "${WORK_DIR:?Set WORK_DIR before calling sbatch, e.g.: export WORK_DIR=/path/to/your/workdir}"

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_VENV="${IMPRESS_VENV:-${WORK_DIR}/ve/small_mol}"
unset SLURM_EXPORT_ENV
source "${IMPRESS_VENV}/bin/activate"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths ────────────────────────────────────────────────────────────────
# LigandMPNN checkout — used for inference (mpnn_run.py) and fine-tuning (ROME).
# Fine-tuning writes updated weights back in-place.
export MPNN_DIR="${MPNN_DIR:-${WORK_DIR}/LigandMPNN}"

export BOLTZ_CACHE="${BOLTZ_CACHE:-${WORK_DIR}/.cache/boltz}"
mkdir -p "${BOLTZ_CACHE}"

# ── ROME-A settings ───────────────────────────────────────────────────────────
# ROME_TRAINER=mpnn   → real LigandMPNN fine-tune (needs MPNN_DIR on disk)
# ROME_TRAINER=dummy  → smoke test — skips fine-tuning, exercises plumbing only
export ROME_TRAINER="${ROME_TRAINER:-mpnn}"
export ROME_MIN_SAMPLES="${ROME_MIN_SAMPLES:-8}"
export ROME_MAX_PASSES="${ROME_MAX_PASSES:-10}"
# 120 s gives training rounds time to finish and write train_complete before
# Dragon's result-delivery future blocks (dragonhpc 0.14.1 DDict race).
export ROME_FALLBACK="${ROME_FALLBACK:-120}"

# ── Scale / debug ─────────────────────────────────────────────────────────────
export IMPRESS_N_PIPELINES="${IMPRESS_N_PIPELINES:-2}"

# ── Foundry sandbox: extract to /tmp, clean up on exit ───────────────────────
if [ -z "${FOUNDRY_SIF_PATH:-}" ]; then
    FOUNDRY_TAR="${FOUNDRY_TAR:-${WORK_DIR}/foundry_sandbox.tar.gz}"
    if [ ! -f "${FOUNDRY_TAR}" ]; then
        echo "ERROR: foundry sandbox tarball not found: ${FOUNDRY_TAR}"
        echo "       Build it first: sbatch ../small_molecule_binding/pull_foundry.sh"
        exit 1
    fi
    _FOUNDRY_TMP="/tmp/foundry_${SLURM_JOB_ID:-$$}"
    echo "Extracting foundry sandbox to ${_FOUNDRY_TMP} ..."
    mkdir -p "${_FOUNDRY_TMP}"
    tar -xzf "${FOUNDRY_TAR}" -C "${_FOUNDRY_TMP}" --strip-components=1
    export FOUNDRY_SIF_PATH="${_FOUNDRY_TMP}"
    trap "echo 'Removing ${_FOUNDRY_TMP}'; rm -rf '${_FOUNDRY_TMP}'" EXIT
fi

echo "WORK_DIR:          ${WORK_DIR}"
echo "MPNN_DIR:          ${MPNN_DIR}"
echo "ROME_TRAINER:      ${ROME_TRAINER}"
echo "ROME_MIN_SAMPLES:  ${ROME_MIN_SAMPLES}"
echo "ROME_MAX_PASSES:   ${ROME_MAX_PASSES}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "BOLTZ_CACHE:       ${BOLTZ_CACHE}"

# ── MPNN check (warn + fallback, not hard exit) ───────────────────────────────
if [ ! -d "${MPNN_DIR}" ] && [ "${ROME_TRAINER}" = "mpnn" ]; then
    echo "WARNING: MPNN_DIR does not exist: ${MPNN_DIR}"
    echo "         Fine-tuning will fall back to DummyTrainer."
    echo "         To enable real fine-tuning: clone LigandMPNN to ${MPNN_DIR}"
fi

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="${IMPRESS_SCRIPTS_DIR:-$(dirname "$(realpath "$0")")}"
cd "${WORKDIR}"
mkdir -p logs

export IMPRESS_OUTPUT_DIR="${IMPRESS_OUTPUT_DIR:-${WORKDIR}/IMPRESS_outputs}"
mkdir -p "${IMPRESS_OUTPUT_DIR}"

# ── Run ───────────────────────────────────────────────────────────────────────
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

rm -f ddict_orc*

echo "Running: dragon ${DRAGON_MODE} run_smb_rome.py  (nodes=${SLURM_NNODES:-1})"
dragon ${DRAGON_MODE} run_smb_rome.py

echo "=== Small Molecule Binding ROME pipeline done: $(date) ==="
