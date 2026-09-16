#!/bin/bash
# =============================================================================
# IMPRESS SMB-ROME — ROME addon for the small_molecule_binding environment
#
# This script adds ROME-A to an existing venv created by
# examples/small_molecule_binding/delta_env_setup.sh.
# Run that script first; this one only installs ROME on top.
#
# Usage:
#   export WORK_DIR=/path/to/your/workdir
#   bash delta_env_setup.sh
#
# Prerequisites:
#   - examples/small_molecule_binding/delta_env_setup.sh already completed
#   - ROME source tree cloned under $WORK_DIR/ROME
#   - Internet access (login nodes have it; compute nodes do not)
#
# Optional overrides (CLI args):
#   --env-dir     DIR   venv location       (default: $WORK_DIR/ve/small_mol)
#   --impress-dir DIR   IMPRESS source tree  (default: $WORK_DIR/IMPRESS)
#   --rome-dir    DIR   ROME source tree     (default: $WORK_DIR/ROME)
#
# After this script completes, submit the pipeline with:
#   export SBATCH_ACCOUNT=<your-project>-delta-gpu
#   cd $WORK_DIR/IMPRESS/examples/smb_rome
#   sbatch delta_gpu_run.sh
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
fi

# ── Work directory ────────────────────────────────────────────────────────────
: "${WORK_DIR:?Set WORK_DIR before running, e.g.: export WORK_DIR=/path/to/your/workdir}"

# ── Defaults / arg parsing ────────────────────────────────────────────────────
ENV_DIR="${ENV_DIR:-${WORK_DIR}/ve/small_mol}"
IMPRESS_DIR="${IMPRESS_DIR:-${WORK_DIR}/IMPRESS}"
ROME_DIR="${ROME_DIR:-${WORK_DIR}/ROME}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --env-dir)      ENV_DIR="$2";      shift 2 ;;
        --impress-dir)  IMPRESS_DIR="$2";  shift 2 ;;
        --rome-dir)     ROME_DIR="$2";     shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

PY="${ENV_DIR}/bin/python"
PIP="${ENV_DIR}/bin/pip"

echo "================================================================="
echo "  WORK_DIR           = ${WORK_DIR}"
echo "  ENV_DIR            = ${ENV_DIR}"
echo "  IMPRESS_DIR        = ${IMPRESS_DIR}"
echo "  ROME_DIR           = ${ROME_DIR}"
echo "================================================================="

# ── 1. Verify base venv exists ────────────────────────────────────────────────
echo ""
echo "── Step 1: Checking base venv ──"
if [ ! -x "${PY}" ]; then
    echo "ERROR: venv not found at ${ENV_DIR}"
    echo "       Run examples/small_molecule_binding/delta_env_setup.sh first."
    exit 1
fi
echo "  Base venv OK: $("${PY}" --version)"

# ── 2. ROME ───────────────────────────────────────────────────────────────────
echo ""
echo "── Step 2: ROME (editable) ──"
if [ ! -d "${ROME_DIR}" ]; then
    echo "ERROR: ROME_DIR not found: ${ROME_DIR}"
    echo "       Clone ROME and re-run, or pass --rome-dir /path/to/ROME"
    exit 1
fi
"${PIP}" install -q -e "${ROME_DIR}"
echo "  ROME installed from ${ROME_DIR}"

# ── 3. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "── Step 3: Verifying ──"
_check() {
    local label="$1"; shift
    if out=$("$@" 2>&1); then
        echo "  [OK] ${label}: ${out}"
    else
        echo "  [WARN] ${label} failed:"
        echo "    ${out}" | head -3
    fi
}
_check "impress" "${PY}" -c "import impress; print('ok')"
_check "rome"    "${PY}" -c "import rome; print('ok')"

echo ""
echo "================================================================="
echo "ROME addon complete."
echo ""
echo "Submit the pipeline:"
echo "  export SBATCH_ACCOUNT=<your-project>-delta-gpu"
echo "  cd ${IMPRESS_DIR}/examples/smb_rome"
echo "  sbatch delta_gpu_run.sh"
echo ""
echo "Smoke test (no GPU needed for training):"
echo "  ROME_TRAINER=dummy sbatch delta_gpu_run.sh"
echo "================================================================="
