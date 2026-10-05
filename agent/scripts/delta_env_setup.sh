#!/bin/bash
# =============================================================================
# IMPRESS-A environment setup - Delta HPC (NCSA)
#
# Adapted from the original IMPRESS project's
# examples/small_molecule_binding/delta_env_setup.sh. Builds THIS repo's own `.venv`
# (per CLAUDE.md: "Use the project .venv - do NOT use system Python") and installs the
# real small_molecule_binding toolkit's dependencies: LigandMPNN, PyRosetta, Boltz-2, and
# the foundry (RFD3) container prerequisites.
#
# Usage:
#   export SCRATCH=/scratch/<allocation>
#   bash scripts/delta_env_setup.sh [--env-dir DIR] [--python PATH]
#
# Defaults:
#   ENV_DIR   = <repo>/.venv
#   MPNN_DIR    = $SCRATCH_BASE/LigandMPNN
#   BOLTZ_CACHE = $SCRATCH_BASE/.cache/boltz
#   ($SCRATCH_BASE is $SCRATCH plus /$USER, appended only when $SCRATCH is not already
#    the per-user directory - see scripts/_scratch_base.sh)
#
# Foundry container (RFD3 backbone diffusion) is NOT built by this script - it is managed
# the same way the original IMPRESS examples do (see their pull_foundry.sh). Point
# FOUNDRY_SIF_PATH at an existing sandbox/tarball, or reuse one already built on this
# allocation's scratch, before running scripts/delta_gpu_run.sh.
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

IMPRESS_A_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Require SCRATCH ───────────────────────────────────────────────────────────
if [[ -z "${SCRATCH:-}" ]]; then
    echo "ERROR: set the SCRATCH env var to your allocation scratch root, e.g.:"
    echo "  export SCRATCH=/scratch/<allocation>"
    echo "  bash scripts/delta_env_setup.sh"
    exit 1
fi

# ── Defaults / arg parsing ────────────────────────────────────────────────────
ENV_DIR="${ENV_DIR:-${IMPRESS_A_DIR}/.venv}"
BASE_PY_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-dir) ENV_DIR="$2";       shift 2 ;;
        --python)  BASE_PY_OVERRIDE="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

PY="${ENV_DIR}/bin/python"
PIP="${ENV_DIR}/bin/pip"

# Shared with delta_gpu_run.sh: the run MUST derive the same paths this setup creates.
source "${IMPRESS_A_DIR}/scripts/_scratch_base.sh"

MPNN_DIR="${MPNN_DIR:-${SCRATCH_BASE}/LigandMPNN}"
BOLTZ_CACHE="${BOLTZ_CACHE:-${SCRATCH_BASE}/.cache/boltz}"

echo "================================================================="
echo "  IMPRESS_A_DIR      = ${IMPRESS_A_DIR}"
echo "  SCRATCH_BASE       = ${SCRATCH_BASE}"
echo "  ENV_DIR            = ${ENV_DIR}"
echo "  MPNN_DIR           = ${MPNN_DIR}"
echo "  BOLTZ_CACHE        = ${BOLTZ_CACHE}"
echo "================================================================="

# ── 1. Create venv (Python >=3.11 - Dragon's own requirement) ─────────────────
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
        echo "python3.11+ not in PATH - trying modules..."
        for mod in python/3.13.5-gcc13.3.1 cray-python/3.12.12 miniforge3-python; do
            module load "${mod}" 2>/dev/null || true
            BASE_PY=$(_find_python || true)
            [ -n "${BASE_PY}" ] && echo "  loaded module: ${mod}" && break
        done
    fi
    if [ -z "${BASE_PY}" ]; then
        echo "ERROR: no Python 3.11+ interpreter found."
        echo "       Pass an explicit interpreter:  --python /path/to/python3.11"
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

