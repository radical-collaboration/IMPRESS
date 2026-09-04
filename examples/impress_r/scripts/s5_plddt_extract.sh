#!/bin/bash
set -e

# Step 5: pLDDT extraction
# Args: $1=output_base_path $2=iter $3=out_name

output_base_path="$1"
iter="$2"
out_name="$3"

# plddt_extract_pipeline.py lives one level above this scripts/ directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Re-activate the IMPRESS venv inside Dragon tasks (VIRTUAL_ENV is exported by sbatch).
[ -n "${VIRTUAL_ENV:-}" ] && source "${VIRTUAL_ENV}/bin/activate"

python3 "${SCRIPT_DIR}/../plddt_extract_pipeline.py" \
    --path="${output_base_path}" \
    --iter="${iter}" \
    --out="${out_name}"
