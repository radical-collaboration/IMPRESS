#!/bin/bash
# =============================================================================
# IMPRESS Small Molecule Binding environment setup — Delta HPC (NCSA)
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
#
# Tool directories (cloned by this script if absent):
#   MPNN_DIR           = $SCRATCH/$USER/LigandMPNN
#   COLABFOLD_PATH     = $SCRATCH/$USER/localcolabfold  (used only for cache ref)
#   COLABFOLD_CACHE_DIR= $SCRATCH/$USER/.cache/colabfold
#
# Foundry container (RFD3 backbone diffusion) is managed separately:
#   Run pull_foundry.sh to build the sandbox tarball; delta_gpu_run.sh unpacks
#   it to /tmp at job start.
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

MPNN_DIR="${MPNN_DIR:-${SCRATCH}/${USER}/LigandMPNN}"
COLABFOLD_CACHE_DIR="${COLABFOLD_CACHE_DIR:-${SCRATCH}/${USER}/.cache/colabfold}"

echo "================================================================="
echo "  ENV_DIR            = ${ENV_DIR}"
echo "  IMPRESS_DIR        = ${IMPRESS_DIR}"
echo "  MPNN_DIR           = ${MPNN_DIR}"
echo "  COLABFOLD_CACHE    = ${COLABFOLD_CACHE_DIR}"
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

# ── 6. PyTorch (CUDA 12.1) — required by LigandMPNN ─────────────────────────
echo ""
echo "── Step 6: PyTorch (cu121) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── 7. ColabFold + AlphaFold2 with pinned JAX versions ───────────────────────
#
# Version constraints validated on Delta gpuA40x4 (CUDA 12.8 / cuDNN 9.25):
#
#   colabfold 1.6.2  requires  alphafold-colabfold==2.3.18
#                              jax>=0.5.2,<0.11
#
#   alphafold-colabfold 2.3.18 is compatible with jaxlib 0.5.x but NOT with
#   jaxlib 0.10.x (MSA feature shape mismatch at runtime).
#
#   jax 0.5.2 / jaxlib 0.5.1 require nvidia-cudnn-cu12 >=9.1,<10.0.
#   Upgrade cudnn to >=9.8.0 so jaxlib's cuDNN version check passes (jaxlib
#   0.5.1 links against cuDNN 9.x; runtime version must satisfy >=compiled).
#
echo ""
echo "── Step 7: ColabFold + AlphaFold2 (pinned JAX) ──"
# Install colabfold with the alphafold extra (pulls alphafold-colabfold 2.3.18,
# dm-haiku, dm-tree, ml-collections, absl-py).
"${PIP}" install -q "colabfold[alphafold]"
# Pin JAX to the era tested with alphafold-colabfold 2.3.18.
# jaxlib 0.5.2 does not exist on PyPI; 0.5.1 pairs with jax 0.5.2.
"${PIP}" install -q "jax[cuda12]==0.5.2" "jaxlib==0.5.1"
# Upgrade cuDNN so jaxlib's runtime check (>=compiled version) passes.
"${PIP}" install -q "nvidia-cudnn-cu12>=9.8.0,<10.0"

# ── 8. LigandMPNN ─────────────────────────────────────────────────────────────
#
# LigandMPNN is run directly from its source tree (no package install).
# This step clones the repo; all Python dependencies (torch, ProDy, biopython,
# numpy) are already satisfied by the venv above.
# LigandMPNN's own requirements.txt pins older torch/cudnn versions — do NOT
# install it into this venv; the newer versions here are compatible at runtime.
#
echo ""
echo "── Step 8: LigandMPNN (clone) ──"
if [ ! -d "${MPNN_DIR}" ]; then
    echo "  Cloning LigandMPNN to ${MPNN_DIR}"
    git clone https://github.com/dauparas/LigandMPNN "${MPNN_DIR}"
else
    echo "  LigandMPNN already at ${MPNN_DIR}, pulling latest"
    git -C "${MPNN_DIR}" pull --ff-only || echo "  (pull skipped — non-fast-forward or detached HEAD)"
fi
# Install ProDy and biopython (needed by LigandMPNN; torch already installed).
"${PIP}" install -q ProDy biopython

# ── 9. gemmi — CIF.GZ parsing for backbone conversion ────────────────────────
echo ""
echo "── Step 9: gemmi ──"
"${PIP}" install -q gemmi

# ── 10. Additional dependencies ───────────────────────────────────────────────
echo ""
echo "── Step 10: pandas + biopandas ──"
"${PIP}" install -q pandas biopandas

# ── 11. PyRosetta ─────────────────────────────────────────────────────────────
echo ""
echo "── Step 11: PyRosetta ──"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# ── 12. ColabFold model weights ───────────────────────────────────────────────
#
# Pre-download AlphaFold2 model weights to COLABFOLD_CACHE_DIR so compute
# nodes (no internet) find them at runtime.  Run this step on a login node.
#
echo ""
echo "── Step 12: ColabFold model weights ──"
mkdir -p "${COLABFOLD_CACHE_DIR}"
echo "  Downloading AlphaFold2 weights to ${COLABFOLD_CACHE_DIR} ..."
"${PY}" -c "
from colabfold.download import download_alphafold_params
download_alphafold_params('alphafold2', '${COLABFOLD_CACHE_DIR}')
print('  Weights downloaded.')
"

# ── 13. Verify ────────────────────────────────────────────────────────────────
echo ""
echo "── Step 13: Verifying installation ──"
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
_check "jax"               "${PY}" -c "import jax; print(jax.__version__)"
_check "colabfold"         "${PY}" -c "import colabfold; print(colabfold.__version__)"
_check "alphafold"         "${PY}" -c "import alphafold; print('ok')"
_check "gemmi"             "${PY}" -c "import gemmi; print(gemmi.__version__)"
_check "pyrosetta"         "${PY}" -c "import pyrosetta; print('ok')"
_check "ProDy"             "${PY}" -c "import prody; print(prody.__version__)"
_check "LigandMPNN"        test -d "${MPNN_DIR}" && echo "present"
_check "colabfold weights" test -d "${COLABFOLD_CACHE_DIR}/params" && echo "present"

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
echo "  cd ${IMPRESS_DIR}/examples/small_molecule_binding"
echo "  sbatch delta_gpu_run.sh"
echo ""
echo "Note: Foundry container (RFD3) is managed separately."
echo "  Build once with:  sbatch pull_foundry.sh"
echo "================================================================="
