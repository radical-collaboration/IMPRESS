#!/bin/bash
#
# Build the Foundry (RFD3) Apptainer sandbox and store it as a .tar.gz.
#
# Set before calling sbatch:
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export WORK_DIR=/path/to/your/workdir
#
# Override the output archive location:
#   export FOUNDRY_SANDBOX_TAR=/path/to/foundry_sandbox.tar.gz
#
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --gpus-per-node=1
#SBATCH --time=00:30:00
#SBATCH --job-name=pull_foundry
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

set -euo pipefail
ulimit -c 0  # disable core dumps

: "${WORK_DIR:?Set WORK_DIR before running, e.g.: export WORK_DIR=/path/to/your/workdir}"

export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-${WORK_DIR}/.apptainer_cache}"
export APPTAINER_TMPDIR=/tmp/apptainer_$$
mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"

# Build as sandbox (directory) to /tmp — no mksquashfs involved.
# Then tar to a single archive under WORK_DIR for storage.
SANDBOX=/tmp/foundry_sandbox_$$
DEST_TAR="${FOUNDRY_SANDBOX_TAR:-${WORK_DIR}/foundry_sandbox.tar.gz}"

echo "=== Building sandbox to /tmp ==="
apptainer build --sandbox "$SANDBOX" docker://rosettacommons/foundry

echo "=== Compressing sandbox to scratch ==="
tar -czf "$DEST_TAR" -C /tmp "foundry_sandbox_$$"

echo "Done: $(ls -lh "$DEST_TAR")"
rm -rf "$SANDBOX"

rm -rf "$APPTAINER_TMPDIR"
