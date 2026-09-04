#!/bin/bash
set -euo pipefail

# Step 4: AlphaFold2 multimer prediction via ColabFold
# Args: $1=fasta_path $2=output_dir

fasta_path="$1"
output_dir="$2"

# Re-activate the IMPRESS venv inside Dragon tasks (VIRTUAL_ENV is exported by sbatch).
[ -n "${VIRTUAL_ENV:-}" ] && source "${VIRTUAL_ENV}/bin/activate"

# ── Test-mode stub (IMPRESS_TEST_MODE=1) ──────────────────────────────────
# Write minimal Boltz-shaped output so plddt_extract_pipeline can run without
# invoking the real AlphaFold model.
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
    echo "[MOCK] s4_alphafold stub done for ${name}"
    exit 0
fi
# ── End test-mode stub ────────────────────────────────────────────────────

colabfold_batch \
    --model-type alphafold2_multimer_v3 \
    --max-template-date 2020-12-01 \
    --rank multimer \
    --random-seed 999 \
    --save-all \
    --debug-logging \
    "$fasta_path" \
    "$output_dir"
