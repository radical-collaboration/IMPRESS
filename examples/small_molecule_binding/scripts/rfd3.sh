#!/bin/bash
set -euo pipefail

# Backbone generation via RFDiffusion3 (apptainer)
# Args: $1=foundry_sif_path $2=output_dir $3=inputs $4=diffusion_batch_size $5=scaffold_arg
#   scaffold_arg: "scaffoldguided.target_pdb=<path>" or "" if unused (optional, defaults to "")

foundry_sif_path="$1"
output_dir="$2"
inputs="$3"
diffusion_batch_size="$4"

if [ $# -eq 5  ]; then
 scaffold_arg="$5"
else
 scaffold_arg=""
fi

# Prevent host ~/.local Python packages from contaminating the container
# (apptainer mounts $HOME by default; PYTHONNOUSERSITE must be SET, not unset).
unset PYTHONPATH PYTHONUSERBASE PYTHONDONTWRITEBYTECODE
export PYTHONNOUSERSITE=1

apptainer exec --nv --writable-tmpfs --bind /scratch:/scratch "$foundry_sif_path" rfd3 design \
    out_dir="$output_dir" \
    inputs="$inputs" \
    skip_existing=False \
    dump_trajectories=True \
    prevalidate_inputs=True \
    diffusion_batch_size="$diffusion_batch_size" \
    ${scaffold_arg:+$scaffold_arg}

