#!/bin/bash
# =============================================================================
# IMPRESS Protein Binding — one-time environment setup for Delta HPC (NCSA)
#
# Run this script once from a Delta login node to install all software and
# populate the work directories needed before submitting the pipeline job.
#
# Prerequisites:
#   - IMPRESS source tree already cloned under $WORK_DIR/IMPRESS
#   - Internet access (login nodes have it; compute nodes do not)
#
# Set WORK_DIR to your personal work directory before running:
#
#   export WORK_DIR=/path/to/your/workdir
#   bash delta_env_setup.sh
#
# What this script does:
#   1. Creates an IMPRESS Python venv  ($WORK_DIR/ve/impress) and installs deps
#   2. Creates a Boltz Python venv     ($WORK_DIR/ve/boltz) and installs deps
#   3. Creates pipeline input/output directories under $WORK_DIR
#   4. Initializes the Boltz model weight cache (45K CCD files, ~7.5 GB)
#
# Usage:
#   bash delta_env_setup.sh
#
# Optional overrides (pass as CLI args, not env vars):
#   --env-dir       DIR   IMPRESS venv location  (default: $WORK_DIR/ve/impress)
#   --boltz-env-dir DIR   Boltz venv location     (default: $WORK_DIR/ve/boltz)
#   --impress-dir   DIR   IMPRESS source tree     (default: $WORK_DIR/IMPRESS)
#   --python        PATH  Python interpreter       (default: python3 from cray-python module)
#
# After this script completes, submit the pipeline with:
#   export SBATCH_ACCOUNT=<your-project>-delta-gpu
#   sbatch delta_gpu_run.sh
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

# ── Load required modules ─────────────────────────────────────────────────────
if ! declare -f module &>/dev/null; then
    _lmod_init=/usr/share/lmod/lmod/init/bash
    [ -f "${_lmod_init}" ] && source "${_lmod_init}"
fi

module load cray-python
module load cray-mpich-abi

# ── Work directory ────────────────────────────────────────────────────────────
: "${WORK_DIR:?Set WORK_DIR before running, e.g.: export WORK_DIR=/path/to/your/workdir}"

ENV_DIR="${WORK_DIR}/ve/impress"
BOLTZ_ENV="${WORK_DIR}/ve/boltz"
IMPRESS_DIR="${WORK_DIR}/IMPRESS"
BASE_PY_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-dir)       ENV_DIR="$2";          shift 2 ;;
        --boltz-env-dir) BOLTZ_ENV="$2";        shift 2 ;;
        --impress-dir)   IMPRESS_DIR="$2";      shift 2 ;;
        --python)        BASE_PY_OVERRIDE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

PY="${ENV_DIR}/bin/python"
PIP="${ENV_DIR}/bin/pip"
BOLTZ_PY="${BOLTZ_ENV}/bin/python"
BOLTZ_PIP="${BOLTZ_ENV}/bin/pip"

echo "================================================================="
echo "  IMPRESS venv  = ${ENV_DIR}"
echo "  Boltz venv    = ${BOLTZ_ENV}"
echo "  IMPRESS src   = ${IMPRESS_DIR}"
echo "  Work dir      = ${WORK_DIR}"
echo "================================================================="

# ── Step 1: Python interpreter ────────────────────────────────────────────────
echo ""
echo "── Step 1: Python interpreter ──"

if [ -n "${BASE_PY_OVERRIDE}" ]; then
    BASE_PY="${BASE_PY_OVERRIDE}"
else
    BASE_PY=$(command -v python3 || true)
    if [ -z "${BASE_PY}" ]; then
        echo "ERROR: python3 not found after loading cray-python."
        exit 1
    fi
    ver=$("${BASE_PY}" -c "import sys; v=sys.version_info; print(v.major*100+v.minor)")
    if [ "${ver}" -lt 311 ]; then
        echo "ERROR: ${BASE_PY} is Python ${ver} — need 3.11+."
        echo "       Pass --python /path/to/python3.11 to override."
        exit 1
    fi
fi
echo "Using: ${BASE_PY} ($(${BASE_PY} --version))"

# ── Step 2: IMPRESS venv ──────────────────────────────────────────────────────
echo ""
echo "── Step 2: IMPRESS venv ──"
if [ ! -x "${PY}" ]; then
    mkdir -p "$(dirname "${ENV_DIR}")"
    "${BASE_PY}" -m venv "${ENV_DIR}"
    echo "Created at ${ENV_DIR}"
else
    echo "Already exists at ${ENV_DIR}"
fi
echo "Python: $("${PY}" --version)"

# ── Step 3: Core pip packages ─────────────────────────────────────────────────
echo ""
echo "── Step 3: Core pip packages ──"
"${PY}" -m pip install -q --upgrade pip wheel
"${PIP}" install -q --force-reinstall "setuptools<71"

# ── Step 4: radical-asyncflow ─────────────────────────────────────────────────
echo ""
echo "── Step 4: radical-asyncflow ──"
"${PIP}" install -q radical-asyncflow

# ── Step 5: rhapsody-py ───────────────────────────────────────────────────────
echo ""
echo "── Step 5: rhapsody-py[dragon,telemetry] ──"
"${PIP}" install -q "rhapsody-py[dragon,telemetry]"

# ── Step 6: IMPRESS (editable install from source) ───────────────────────────
echo ""
echo "── Step 6: IMPRESS ──"
"${PIP}" install -q -e "${IMPRESS_DIR}"