# ── 3. IMPRESS-A itself (editable), pulling radical.asyncflow + rhapsody-py ───
echo ""
echo "── Step 3: IMPRESS-A (editable, pulls radical.asyncflow>=0.5.1, rhapsody-py>=0.5.0) ──"
"${PIP}" install -q -e "${IMPRESS_A_DIR}[dev]"

# pyproject.toml's base rhapsody-py dependency has no [dragon] extra - install it
# explicitly, or Dragon backend resolution (exec/backend.py's get_backend("dragon", ...))
# fails at runtime even though the plain package imports fine.
echo ""
echo "── Step 3b: rhapsody-py[dragon,telemetry] ──"
"${PIP}" install -q "rhapsody-py[dragon,telemetry]"

# ── 4. PyTorch (CUDA 12.1) - required by LigandMPNN + Boltz-2 ────────────────
echo ""
echo "── Step 4: PyTorch (cu121) ──"
"${PIP}" install -q torch --index-url https://download.pytorch.org/whl/cu121

# ── 5. Boltz-2 ────────────────────────────────────────────────────────────────
#
# Same resolver-thrash problem the original IMPRESS setup script documented: a plain
# `pip install "boltz[cuda]"` fights numpy/gemmi/pytorch-lightning pins already present
# from steps above for a very long time. Install with --no-deps, then its actually-
# imported runtime deps individually, also --no-deps, accepting versions already present.
echo ""
echo "── Step 5: Boltz-2 ──"
"${PIP}" install -q --no-deps "boltz[cuda]"
"${PIP}" install -q --no-deps \
    pytorch_lightning torchmetrics fairscale einops einx mashumaro modelcif \
    wandb dm-tree chembl_structure_pipeline \
    cuequivariance_ops_cu12 cuequivariance_ops_torch_cu12
# EMPIRICALLY CONFIRMED (this run, live on Delta): the --no-deps list above imports the
# TOP-LEVEL boltz package but NOT `boltz.main` (the CLI entrypoint's actual import chain),
# which pulls in a much deeper transitive tree that --no-deps deliberately skips. Getting
# `boltz --help`/`boltz predict` to actually run required these additional --no-deps
# installs, found by iterating ModuleNotFoundErrors one at a time:
#   lightning_utilities, tqdm, fsspec, aiohttp   (pytorch_lightning's own core deps)
#   ihm                                          (modelcif's only dep)
#   sympy, frozendict                            (einx's own deps)
#   absl-py, attrs, wrapt                        (dm-tree's own deps)
#   requests, click, scipy, numba, llvmlite,
#   joblib, threadpoolctl                        (boltz's own direct core deps)
# Two packages needed an EXACT pin, not latest, or a deeper transitive chain reopens:
#   - scikit-learn: boltz pins ==1.6.1; an unpinned `pip install scikit-learn` resolves to
#     a much newer release that itself needs `narwhals`, which isn't in this dependency
#     tree at all otherwise.
#   - antlr4-python3-runtime: omegaconf (a hydra-core dependency, pulled in transitively)
#     hard-requires `==4.9.*`. An unpinned install resolves the latest (4.13.x), and
#     hydra-core's compiled grammar parser fails at IMPORT time with
#     "Could not deserialize ATN with version 3 (expected 4)" - a genuinely confusing
#     error for what is really just a version mismatch.
"${PIP}" install -q --no-deps \
    lightning_utilities tqdm fsspec aiohttp ihm sympy frozendict absl-py attrs wrapt \
    mpmath requests click scipy numba llvmlite joblib threadpoolctl \
    hydra-core omegaconf "antlr4-python3-runtime==4.9.3"
"${PIP}" install -q --no-deps --force-reinstall "scikit-learn==1.6.1"
"${PY}" -c "import boltz; import boltz.main; import torch; print('boltz + torch', torch.__version__, 'import OK')"

