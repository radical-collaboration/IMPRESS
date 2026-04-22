#!/bin/bash
set -euo pipefail

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"

source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    --use_msa_server \
    --cache /ocean/projects/dmr170002p/hooten/boltz \
    --output_format pdb \
    --write_full_pae \
    --override
