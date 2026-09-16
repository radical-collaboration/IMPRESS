#!/bin/bash
# =============================================================================
# IMPRESS Small Molecule Binding environment setup — Delta HPC (NCSA)
#
# Creates a Python 3.11+ venv and installs all dependencies.
#
# Set WORK_DIR to your personal work directory before running:
#
#   export WORK_DIR=/path/to/your/workdir
#   bash delta_env_setup.sh
#
# Prerequisites:
#   - IMPRESS source tree already cloned under $WORK_DIR/IMPRESS
#   - Internet access (login nodes have it; compute nodes do not)
#
# What this script does:
#   1. Creates a Python venv at $WORK_DIR/ve/small_mol and installs deps
#   2. Clones LigandMPNN into $WORK_DIR/LigandMPNN if not already present
#   3. Warms the Boltz-2 model weights cache at $WORK_DIR/.cache/boltz
#
# Optional overrides (CLI args):
#   --env-dir     DIR   venv location       (default: $WORK_DIR/ve/small_mol)
#   --impress-dir DIR   IMPRESS source tree  (default: $WORK_DIR/IMPRESS)
#   --python      PATH  Python interpreter   (default: auto-detected, 3.11+)
#
# After this script completes, submit the pipeline with:
#   export SBATCH_ACCOUNT=<your-project>-delta-gpu
#   cd $WORK_DIR/IMPRESS/examples/small_molecule_binding
#   sbatch delta_gpu_run.sh
#
# Note: Foundry container (RFD3) is managed separately.
#   Build once with:  sbatch pull_foundry.sh
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

if ! declare -f module &>/dev/null; then
    _lmod_init=/usr/share/lmod/lmod/init/bash
    [ -f "${_lmod_init}" ] && source "${_lmod_init}"
fi

# ── Work directory ────────────────────────────────────────────────────────────
: "${WORK_DIR:?Set WORK_DIR before running, e.g.: export WORK_DIR=/path/to/your/workdir}"

# ── Defaults / arg parsing ────────────────────────────────────────────────────
ENV_DIR="${ENV_DIR:-${WORK_DIR}/ve/small_mol}"
IMPRESS_DIR="${IMPRESS_DIR:-${WORK_DIR}/IMPRESS}"
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

MPNN_DIR="${MPNN_DIR:-${WORK_DIR}/LigandMPNN}"
BOLTZ_CACHE="${BOLTZ_CACHE:-${WORK_DIR}/.cache/boltz}"

echo "================================================================="
echo "  WORK_DIR           = ${WORK_DIR}"
echo "  ENV_DIR            = ${ENV_DIR}"
echo "  IMPRESS_DIR        = ${IMPRESS_DIR}"
echo "  MPNN_DIR           = ${MPNN_DIR}"
echo "  BOLTZ_CACHE        = ${BOLTZ_CACHE}"
echo "================================================================="

# ── 1. Create venv ────────────────────────────────────────────────────────────
echo ""
echo "── Step 1: Creating venv ──"