# ── Step 7: PyTorch ───────────────────────────────────────────────────────────
echo ""
echo "── Step 7: PyTorch (CUDA 12.1) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── Step 8: Scientific Python packages ───────────────────────────────────────
echo ""
echo "── Step 8: pandas + biopandas + matplotlib ──"
"${PIP}" install -q pandas biopandas matplotlib

# ── Step 9: Boltz venv ───────────────────────────────────────────────────────
# Boltz lives in a separate venv because its dependency pins (numpy, scipy)
# would conflict with the main IMPRESS environment.
echo ""
echo "── Step 9: Boltz venv ──"
if [ ! -x "${BOLTZ_PY}" ]; then
    mkdir -p "$(dirname "${BOLTZ_ENV}")"
    "${BASE_PY}" -m venv "${BOLTZ_ENV}"
    echo "Created at ${BOLTZ_ENV}"
else
    echo "Already exists at ${BOLTZ_ENV}"
fi
echo "Python: $(${BOLTZ_PY} --version)"

"${BOLTZ_PY}" -m pip install -q --upgrade pip wheel
"${BOLTZ_PIP}" install -q --force-reinstall "setuptools<71"
"${BOLTZ_PIP}" install -q "boltz[cuda]"
"${BOLTZ_PIP}" install -q "rhapsody-py[dragon]"

# ── Step 10: Work directories ────────────────────────────────────────────────
echo ""
echo "── Step 10: Work directories ──"

# Pipeline reads inputs from here; place your protein structures under
# ${WORK_DIR}/IMPRESS_inputs/prod_in/<name>_in/
mkdir -p "${WORK_DIR}/IMPRESS_inputs/prod_in"
echo "  ${WORK_DIR}/IMPRESS_inputs/prod_in   (place input PDB dirs here)"

# Pipeline writes all results here
mkdir -p "${WORK_DIR}/IMPRESS_outputs"
echo "  ${WORK_DIR}/IMPRESS_outputs           (pipeline results)"

# Boltz model weight + CCD molecule cache (45K files, ~7.5 GB).
# Downloaded automatically on first run (requires internet — login node only).
BOLTZ_CACHE_DIR="${WORK_DIR}/boltz"
mkdir -p "${BOLTZ_CACHE_DIR}"
export BOLTZ_CACHE_DIR

if [ -f "${BOLTZ_CACHE_DIR}/boltz2_conf.ckpt" ] && [ -d "${BOLTZ_CACHE_DIR}/mols" ]; then
    echo "  Boltz cache already present at ${BOLTZ_CACHE_DIR} — skipping download."
else
    echo "  Downloading Boltz CCD cache to ${BOLTZ_CACHE_DIR} ..."
    echo "  (CCD molecule files + model weights, ~7.5 GB — may take several minutes)"
    # Run boltz predict with a minimal FASTA to trigger the CCD + model weight
    # download.  The prediction itself will fail (no GPU on login nodes) but the
    # cache is written before boltz reaches the GPU stage, so that error is harmless.
    _boltz_init_fasta=$(mktemp --suffix=.fasta)
    _boltz_init_out=$(mktemp -d)
    printf '>A\nACDEFGH\n' > "${_boltz_init_fasta}"

    PATH="${BOLTZ_ENV}/bin:${PATH}" \
        boltz predict "${_boltz_init_fasta}" \
            --out_dir "${_boltz_init_out}" \
            --cache "${BOLTZ_CACHE_DIR}" \
            --output_format pdb \
            --override > /dev/null 2>&1 || true

    rm -f "${_boltz_init_fasta}"
    rm -rf "${_boltz_init_out}"

    if [ -f "${BOLTZ_CACHE_DIR}/boltz2_conf.ckpt" ] && [ -d "${BOLTZ_CACHE_DIR}/mols" ]; then
        echo "  Boltz cache ready at ${BOLTZ_CACHE_DIR}"
    else
        echo "  WARNING: Boltz CCD mols/ not found — cache download may have failed."
        echo "           Re-run this step or ensure internet access from the login node."
    fi
fi

# ── Step 11: Verify ──────────────────────────────────────────────────────────
echo ""
echo "── Step 11: Verification ──"
_check() {
    local label="$1"; shift
    if out=$("$@" 2>&1); then
        echo "  [OK] ${label}: ${out}"
    else
        echo "  [WARN] ${label} failed:"
        echo "    ${out}" | head -3
    fi
}

echo "  IMPRESS venv:"
_check "radical.asyncflow" "${PY}" -c "import radical.asyncflow; print(radical.asyncflow.__version__)"
_check "rhapsody"          "${PY}" -c "import rhapsody; print('ok')"
_check "impress"           "${PY}" -c "import impress; print('ok')"
_check "torch"             "${PY}" -c "import torch; print(torch.__version__)"
_check "pandas"            "${PY}" -c "import pandas; print(pandas.__version__)"

echo "  Boltz venv:"
_check "boltz"             "${BOLTZ_PY}" -c "import boltz; print(boltz.__version__)"
_check "rhapsody[dragon]" "${BOLTZ_PY}" -c "import rhapsody; print('ok')"

echo ""
echo "================================================================="
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Place input PDB directories under:"
echo "       ${WORK_DIR}/IMPRESS_inputs/prod_in/"
echo "       e.g. prod_in/p1_in/  prod_in/p2_in/  ..."
echo ""
echo "  2. Submit the pipeline:"
echo "       export SBATCH_ACCOUNT=<your-project>-delta-gpu"
echo "       cd ${IMPRESS_DIR}/examples/protein_binding"
echo "       sbatch delta_gpu_run.sh"
echo "================================================================="