# ── 6. LigandMPNN (clone, run from source tree - no package install) ─────────
echo ""
echo "── Step 6: LigandMPNN (clone) ──"
if [ ! -d "${MPNN_DIR}" ]; then
    echo "  Cloning LigandMPNN to ${MPNN_DIR}"
    git clone https://github.com/dauparas/LigandMPNN "${MPNN_DIR}"
else
    echo "  LigandMPNN already at ${MPNN_DIR}, pulling latest"
    git -C "${MPNN_DIR}" pull --ff-only || echo "  (pull skipped - non-fast-forward or detached HEAD)"
fi
# ml-collections is NOT optional, and nothing here imports it directly: LigandMPNN's
# bundled openfold does, at `run.py` import time, so without it stage 2 of every campaign
# dies before parsing an argument. It is in LigandMPNN's own requirements.txt alongside
# dm-tree (which step 5 already installed for Boltz, which is why this was the only hole).
# Job 22669509 paid a queue slot to find it. The numpy-alias half of the same problem is
# handled at run time by MPNN_SHIM in src/impress_a/tools/ligandmpnn_agents.py - a wrapper
# rather than a patch to the checkout, because the clone is `git pull`ed above and any
# in-place edit would be silently reverted.
# Pinned: unpinned it re-resolves absl-py and PyYAML against the tree steps 4-5 spent a
# long comment block stabilising. 1.1.0 is what the full import chain was verified against
# here; the reference pipeline pins 0.1.1, and both expose what openfold uses.
"${PIP}" install -q ProDy biopython "ml-collections==1.1.0"
"${PY}" -c "import ml_collections, prody, Bio; print('LigandMPNN deps import OK')"

# ── 7. gemmi - pinned to what Boltz's step 5 install already resolved ─────────
echo ""
echo "── Step 7: gemmi ──"
"${PIP}" install -q "gemmi==0.6.5"

# ── 8. rdkit ───────────────────────────────────────────────────────────────────
echo ""
echo "── Step 8: rdkit ──"
"${PIP}" install -q "rdkit==2024.9.6"

# ── 9. Additional dependencies ─────────────────────────────────────────────────
echo ""
echo "── Step 9: pandas + biopandas ──"
"${PIP}" install -q pandas biopandas

# ── 10. PyRosetta ──────────────────────────────────────────────────────────────
#
# EMPIRICALLY CONFIRMED (this run): pyrosetta-installer's own install_pyrosetta() embeds
# empty basic-auth credentials in the wheel URL (`https://:@host/...`), which this pip
# version rejects immediately with a MISLEADING "is not a supported wheel on this
# platform" error - the wheel itself is fine (confirmed: same URL, no embedded auth,
# `pip install <url>` downloads and installs it correctly). Try the installer's own path
# first (in case a future pyrosetta-installer release fixes this); if it raises, fall back
# to reconstructing the same URL without the auth prefix and installing directly.
echo ""
echo "── Step 10: PyRosetta ──"
"${PIP}" install -q pyrosetta-installer
"${PY}" -c "
import sys
try:
    import pyrosetta_installer
    pyrosetta_installer.install_pyrosetta()
except SystemExit:
    pass
try:
    import pyrosetta
    pyrosetta.init
    print('PyRosetta already installed, done.')
    sys.exit(0)
except (ImportError, AttributeError):
    pass

print('pyrosetta-installer failed (known bad-URL bug) - falling back to a direct pip install')
import pyrosetta_installer as pi
import subprocess
os_name = pi.get_pyrosetta_os()
url_dir = f'{pi._PYROSETTA_RELEASES_URLS_[0]}/PyRosetta4.Release.python{sys.version_info.major}{sys.version_info.minor}.{os_name}.wheel/'
wheel = pi.get_latest_file(url_dir)
subprocess.check_call(['${PIP}', 'install', url_dir + wheel])
"
"${PIP}" install -q numpy

