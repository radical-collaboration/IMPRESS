#!/bin/bash
set -e

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"

#source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate
source /anvil/projects/x-nairr240405/mason/IMPRESS/.venv/bin/activate
module load modtree/gpu
export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt

# Boltz caches MSA in boltz_results_<name>/msa/ and reuses it across runs even with
# --override, so pass 2+ would fold new MPNN-designed sequences using the pass-1 MSA.
# Delete the stale MSA before each run to force recomputation for the current sequence.
fasta_stem=$(basename "${fasta_path}" .fa)
stale_msa="${output_dir}/boltz_results_${fasta_stem}/msa"
if [ -d "${stale_msa}" ]; then
    rm -rf "${stale_msa}"
fi

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    --use_msa_server \
    --cache /anvil/projects/x-nairr240405/mason/boltz \
    --output_format pdb \
    --write_full_pae \
    --override
