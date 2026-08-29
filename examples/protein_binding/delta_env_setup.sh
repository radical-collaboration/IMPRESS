#!/bin/bash
# =============================================================================
# IMPRESS Protein Binding environment setup — Delta HPC (NCSA)
#
# Creates a Python 3.11+ venv and installs all dependencies.
#
# Usage:
#   export SCRATCH=/scratch/<allocation>
#   bash delta_env_setup.sh [--env-dir DIR] [--impress-dir DIR] [--python PATH]
#
# Defaults:
#   ENV_DIR     = /u/$USER/ve/impress
#   IMPRESS_DIR = $SCRATCH/$USER/IMPRESS
#   python      = auto-detected (python/3.11, cray-python/3.11.7, anaconda3)
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

# ── Require SCRATCH ───────────────────────────────────────────────────────────
if [[ -z "${SCRATCH:-}" ]]; then
    echo "ERROR: set the SCRATCH env var to your allocation scratch root, e.g.:"
    echo "  export SCRATCH=/scratch/<allocation>"
    echo "  bash delta_env_setup.sh"
    exit 1
fi

# ── Defaults / arg parsing ────────────────────────────────────────────────────
ENV_DIR="${ENV_DIR:-/u/${USER}/ve/impress}"
IMPRESS_DIR="${IMPRESS_DIR:-${SCRATCH}/${USER}/IMPRESS}"
BASE_PY_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-dir)      ENV_DIR="$2";      shift 2 ;;
        --impress-dir)  IMPRESS_DIR="$2";  shift 2 ;;
        --python)       BASE_PY_OVERRIDE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

PY="${ENV_DIR}/bin/python"
PIP="${ENV_DIR}/bin/pip"

echo "================================================================="
echo "  ENV_DIR       = ${ENV_DIR}"
echo "  IMPRESS_DIR   = ${IMPRESS_DIR}"
echo "================================================================="

# ── 1. Create venv ────────────────────────────────────────────────────────────
echo ""
echo "── Step 1: Creating venv ──"

_find_python() {
    for candidate in python3.12 python3.11 python3 python; do
        local p
        p=$(command -v "${candidate}" 2>/dev/null) || continue
        local ver
        ver=$("${p}" -c "import sys; v=sys.version_info; print(v.major*10+v.minor)" 2>/dev/null) || continue
        [ "${ver}" -ge 311 ] && echo "${p}" && return 0
    done
    return 1
}

if [ -n "${BASE_PY_OVERRIDE}" ]; then
    BASE_PY="${BASE_PY_OVERRIDE}"
    echo "Using Python override: ${BASE_PY}"
else
    BASE_PY=$(_find_python || true)
    if [ -z "${BASE_PY}" ]; then
        echo "python3.11+ not in PATH — trying modules..."
        for mod in python/3.12 python/3.11 cray-python/3.11.7 anaconda3; do
            module load "${mod}" 2>/dev/null || true
            BASE_PY=$(_find_python || true)
            [ -n "${BASE_PY}" ] && echo "  loaded module: ${mod}" && break
        done
    fi
    if [ -z "${BASE_PY}" ]; then
        echo "ERROR: no Python 3.11+ interpreter found."
        echo "       Pass an explicit interpreter:  --python /path/to/python3.11"
        echo "       Or load a module manually before running this script."
        exit 1
    fi
fi
echo "Using Python: ${BASE_PY} ($(${BASE_PY} --version))"

if [ ! -x "${PY}" ]; then
    "${BASE_PY}" -m venv "${ENV_DIR}"
else
    echo "venv already exists at ${ENV_DIR}"
fi

echo "Python: $("${PY}" --version)"

# ── 2. Bootstrap pip ──────────────────────────────────────────────────────────
echo ""
echo "── Step 2: Bootstrapping pip ──"
"${PY}" -m pip install -q --upgrade pip wheel
"${PIP}" install -q --force-reinstall "setuptools<71"

# ── 3. radical.asyncflow (PyPI) ──────────────────────────────────────────────
echo ""
echo "── Step 3: radical-asyncflow (PyPI) ──"
"${PIP}" install -q radical-asyncflow

# ── 4. rhapsody-py (PyPI) ────────────────────────────────────────────────────
echo ""
echo "── Step 4: rhapsody-py[dragon] (PyPI) ──"
"${PIP}" install -q "rhapsody-py[dragon,telemetry]"

# ── 5. IMPRESS (local editable) ───────────────────────────────────────────────
echo ""
echo "── Step 5: IMPRESS (editable) ──"
"${PIP}" install -q -e "${IMPRESS_DIR}"

# ── 6. PyTorch (CUDA 12.1) ───────────────────────────────────────────────────
echo ""
echo "── Step 6: PyTorch (cu121) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── 7. Additional dependencies ───────────────────────────────────────────────
echo ""
echo "── Step 7: pandas + biopandas ──"
"${PIP}" install -q pandas biopandas

# ── 8. PyRosetta (via pyrosetta-installer) ───────────────────────────────────
echo ""
echo "── Step 8: PyRosetta ──"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# ── 9. Verify ────────────────────────────────────────────────────────────────
echo ""
echo "── Step 9: Verifying installation ──"
_check() {
    local label="$1"; shift
    if out=$("$@" 2>&1); then
        echo "  ${label}: OK  (${out})"
    else
        echo "  WARNING: ${label} failed"
        echo "    ${out}" | head -3
    fi
}

_check "radical.asyncflow" "${PY}" -c "import radical.asyncflow; print(radical.asyncflow.__version__)"
_check "rhapsody-py"       "${PY}" -c "import rhapsody; print('ok')"
_check "impress"           "${PY}" -c "import impress; print('ok')"
_check "torch"             "${PY}" -c "import torch; print(torch.__version__)"
_check "pandas"            "${PY}" -c "import pandas; print(pandas.__version__)"

echo ""
echo "================================================================="
echo "Setup complete."
echo ""
echo "Activate with:"
echo "  source ${ENV_DIR}/bin/activate"
echo ""
echo "Run the pipeline:"
echo "  export SCRATCH=${SCRATCH}"
echo "  export SBATCH_ACCOUNT=bblj-delta-gpu"
echo "  cd ${IMPRESS_DIR}/examples/protien_binding_usecase"
echo "  sbatch delta_gpu_run.sh"
echo "================================================================="
