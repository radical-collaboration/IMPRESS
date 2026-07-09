#!/bin/bash
set -e

# Step 5: pLDDT extraction
# Args: $1=base_path $2=iter $3=out_name

base_path="$1"
iter="$2"
out_name="$3"

source /anvil/projects/x-nairr240405/mason/IMPRESS/.venv/bin/activate
#source /ocean/projects/dmr170002p/hooten/IMPRESS/.venv/bin/activate

python3 "$base_path/plddt_extract_pipeline.py" \
    --path="$base_path" \
    --iter="$iter" \
    --out="$out_name"
