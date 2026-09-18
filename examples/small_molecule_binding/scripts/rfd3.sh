#!/bin/bash
set -euo pipefail

# Backbone generation via RFDiffusion3 (apptainer)
# Args: $1=foundry_sif_path $2=output_dir $3=inputs $4=diffusion_batch_size
#
# RFD3 has no scaffold/guidance CLI override (no `scaffoldguided.*` namespace,
# unlike older RFDiffusion versions). Scaffold/motif guidance is expressed
# entirely inside the InputSpecification JSON passed as `inputs=` (see
# `input`/`partial_t` fields) -- guided vs. unguided diffusion is selected by
# which JSON file the caller points `inputs` at, never by an extra CLI arg.

foundry_sif_path="$1"
output_dir="$2"
inputs="$3"
diffusion_batch_size="$4"

# Prevent host ~/.local Python packages from contaminating the container
# (apptainer mounts $HOME by default; PYTHONNOUSERSITE must be SET, not unset).
unset PYTHONPATH PYTHONUSERBASE PYTHONDONTWRITEBYTECODE
export PYTHONNOUSERSITE=1

apptainer exec --nv --writable-tmpfs ${SCRATCH:+--bind "${SCRATCH}:${SCRATCH}"} "$foundry_sif_path" rfd3 design \
    out_dir="$output_dir" \
    inputs="$inputs" \
    skip_existing=False \
    dump_trajectories=True \
    prevalidate_inputs=True \
    diffusion_batch_size="$diffusion_batch_size"

