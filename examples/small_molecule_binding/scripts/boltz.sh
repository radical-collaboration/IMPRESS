#!/bin/bash
set -euo pipefail
# Protein+ligand co-folding via Boltz-2 (pip CLI, no container)
# Args: $1=input_yaml $2=output_dir $3=boltz_cache_dir
input_yaml="$1"; output_dir="$2"; boltz_cache_dir="$3"

# $boltz_cache_dir is shared across concurrently-running pipelines. boltz's own
# download_boltz2() checks `mols.exists()` (directory presence), not
# completeness, before skipping extraction — tarfile.extractall() creates the
# "mols" directory entry immediately, so a *second* concurrent pipeline calling
# download_boltz2() while a first one is still mid-extract sees mols/ already
# existing and skips extraction outright, then reads a half-populated
# directory and fails with "CCD component <resname> not found!" for whatever
# hasn't been extracted yet. A prior fix here only checked mols.tar's archive
# integrity under a lock, which doesn't guard this race at all (mols.tar can
# be perfectly valid while mols/ is still being extracted from it elsewhere).
#
# Fix: hold the lock for the entire check-and-repair, verify mols/ actually
# contains every file mols.tar lists (not just that the directory exists),
# and if not, delete and re-extract *inside* the lock via boltz's own
# download_boltz2() so no other concurrent pipeline can observe a
# partially-populated mols/ while this one repairs it. A `.mols_complete`
# marker (written only after a verified-complete extraction) lets later
# invocations skip the O(45k) file-count re-check once warmed.
mkdir -p "$boltz_cache_dir"
(
    flock -x 200

    tar_ok=false
    if tar -tf "$boltz_cache_dir/mols.tar" >/dev/null 2>&1; then
        tar_ok=true
    fi

    mols_complete=false
    if $tar_ok && [ -f "$boltz_cache_dir/.mols_complete" ]; then
        mols_complete=true
    elif $tar_ok && [ -d "$boltz_cache_dir/mols" ]; then
        # No marker yet (cache predates this fix, or a previous repair was
        # interrupted) -- verify extraction actually completed rather than
        # trusting mere directory existence.
        expected=$(tar -tf "$boltz_cache_dir/mols.tar" | grep -vc '/$')
        actual=$(find "$boltz_cache_dir/mols" -maxdepth 1 -type f | wc -l)
        if [ "$actual" -eq "$expected" ]; then
            mols_complete=true
            touch "$boltz_cache_dir/.mols_complete"
        fi
    fi

    if ! $mols_complete; then
        rm -rf "$boltz_cache_dir/mols.tar" "$boltz_cache_dir/mols" "$boltz_cache_dir/.mols_complete"
        BOLTZ_CACHE_DIR_FOR_PY="$boltz_cache_dir" python -c "
import os
from pathlib import Path
from boltz.main import download_boltz2
download_boltz2(Path(os.environ['BOLTZ_CACHE_DIR_FOR_PY']))
"
        touch "$boltz_cache_dir/.mols_complete"
    fi
) 200>"$boltz_cache_dir/.download.lock"

# --no_kernels: cuequivariance_ops_torch's compiled kernel (used for the fused
# triangular-multiplication op) requires cublasGemmGroupedBatchedEx, which is
# absent from nvidia-cublas-cu12==12.1.3.1 (the exact version torch==2.5.1+cu121
# pins and loads first via its own RPATH) and only present from 12.5.3.2+ --
# verified by inspecting both wheels' libcublas.so.12 with `nm -D`. That ABI
# mismatch makes the kernel import fail every time (reproduced with no GPU
# present: `python -c "import torch; import cuequivariance_ops_torch"`), not
# just intermittently, so --no_kernels (falls back to plain PyTorch ops) is
# required until torch's pinned nvidia-cublas-cu12 and cuequivariance-ops-cu12
# are reconciled -- don't remove this thinking it's a leftover.
boltz predict "$input_yaml" \
    --out_dir "$output_dir" --cache "$boltz_cache_dir" \
    --devices 1 --accelerator gpu \
    --diffusion_samples "${BOLTZ_DIFFUSION_SAMPLES:-1}" \
    --output_format pdb \
    --no_kernels