# ── 11. Boltz-2 model weights (cache warm-up on the login node) ───────────────
echo ""
echo "── Step 11: Boltz-2 model weights (cache warm-up) ──"
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
if "${ENV_DIR}/bin/boltz" predict "${_WARM_DIR}/warm.yaml" \
    --out_dir "${_WARM_DIR}/out" --cache "${BOLTZ_CACHE}" \
    --devices 1 --accelerator cpu --output_format pdb; then
    # Marks the CCD dictionary as fully extracted. Compute nodes then take the fast
    # path in `_claim_cache` (src/impress_a/tools/boltz_agents.py) instead of
    # serialising their first prediction - and, more importantly, an unextracted cache
    # is caught HERE, on a node that still has internet, rather than inside the
    # allocation where it cannot be repaired.
    touch "${BOLTZ_CACHE}/.mols_complete"
else
    echo "WARNING: boltz cache warm-up failed - check login-node internet access"
    echo "         (leaving ${BOLTZ_CACHE}/.mols_complete unwritten; preflight will flag it)"
fi
rm -rf "${_WARM_DIR}"

# ── 12. Verify ──────────────────────────────────────────────────────────────────
echo ""
echo "── Step 12: Verifying installation ──"
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
_check "impress_a"         "${PY}" -c "import impress_a; print('ok')"
_check "torch"             "${PY}" -c "import torch; print(torch.__version__)"
_check "boltz"             "${PY}" -c "import boltz; print('ok')"
_check "gemmi"             "${PY}" -c "import gemmi; print(gemmi.__version__)"
_check "rdkit"             "${PY}" -c "import rdkit; print(rdkit.__version__)"
_check "pyrosetta"         "${PY}" -c "import pyrosetta; print('ok')"
_check "ProDy"             "${PY}" -c "import prody; print(prody.__version__)"
_check "ml_collections"    "${PY}" -c "import ml_collections; print('ok')"
# `test -d` proved only that a clone happened. The checkpoints are what stage 2 actually
# opens, and this script never downloads them (LigandMPNN ships get_model_params.sh for
# that) - so say so here rather than let a fresh setup discover it inside an allocation.
_check "LigandMPNN"        test -f "${MPNN_DIR}/run.py" \
                             -a -f "${MPNN_DIR}/model_params/ligandmpnn_v_32_010_25.pt" \
                             -a -f "${MPNN_DIR}/model_params/ligandmpnn_sc_v_32_002_16.pt" \
                           && echo "run.py + both checkpoints present"
_check "boltz weights"     test -f "${BOLTZ_CACHE}/boltz2_conf.ckpt" && echo "present"

echo ""
echo "── Step 12b: real toolkit registers cleanly (impress-a specific) ──"
_TOOLKIT_CHECK=$("${ENV_DIR}/bin/impress-a" tools 2>&1) || true
echo "${_TOOLKIT_CHECK}"
for tid in rfd3_design ligandmpnn_design packmin fastrelax filter_shape boltz_predict; do
    if echo "${_TOOLKIT_CHECK}" | grep -q "${tid}"; then
        echo "  ${tid}: registered"
    else
        echo "  WARNING: ${tid} NOT found in \`impress-a tools\` output"
    fi
done

echo ""
echo "================================================================="
echo "Setup complete."
echo ""
echo "Activate with:"
echo "  source ${ENV_DIR}/bin/activate"
echo ""
echo "Run the smoke campaign:"
echo "  export SCRATCH=${SCRATCH}"
echo "  export SBATCH_ACCOUNT=<project>-delta-gpu   # or <project>-delta-gpu"
echo "  cd ${IMPRESS_A_DIR}"
echo "  sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml"
echo ""
echo "Note: the foundry container (RFD3) is NOT built by this script - point"
echo "  FOUNDRY_SIF_PATH at an existing sandbox, or build one the way the original"
echo "  IMPRESS examples/small_molecule_binding/pull_foundry.sh does."
echo "================================================================="
