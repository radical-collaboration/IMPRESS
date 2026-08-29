#!/bin/bash
set -euo pipefail

# AlphaFold2 structure prediction via LocalColabFold
# Args: $1=colabfold_path $2=short_fasta $3=output_dir
#
# colabfold_path: root of the localcolabfold repo (contains pyproject.toml).
# colabfold_batch is resolved from .pixi/envs/default/bin/ under that root,
# bypassing pixi (not available on Delta).

colabfold_path="$1"
short_fasta="$2"
output_dir="$3"

# Prefer the venv's colabfold_batch (installed in IMPRESS venv) over the
# hooten1 pixi env, whose Python files are not world-readable on Delta.
VENV_BIN="$(dirname "$(command -v python 2>/dev/null)")"
colabfold_bin=""
for candidate in \
    "${VENV_BIN}/colabfold_batch" \
    "${colabfold_path}/.pixi/envs/default/bin/colabfold_batch"; do
    if [ -x "$candidate" ]; then
        colabfold_bin="$candidate"
        break
    fi
done
if [ -z "$colabfold_bin" ]; then
    echo "ERROR: colabfold_batch not found in venv or at $colabfold_path" >&2
    exit 1
fi
echo "[af2.sh] using colabfold_batch: $colabfold_bin"

# Use scratch for the model weights cache to avoid home quota exhaustion.
# COLABFOLD_CACHE_DIR must be set (delta_sbatch.sh exports it).
data_dir="${COLABFOLD_CACHE_DIR:-${HOME}/.cache/colabfold}"
echo "[af2.sh] data_dir: $data_dir"

"$colabfold_bin" \
    --model-type alphafold2 \
    --num-models 1 \
    --data "$data_dir" \
    --rank auto \
    --random-seed 999 \
    --save-all \
    --debug-logging \
    "$short_fasta" \
    "$output_dir"
