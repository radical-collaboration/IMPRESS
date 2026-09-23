#!/bin/bash
#
# IMPRESS-A small-molecule-binding campaign - SLURM batch script (Delta HPC / GPU)
#
# Adapted from the original IMPRESS project's
# examples/small_molecule_binding/delta_gpu_run.sh.
#
# Set before calling sbatch (only SBATCH_ACCOUNT and SCRATCH are required):
#   export SBATCH_ACCOUNT=<project>-delta-gpu     # <project>-delta-gpu or <project>-delta-gpu
#   export SCRATCH=/work/hdd/<project>           # or /work/hdd/<project>/$USER - either
#                                                # form works, see scripts/_scratch_base.sh
#
# Optional overrides:
#   export MPNN_DIR=/path/to/LigandMPNN
#   export BOLTZ_CACHE=/path/to/boltz_cache
#   export FOUNDRY_SIF_PATH=/path/to/extracted/foundry/sandbox   # skips tarball extraction
#   export FOUNDRY_TAR=/path/to/foundry_sandbox.tar.gz           # default: see below
#
# Example:
#   sbatch scripts/delta_gpu_run.sh                                    # full campaign
#   sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml  # smoke test
#
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gpus-per-node=4
#SBATCH --mem=220G
#SBATCH --time=06:00:00
#SBATCH --job-name=impress_a_sm_binding
#SBATCH --mail-user=<your email>
#SBATCH --mail-type=ALL
#SBATCH --output=impress_a_%j.out
# NOTE: IMPRESS-A log output (including errors) goes to .out, not .err, mirroring the
#   original IMPRESS scripts' own convention - on failure check impress_a_<jobid>.out.

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set - job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: SCRATCH is not set."
    echo "       export SCRATCH=/work/hdd/<project> && sbatch scripts/delta_gpu_run.sh"
    exit 1
fi

IMPRESS_A_DIR="${IMPRESS_A_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# SCRATCH_BASE, not ${SCRATCH}/${USER}: $SCRATCH may already BE the per-user directory.
# Shared with delta_env_setup.sh so setup and run cannot disagree about where the tool
# trees live.
source "${IMPRESS_A_DIR}/scripts/_scratch_base.sh"

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
export CUDA_HOME=/opt/nvidia/hpc_sdk/Linux_x86_64/25.3/cuda/12.8
export MPI_LIB=/opt/cray/pe/mpich/8.1.32/ofi/gnu/11.2/lib-abi-mpich
export FAB_LIB=/opt/cray/libfabric/1.22.0/lib64
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_A_VENV="${IMPRESS_A_VENV:-${IMPRESS_A_DIR}/.venv}"
unset SLURM_EXPORT_ENV
source "${IMPRESS_A_VENV}/bin/activate"
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths (read by the rfd3/ligandmpnn/rosetta/boltz task agents) ────────
export MPNN_DIR="${MPNN_DIR:-${SCRATCH_BASE}/LigandMPNN}"
export BOLTZ_CACHE="${BOLTZ_CACHE:-${SCRATCH_BASE}/.cache/boltz}"
mkdir -p "${BOLTZ_CACHE}"

# ── Foundry sandbox: extract to /tmp at job start, clean up on exit ───────────
for _sif in "${SCRATCH_BASE}/foundry.sif" "${SCRATCH}/foundry.sif"; do
    if [ -z "${FOUNDRY_SIF_PATH:-}" ] && [ -f "${_sif}" ]; then
        export FOUNDRY_SIF_PATH="${_sif}"
    fi
done
if [ -z "${FOUNDRY_SIF_PATH:-}" ]; then
    FOUNDRY_TAR="${FOUNDRY_TAR:-${SCRATCH_BASE}/foundry_sandbox.tar.gz}"
    if [ ! -f "${FOUNDRY_TAR}" ]; then
        echo "ERROR: foundry sandbox tarball not found: ${FOUNDRY_TAR}"
        echo "       Build it the way the original IMPRESS examples' pull_foundry.sh does,"
        echo "       or set FOUNDRY_SIF_PATH to an existing .sif/sandbox."
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

echo "SCRATCH_BASE:      ${SCRATCH_BASE}"
echo "MPNN_DIR:          ${MPNN_DIR}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "BOLTZ_CACHE:       ${BOLTZ_CACHE}"

# ── Tool existence checks ──────────────────────────────────────────────────────
if [ ! -d "${MPNN_DIR}" ]; then
    echo "ERROR: MPNN_DIR does not exist: ${MPNN_DIR}"
    echo "       Run scripts/delta_env_setup.sh first (clones LigandMPNN)."
    exit 1
fi

# ── Campaign spec ──────────────────────────────────────────────────────────────
# Resolve before cd'ing into WORKDIR - a relative path (as in the smoke-test example
# above) would otherwise be looked up inside the per-job scratch dir, not the repo.
CAMPAIGN="${1:-${IMPRESS_A_DIR}/campaigns/delta-small-molecule.yaml}"
if [ ! -f "${CAMPAIGN}" ]; then
    echo "ERROR: campaign spec not found: ${CAMPAIGN} (relative to $(pwd))"
    exit 1
fi
CAMPAIGN="$(realpath "${CAMPAIGN}")"

# ── Working directory ─────────────────────────────────────────────────────────
# No IMPRESS_WORK_DIR/IMPRESS_SESSION_DIR indirection here (unlike the old scripts) -
# impress_a's CampaignSpec.root and asyncflow's own session dir both resolve relative to
# the process CWD (see CLAUDE.md's asyncflow-writes-into-CWD gotcha), so `cd`ing into a
# per-job scratch directory before launch is sufficient.
WORKDIR="${IMPRESS_A_WORKDIR:-${SCRATCH_BASE}/impress_a_runs/${SLURM_JOB_ID:-manual}}"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

# ── Model ────────────────────────────────────────────────────────────
MODEL="${IMPRESS_A_MODEL:-D}"
echo "Campaign:          ${CAMPAIGN}"
echo "Model:             ${MODEL}"
echo "Working directory: ${WORKDIR}"

# -s = single-node Dragon runtime; -m = multi-node (uses MPI/OFI fabric).
if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    DRAGON_MODE="-m"
else
    DRAGON_MODE="-s"
fi

rm -f ddict_orc*
echo "Running: dragon ${DRAGON_MODE} ${IMPRESS_A_DIR}/scripts/delta_run_campaign.py run ${CAMPAIGN} --model ${MODEL}  (nodes=${SLURM_NNODES:-1})"
dragon ${DRAGON_MODE} "${IMPRESS_A_DIR}/scripts/delta_run_campaign.py" run "${CAMPAIGN}" --model "${MODEL}"

echo "=== IMPRESS-A small-molecule-binding campaign done: $(date) ==="
