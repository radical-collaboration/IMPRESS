#!/bin/bash
set -e

# Step 4: Structure prediction via Boltz
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"

#source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate
source /anvil/projects/x-nairr240405/mason/IMPRESS/.venv/bin/activate
source $HOME/.bashrc

boltz predict \
    "${fasta_path}" \
    --out_dir "${output_dir}" \
    --use_msa_server \
    --cache /anvil/projects/x-nairr240405/mason/boltz \
    --output_format pdb \
    --write_full_pae \
    --override
