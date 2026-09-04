#!/bin/bash
#
# IMPRESS-R (Protein Binding + ROME fine-tuning) — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch (only SBATCH_ACCOUNT and SCRATCH are required):
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export SCRATCH=/scratch/<allocation>
#
# Key env vars (all have defaults):
#   MPNN_PATH               — dauparas/ProteinMPNN checkout (inference AND fine-tune target)
#   ROME_MPNN_REPO          — same as MPNN_PATH by default
#   ROME_TRAINER            — mpnn (real fine-tune) | dummy (smoke test, default)
#   ROME_MIN_SAMPLES        — corpus size before the first training round (default 2)
#   ROME_MAX_PASSES         — max design passes per pipeline (default 10)
#   ROME_FALLBACK           — seconds Dragon may take to deliver a training result (default 60)
#   IMPRESS_N_PIPELINES     — number of top-level pipelines to run (default 16)
#   IMPRESS_MAX_SUB_PIPELINES — max child pipeline depth per parent (default 3; 0 = none)
#   IMPRESS_BASE_DIR        — parent of prod_in/ (input PDB files)
#   IMPRESS_OUTPUT_DIR      — where af_pipeline_outputs_multi/ is written
#
# Debug flags:
#   IMPRESS_TEST_MODE=1  — 2 pipelines, max_passes=1, no child pipelines
#   ROME_TRAINER=dummy   — skip real fine-tuning (useful with IMPRESS_TEST_MODE)
#
# Quick validation run (~1 h, sees full ROME loop to completion):
#   IMPRESS_N_PIPELINES=4 IMPRESS_MAX_SUB_PIPELINES=1 ROME_MAX_PASSES=8 ROME_FALLBACK=120 sbatch delta_gpu_run.sh
#
# Full production run (~3 h):
#   sbatch delta_gpu_run.sh
#
# Example:
#   sbatch delta_gpu_run.sh
#   IMPRESS_TEST_MODE=1 ROME_TRAINER=dummy sbatch delta_gpu_run.sh
#
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=02:00:00
#SBATCH --job-name=impress_r
#SBATCH --mail-user=mg2347@soe.rutgers.edu
#SBATCH --mail-type=END,FAIL
#SBATCH --output=logs/impress_%j.out
#SBATCH --error=logs/impress_%j.err
# NOTE: logs/ must exist before sbatch is called.  Create it once with:
#   mkdir -p <impress_r_dir>/logs

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
IMPRESS_VENV="${IMPRESS_VENV:-${HOME}/ve/impress_A}"
unset SLURM_EXPORT_ENV
source "${IMPRESS_VENV}/bin/activate"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths ────────────────────────────────────────────────────────────────
# ProteinMPNN checkout — used for inference (mpnn_wrapper.py) and fine-tuning (ROME).
export MPNN_PATH="${MPNN_PATH:-${SCRATCH}/${USER}/ProteinMPNN}"
# ROME-A fine-tunes the same checkout and publishes weights back into it.
export ROME_MPNN_REPO="${ROME_MPNN_REPO:-${MPNN_PATH}}"

# Boltz — separate Python <=3.12 env (numpy<2.0 etc.)
export BOLTZ_VENV="${BOLTZ_VENV:-${HOME}/ve/boltz}"
export BOLTZ_CACHE_DIR="${BOLTZ_CACHE_DIR:-${HOME}/boltz}"
mkdir -p "${BOLTZ_CACHE_DIR}"

# ── IMPRESS paths ─────────────────────────────────────────────────────────────
export IMPRESS_SCRIPTS_DIR="${IMPRESS_SCRIPTS_DIR:-${SCRATCH}/${USER}/IMPRESS/examples/impress_r}"
export IMPRESS_BASE_DIR="${IMPRESS_BASE_DIR:-${SCRATCH}/${USER}/IMPRESS_inputs}"
export IMPRESS_OUTPUT_DIR="${IMPRESS_OUTPUT_DIR:-${SCRATCH}/${USER}/IMPRESS_outputs}"

# ── ROME-A settings ───────────────────────────────────────────────────────────
# ROME_TRAINER=mpnn  → real ProteinMPNN fine-tune (needs ROME_MPNN_REPO on disk)
# ROME_TRAINER=dummy → smoke test (no GPU/torch needed for training)
export ROME_TRAINER="${ROME_TRAINER:-mpnn}"
export ROME_MIN_SAMPLES="${ROME_MIN_SAMPLES:-2}"
export ROME_MAX_PASSES="${ROME_MAX_PASSES:-10}"
# 120 s gives training rounds time to finish and write train_complete before Dragon's
# result-delivery future raises a spurious TypeError (dragonhpc 0.14.1 DDict race).
export ROME_FALLBACK="${ROME_FALLBACK:-120}"

# ── Scale settings ────────────────────────────────────────────────────────────
# Quick run (~1 h): IMPRESS_N_PIPELINES=4 IMPRESS_MAX_SUB_PIPELINES=1 ROME_MAX_PASSES=8
# Full run  (~3 h): leave unset (16 pipelines, 3 sub-levels, 10 passes)
export IMPRESS_N_PIPELINES="${IMPRESS_N_PIPELINES:-16}"
# Blank = use code default (3); set to 0 to disable child-pipeline spawning entirely.
export IMPRESS_MAX_SUB_PIPELINES="${IMPRESS_MAX_SUB_PIPELINES:-}"

# ── Test / debug flags ────────────────────────────────────────────────────────
export IMPRESS_TEST_MODE="${IMPRESS_TEST_MODE:-0}"

echo "MPNN_PATH:         ${MPNN_PATH}"
echo "ROME_MPNN_REPO:    ${ROME_MPNN_REPO}"
echo "ROME_TRAINER:      ${ROME_TRAINER}"
echo "ROME_MIN_SAMPLES:  ${ROME_MIN_SAMPLES}"
echo "IMPRESS_BASE_DIR:  ${IMPRESS_BASE_DIR}"
echo "IMPRESS_OUTPUT_DIR:${IMPRESS_OUTPUT_DIR}"
echo "TEST_MODE:         ${IMPRESS_TEST_MODE}"

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR="${IMPRESS_SCRIPTS_DIR}"
cd "${WORKDIR}"
mkdir -p logs

# ── Run ───────────────────────────────────────────────────────────────────────
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

rm -f ddict_orc*

echo "Running: dragon ${DRAGON_MODE} run_protein_binding_rome.py  (nodes=${SLURM_NNODES:-1})"
dragon ${DRAGON_MODE} run_protein_binding_rome.py

echo "=== IMPRESS-R pipeline done: $(date) ==="
