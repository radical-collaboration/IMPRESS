#!/bin/bash
# =============================================================================
# IMPRESS-R (Protein Binding + ROME fine-tuning) environment setup — Delta HPC
#
# Creates a Python 3.11+ venv and installs all dependencies, including ROME-A.
#
# Usage:
#   export SCRATCH=/scratch/<allocation>
#   bash delta_env_setup.sh [--env-dir DIR] [--impress-dir DIR] [--rome-dir DIR] [--python PATH]
#
# Defaults:
#   ENV_DIR     = /u/$USER/ve/impress
#   IMPRESS_DIR = $SCRATCH/$USER/IMPRESS
#   ROME_DIR    = $SCRATCH/$USER/ROME
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
ROME_DIR="${ROME_DIR:-${SCRATCH}/${USER}/ROME}"
BASE_PY_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-dir)      ENV_DIR="$2";      shift 2 ;;
        --impress-dir)  IMPRESS_DIR="$2";  shift 2 ;;
        --rome-dir)     ROME_DIR="$2";     shift 2 ;;
        --python)       BASE_PY_OVERRIDE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

PY="${ENV_DIR}/bin/python"
PIP="${ENV_DIR}/bin/pip"

echo "================================================================="
echo "  ENV_DIR       = ${ENV_DIR}"
echo "  IMPRESS_DIR   = ${IMPRESS_DIR}"
echo "  ROME_DIR      = ${ROME_DIR}"
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

# ── 6. ROME (local editable) ─────────────────────────────────────────────────
echo ""
echo "── Step 6: ROME (editable) ──"
if [ -d "${ROME_DIR}" ]; then
    "${PIP}" install -q -e "${ROME_DIR}"
else
    echo "WARNING: ROME_DIR=${ROME_DIR} not found — skipping ROME install."
    echo "         Set --rome-dir or clone ROME before running impress_r."
fi

# ── 7. PyTorch (CUDA 12.1) ───────────────────────────────────────────────────
echo ""
echo "── Step 7: PyTorch (cu121) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── 8. Additional dependencies ───────────────────────────────────────────────
echo ""
echo "── Step 8: pandas + biopandas ──"
"${PIP}" install -q pandas biopandas

# ── 9. PyRosetta (via pyrosetta-installer) ───────────────────────────────────
echo ""
echo "── Step 9: PyRosetta ──"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# ── 10. Boltz (structure prediction — separate Python 3.12 conda env) ────────
echo ""
echo "── Step 10: Boltz (separate conda env) ──"
# boltz 2.x requires numpy<2.0, scipy==1.13.1, etc. — none have Python 3.13
# wheels, so boltz cannot be installed in the main Python 3.13 IMPRESS venv.
# Create a dedicated Python 3.12 conda env and install boltz there.
# s4_boltz.sh activates BOLTZ_VENV (set in delta_gpu_run.sh) instead of VIRTUAL_ENV.
MINIFORGE="${MINIFORGE:-/scratch/bblj/${USER}/miniforge3}"
BOLTZ_ENV="${BOLTZ_ENV:-${HOME}/ve/boltz}"
# Cache lives in home dir — scratch inode quota can't hold the 45K CCD files.
BOLTZ_CACHE="${BOLTZ_CACHE:-${HOME}/boltz}"
if [ ! -x "${BOLTZ_ENV}/bin/python" ]; then
    echo "  Creating conda env (Python 3.11) at ${BOLTZ_ENV}"
    # Use /tmp for package cache to avoid scratch quota exhaustion.
    CONDA_PKGS_DIRS=/tmp/conda_pkgs "${MINIFORGE}/bin/conda" create -p "${BOLTZ_ENV}" python=3.11 -y -q
else
    echo "  boltz conda env already exists at ${BOLTZ_ENV}"
fi
echo "  Installing boltz into ${BOLTZ_ENV}"
"${BOLTZ_ENV}/bin/pip" install -q boltz
# Pre-warm the boltz cache so compute nodes (no internet) find weights ready.
# boltz downloads mols.tar (45K CCD pkl files) + model weights on first run.
# Running predict on the login node (which has internet) pre-populates them.
echo "  Pre-warming boltz cache at ${BOLTZ_CACHE}"
mkdir -p "${BOLTZ_CACHE}"
_WARM_FA="$(mktemp /tmp/boltz_warmup_XXXXXX.fasta)"
printf ">warmup|A\nGSSGSSGSS\n>warmup|B\nGSSGSSGSS\n" > "${_WARM_FA}"
BOLTZ_CACHE_DIR="${BOLTZ_CACHE}" "${BOLTZ_ENV}/bin/boltz" predict "${_WARM_FA}" \
    --out_dir "$(mktemp -d /tmp/boltz_warmup_out_XXXXXX)" \
    --cache "${BOLTZ_CACHE}" \
    --override 2>&1 | grep -E "Download|Extracting|Error|error" || true