_find_python() {
    for candidate in python3.12 python3.11 python3 python; do
        local p
        p=$(command -v "${candidate}" 2>/dev/null) || continue
        local ver
        ver=$("${p}" -c "import sys; v=sys.version_info; print(v.major*100+v.minor)" 2>/dev/null) || continue
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
        for mod in python/3.13.5-gcc13.3.1 cray-python/3.12.12 anaconda3; do
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
    mkdir -p "$(dirname "${ENV_DIR}")"
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

# ── 6. PyTorch (CUDA 12.1) — required by LigandMPNN ─────────────────────────
echo ""
echo "── Step 6: PyTorch (cu121) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── 7. Boltz-2 ────────────────────────────────────────────────────────────────
#
# Install boltz itself with --no-deps to avoid pip's resolver hanging for hours
# on boltz's conflicting pins (numpy<2.0, gemmi==0.6.5, etc.) against packages
# already in this venv (PyRosetta needs numpy 2.x; gemmi 0.6.5 is installed
# later in Step 9). Then install boltz's runtime deps without --no-deps so
# their own sub-deps (e.g. lightning_utilities for pytorch_lightning) are
# pulled in automatically. No version pins here — pip picks versions compatible
# with the numpy already present. `pip check` will still report boltz's declared
# version mismatches as cosmetic warnings; none affect actual predict runs.
#
echo ""
echo "── Step 7: Boltz-2 ──"
"${PIP}" install -q --no-deps "boltz[cuda]"
"${PIP}" install -q \
    pytorch_lightning torchmetrics lightning_utilities fairscale \
    einops "einx" frozendict mashumaro modelcif \
    wandb "dm-tree" chembl_structure_pipeline \
    "hydra-core" numba scikit-learn trifast types-requests absl-py attrs wrapt \
    cuequivariance_ops_cu12 cuequivariance_ops_torch_cu12
"${PY}" -c "import boltz; import torch; print('boltz', getattr(boltz, '__version__', '?'), '+ torch', torch.__version__, 'import OK')"

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
#
# Pinned to 0.6.5 — boltz declares this exact version as a requirement.
# An unpinned install would pull latest and break boltz at runtime.
# 0.6.5 covers all pipeline uses: mpnn()'s CIF.GZ->PDB conversion
# (gemmi.cif.read_string, make_structure_from_block, write_pdb) and rfd3()'s
# ligand-normalization helper (read_structure, res.het_flag, write_pdb).
#
echo ""
echo "── Step 9: gemmi ──"
"${PIP}" install -q "gemmi==0.6.5"

# ── 10. rdkit — ligand atom-name graph-isomorphism mapping for guided RFD3 ────
#
# Used by rfd3()'s guided-backbone-feedback path (_infer_ligand_atom_mapping
# in small_molecule_binding.py) to reconcile Boltz-2's arbitrary ligand atom
# names against the canonical names in the ligand's .params file, via
# element+connectivity graph isomorphism (rdDetermineBonds.DetermineConnectivity
# + GetSubstructMatches) with a Kabsch-RMSD tie-break. Without this, RFD3's
# input validator rejects every guided run (ComponentValidationError) --
# confirmed as the root cause of 4/4 pipeline crashes in a real production
# run (job 21916521).
#
# Pinned to 2024.9.6, the same version already used by the offline
# scripts/derive_ligand_smiles.py tool in this repo.
#
echo ""
echo "── Step 10: rdkit ──"
"${PIP}" install -q "rdkit==2024.9.6"

# ── 11. Additional dependencies ───────────────────────────────────────────────
echo ""
echo "── Step 11: pandas + biopandas ──"
"${PIP}" install -q pandas biopandas

# ── 12. PyRosetta ─────────────────────────────────────────────────────────────
echo ""
echo "── Step 12: PyRosetta ──"
export VIRTUAL_ENV="${ENV_DIR}"
export PATH="${ENV_DIR}/bin:${PATH}"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# ── 13. Boltz-2 model weights (cache warm-up) ─────────────────────────────────
#
# Boltz has no dedicated "download weights" subcommand — weights auto-download
# on first `boltz predict` call.  Warm the cache with a trivial CPU prediction
# on a login node so compute nodes (no internet) find them already present at
# BOLTZ_CACHE.
#
echo ""
echo "── Step 13: Boltz-2 model weights (cache warm-up) ──"
mkdir -p "${BOLTZ_CACHE}"
_WARM_DIR=$(mktemp -d)
cat > "${_WARM_DIR}/warm.yaml" <<'YAML'
version: 1
sequences:
  - protein:
      id: [A]
      sequence: MAAAAAAAAAAAAAAAAAAA
      msa: empty
YAML
"${ENV_DIR}/bin/boltz" predict "${_WARM_DIR}/warm.yaml" \
    --out_dir "${_WARM_DIR}/out" --cache "${BOLTZ_CACHE}" \
    --devices 1 --accelerator cpu --output_format pdb \
    || echo "WARNING: boltz cache warm-up failed — check login-node internet access"
rm -rf "${_WARM_DIR}"

# ── 14. Verify ────────────────────────────────────────────────────────────────
echo ""
echo "── Step 14: Verifying installation ──"
_check() {
    local label="$1"; shift
    if out=$("$@" 2>&1); then
        echo "  [OK] ${label}: ${out}"
    else
        echo "  [WARN] ${label} failed:"
        echo "    ${out}" | head -3
    fi
}
_check "radical.asyncflow" "${PY}" -c "import radical.asyncflow; print(radical.asyncflow.__version__)"
_check "rhapsody-py"       "${PY}" -c "import rhapsody; print('ok')"
_check "impress"           "${PY}" -c "import impress; print('ok')"
_check "torch"             "${PY}" -c "import torch; print(torch.__version__)"
_check "boltz"             "${PY}" -c "import boltz; print('ok')"
_check "gemmi"             "${PY}" -c "import gemmi; print(gemmi.__version__)"
_check "rdkit"             "${PY}" -c "import rdkit; print(rdkit.__version__)"
_check "pyrosetta"         "${PY}" -c "import pyrosetta; print('ok')"
_check "ProDy"             "${PY}" -c "import prody; print(prody.__version__)"
_check "LigandMPNN"        test -d "${MPNN_DIR}" && echo "present"
_check "boltz weights"     test -f "${BOLTZ_CACHE}/boltz2_conf.ckpt" && echo "present"

echo ""
echo "================================================================="
echo "Setup complete."
echo ""
echo "Submit the pipeline:"
echo "  export SBATCH_ACCOUNT=<your-project>-delta-gpu"
echo "  cd ${IMPRESS_DIR}/examples/small_molecule_binding"
echo "  sbatch delta_gpu_run.sh"
echo "================================================================="
