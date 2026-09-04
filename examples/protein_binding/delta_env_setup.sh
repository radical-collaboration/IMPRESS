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
#   python      = auto-detected via `module load python` (Delta default: 3.13+)
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

# ── Initialize lmod (needed when run as non-interactive bash script) ──────────
if ! declare -f module &>/dev/null; then
    _lmod_init=/usr/share/lmod/lmod/init/bash
    [ -f "${_lmod_init}" ] && source "${_lmod_init}"
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

if [ -n "${BASE_PY_OVERRIDE}" ]; then
    BASE_PY="${BASE_PY_OVERRIDE}"
    echo "Using Python override: ${BASE_PY}"
else
    # On Delta, `module load python` gives the default Python 3.13+.
    module load python 2>/dev/null || true
    BASE_PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
    if [ -z "${BASE_PY}" ]; then
        echo "ERROR: no Python found after 'module load python'."
        echo "       Pass an explicit interpreter: --python /path/to/python3"
        exit 1
    fi
    ver=$("${BASE_PY}" -c "import sys; v=sys.version_info; print(v.major*100+v.minor)")
    if [ "${ver}" -lt 311 ]; then
        echo "ERROR: ${BASE_PY} is Python ${ver} — need 3.11+."
        echo "       Pass an explicit interpreter: --python /path/to/python3.11"
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
# Pin dragonhpc to 0.14.1 — 0.14.2 added waitForKeys to DDRegisterClientResponse
# but the Delta system Dragon runtime has not been updated to match; 0.14.2 fails
# with AttributeError on every DDict operation on this cluster.
"${PIP}" install -q "dragonhpc==0.14.1"

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
echo "── Step 7: pandas + biopandas + matplotlib ──"
"${PIP}" install -q pandas biopandas matplotlib

# ── 8. PyRosetta ─────────────────────────────────────────────────────────────
echo ""
echo "── Step 8: PyRosetta ──"
# pyrosetta_installer handles credential lookup internally.
# Activate the venv in the environment so its subprocess pip installs there.
export VIRTUAL_ENV="${ENV_DIR}"
export PATH="${ENV_DIR}/bin:${PATH}"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# ── 9. Boltz (structure prediction — separate conda env) ─────────────────────
echo ""
echo "── Step 9: Boltz (separate conda env) ──"
# boltz 2.x is kept in a separate conda env so its dependency pins (scipy, etc.)
# don't constrain the main IMPRESS venv. Boltz 2.0+ also installs fine via pip
# in Python 3.13, but we keep the separation to avoid pin conflicts.
# s4_boltz.sh activates BOLTZ_VENV (set in delta_gpu_run.sh) instead of VIRTUAL_ENV.
MINIFORGE="${MINIFORGE:-${SCRATCH}/${USER}/miniforge3}"
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
# protein_binding.py s3() reads from BOLTZ_MSA_CACHE and embeds paths in the FASTA so
# compute nodes do not need internet access.  Entity 0 = receptor, entity 1 = peptide.
BOLTZ_MSA_CACHE="${BOLTZ_CACHE}/msa_cache"
mkdir -p "${BOLTZ_MSA_CACHE}"
echo "  Pre-computing MSAs into ${BOLTZ_MSA_CACHE}"
# IMPRESS_BASE_DIR = parent of prod_in/; IMPRESS_OUTPUT_DIR = parent of af_pipeline_outputs_multi/
_scratch="${SCRATCH}"
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
            # Use FASTA from a prior run (sequences match the actual protein); fall back to
            # a placeholder that will trigger MSA generation but gives a generic MSA.
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

# ── 10. Verify ───────────────────────────────────────────────────────────────
echo ""
echo "── Step 10: Verifying installation ──"
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
echo "  cd ${IMPRESS_DIR}/examples/protein_binding"
echo "  sbatch delta_gpu_run.sh"
echo "================================================================="