rm -f "${_WARM_FA}"
echo "  Boltz cache pre-warm done (model weights cached at ${BOLTZ_CACHE})"

# Pre-compute MSAs for all input proteins using the MSA server (login node has internet).
# protein_binding_rome.py s3() reads from BOLTZ_MSA_CACHE and embeds paths in the FASTA so
# compute nodes do not need internet access.  Entity 0 = receptor, entity 1 = peptide.
BOLTZ_MSA_CACHE="${BOLTZ_CACHE}/msa_cache"
mkdir -p "${BOLTZ_MSA_CACHE}"
echo "  Pre-computing MSAs into ${BOLTZ_MSA_CACHE}"
_scratch="${SCRATCH:-/scratch/bblj/${USER}}"
_base_dir="${IMPRESS_BASE_DIR:-${_scratch}/IMPRESS_inputs}"
_out_dir="${IMPRESS_OUTPUT_DIR:-${_scratch}/IMPRESS_outputs}"
_msa_inputs_dir="${_base_dir}/prod_in"
if [ -d "${_msa_inputs_dir}" ]; then
    for _pdb_dir in "${_msa_inputs_dir}"/p*_in; do
        for _pdb in "${_pdb_dir}"/*.pdb; do
            [ -f "${_pdb}" ] || continue
            _stem="$(basename "${_pdb}" .pdb)"
            _msa_csv="${BOLTZ_MSA_CACHE}/boltz_results_${_stem}/msa/${_stem}_0.csv"
            if [ -f "${_msa_csv}" ]; then
                echo "    ${_stem}: MSA already cached, skipping"
                continue
            fi
            echo "    ${_stem}: generating MSA via server..."
            _tmp_fa="$(mktemp /tmp/boltz_msa_XXXXXX.fasta)"
            _prior_fa=""
            for _cand in "${_out_dir}"/af_pipeline_outputs_multi/*/af/fasta/"${_stem}.fa"; do
                [ -f "${_cand}" ] && { _prior_fa="${_cand}"; break; }
            done
            if [ -n "${_prior_fa}" ]; then
                cp "${_prior_fa}" "${_tmp_fa}"
            else
                printf ">pdz|protein\nGSSGSS\n>pep|protein\nGSSG\n" > "${_tmp_fa}"
            fi
            BOLTZ_CACHE_DIR="${BOLTZ_CACHE}" "${BOLTZ_ENV}/bin/boltz" predict "${_tmp_fa}" \
                --out_dir "${BOLTZ_MSA_CACHE}" \
                --use_msa_server \
                --cache "${BOLTZ_CACHE}" \
                --output_format pdb \
                --override 2>&1 | grep -E "MSA|Generat|Error|error|skip" || true
            rm -f "${_tmp_fa}"
        done
    done
else
    echo "    prod_in not found at ${_msa_inputs_dir}, skipping MSA pre-compute"
fi
echo "  MSA pre-compute done"

# ── 11. Verify ───────────────────────────────────────────────────────────────
echo ""
echo "── Step 11: Verifying installation ──"
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
_check "rome"              "${PY}" -c "import rome; print('ok')"
_check "torch"             "${PY}" -c "import torch; print(torch.__version__)"
_check "pandas"            "${PY}" -c "import pandas; print(pandas.__version__)"
BOLTZ_ENV="${BOLTZ_ENV:-${HOME}/ve/boltz}"
_check "boltz"             "${BOLTZ_ENV}/bin/python" -c "import boltz; print('ok')"

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
echo "  cd ${IMPRESS_DIR}/examples/impress_r"
echo "  sbatch delta_gpu_run.sh"
echo ""
echo "Test (smoke) run:"
echo "  IMPRESS_TEST_MODE=1 ROME_TRAINER=dummy sbatch delta_gpu_run.sh"
echo "================================================================="
