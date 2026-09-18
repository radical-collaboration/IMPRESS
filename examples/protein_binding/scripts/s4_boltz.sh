#!/bin/bash
set -e

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir
# GPU placement is left to the execution backend; this script does not set
# CUDA_VISIBLE_DEVICES.

fasta_path="$1"
output_dir="$2"

# Boltz requires Python <=3.12 (numpy<2.0 etc.) so it lives in its own env.
# BOLTZ_VENV may point to a conda env (no bin/activate) or a pip venv; prepend
# its bin/ to PATH so the correct python/boltz are found in either case.
_BOLTZ_ENV="${BOLTZ_VENV:-${VIRTUAL_ENV:-}}"
[ -n "${_BOLTZ_ENV}" ] && export PATH="${_BOLTZ_ENV}/bin:${PATH}"
export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt

# Compute nodes typically have no internet access, so --use_msa_server is off
# by default. Set BOLTZ_USE_MSA_SERVER=1 to enable it on nodes with internet.
_MSA_FLAG=""
[ "${BOLTZ_USE_MSA_SERVER:-0}" = "1" ] && _MSA_FLAG="--use_msa_server"

# ── Test-mode stub (IMPRESS_TEST_MODE=1) ──────────────────────────────────
# Write minimal Boltz-shaped output so downstream steps (plddt_extract_pipeline)
# can run without invoking the real Boltz model.  numpy is available because
# BOLTZ_VENV/bin is already on PATH above.
if [ "${IMPRESS_TEST_MODE:-0}" = "1" ]; then
    name="$(basename "${fasta_path}" .fa)"
    pred_dir="${output_dir}/boltz_results_${name}/predictions/${name}"
    mkdir -p "${pred_dir}"
    python3 - "${pred_dir}" "${name}" <<'PYEOF'
import sys, json
import numpy as np
pred_dir, name = sys.argv[1], sys.argv[2]
n = 110  # 100 PDZ residues + 10 peptide (PEP_LEN=10 assumed by extractor)
np.savez(f"{pred_dir}/plddt_{name}_model_0.npz", plddt=np.full(n, 0.85))
np.savez(f"{pred_dir}/pae_{name}_model_0.npz",   pae=np.full((n, n), 2.0))
with open(f"{pred_dir}/confidence_{name}_model_0.json", "w") as f:
    json.dump({"iptm": 0.75, "ptm": 0.80}, f)
PYEOF
    echo "[MOCK] s4_boltz stub done for ${name}"
    exit 0
fi
# ── End test-mode stub ────────────────────────────────────────────────────

mkdir -p "${output_dir}"

_boltz_cache_dir="${BOLTZ_CACHE_DIR:-${HOME}/.boltz}"

# $_boltz_cache_dir is shared across concurrently-dispatched pipelines. boltz's own
# download_boltz2() checks `mols.exists()` (directory presence), not
# completeness, before skipping extraction -- tarfile.extractall() creates the
# "mols" directory entry immediately, so a *second* concurrent task calling
# download_boltz2() while a first one is still mid-extract sees mols/ already
# existing and skips extraction outright, then reads a half-populated
# directory and fails with "CCD component <resname> not found!" for whatever
# hasn't been extracted yet (see examples/small_molecule_binding/scripts/boltz.sh
# for the same fix, ported here after this exact race killed 13/16 pipelines
# in a production run).
#
# Fix: hold the lock for the entire check-and-repair, verify mols/ actually
# contains every file mols.tar lists (not just that the directory exists),
# and if not, delete and re-extract *inside* the lock via boltz's own
# download_boltz2() so no other concurrent task can observe a
# partially-populated mols/ while this one repairs it. A `.mols_complete`
# marker (written only after a verified-complete extraction) lets later
# invocations skip the O(45k) file-count re-check once warmed.
mkdir -p "$_boltz_cache_dir"
(
    flock -x 200

    tar_ok=false
    if tar -tf "$_boltz_cache_dir/mols.tar" >/dev/null 2>&1; then
        tar_ok=true
    fi

    mols_complete=false
    if $tar_ok && [ -f "$_boltz_cache_dir/.mols_complete" ]; then
        mols_complete=true
    elif $tar_ok && [ -d "$_boltz_cache_dir/mols" ]; then
        expected=$(tar -tf "$_boltz_cache_dir/mols.tar" | grep -vc '/$')
        actual=$(find "$_boltz_cache_dir/mols" -maxdepth 1 -type f | wc -l)
        if [ "$actual" -eq "$expected" ]; then
            mols_complete=true
            touch "$_boltz_cache_dir/.mols_complete"
        fi
    fi

    if ! $mols_complete; then
        rm -rf "$_boltz_cache_dir/mols.tar" "$_boltz_cache_dir/mols" "$_boltz_cache_dir/.mols_complete"
        BOLTZ_CACHE_DIR_FOR_PY="$_boltz_cache_dir" python -c "
import os
from pathlib import Path
from boltz.main import download_boltz2
download_boltz2(Path(os.environ['BOLTZ_CACHE_DIR_FOR_PY']))
"
        touch "$_boltz_cache_dir/.mols_complete"
    fi
) 200>"$_boltz_cache_dir/.download.lock"

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    ${_MSA_FLAG} \
    --cache "$_boltz_cache_dir" \
    --output_format pdb \
    --write_full_pae \
    --no_kernels \
    --devices 1 \
    --override
