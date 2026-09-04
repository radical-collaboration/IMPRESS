#!/bin/bash
set -e

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir

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

# Prevent PyTorch Lightning from installing SLURM auto-requeue signal handlers.
# PL detects SLURM_JOB_ID and registers SIGTERM/SIGUSR handlers that keep the
# process group alive after Boltz finishes, causing Dragon to report
# "ProcessGroup manager is not in state State.DEAD".
unset SLURM_JOB_ID

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    ${_MSA_FLAG} \
    --cache "${BOLTZ_CACHE_DIR:-${HOME}/.boltz}" \
    --output_format pdb \
    --write_full_pae \
    --no_kernels \
    --devices 1 \
    --override \
    2>&1 | tee "${output_dir}/boltz_run.log"
# tee exits 0; check the actual boltz exit code via PIPESTATUS
test "${PIPESTATUS[0]}" -eq 0
