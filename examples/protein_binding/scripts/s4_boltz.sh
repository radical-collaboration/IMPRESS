#!/bin/bash
set -euo pipefail

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"
log_file="${output_dir}_boltz.log"

echo "[s4_boltz] START: $(date)"
echo "[s4_boltz] fasta_path=${fasta_path}"
echo "[s4_boltz] output_dir=${output_dir}"
echo "[s4_boltz] log_file=${log_file}"

if [[ ! -f "${fasta_path}" ]]; then
    echo "[s4_boltz] ERROR: FASTA file not found: ${fasta_path}" >&2
    exit 1
fi
if [[ ! -s "${fasta_path}" ]]; then
    echo "[s4_boltz] ERROR: FASTA file is empty: ${fasta_path}" >&2
    exit 1
fi

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    --use_msa_server \
    --cache /ocean/projects/dmr170002p/hooten/boltz/ \
    --output_format pdb \
    --write_full_pae \
    2>&1 | tee "${log_file}"

BOLTZ_EXIT=${PIPESTATUS[0]}
echo "[s4_boltz] boltz exit code: ${BOLTZ_EXIT}"
echo "[s4_boltz] END: $(date)"
exit ${BOLTZ_EXIT}
