#!/bin/bash
set -euo pipefail

# Backbone generation via RFDiffusion3 (apptainer)
# Args: $1=foundry_sif_path $2=output_dir $3=inputs $4=scaffold_arg $5=diffusion_batch_size
#   scaffold_arg: "scaffoldguided.target_pdb=<path>" or "" if unused

foundry_sif_path="$1"
output_dir="$2"
inputs="$3"
scaffold_arg="$4"
diffusion_batch_size="$5"

apptainer exec --nv "$foundry_sif_path" rfd3 design \
    out_dir="$output_dir" \
    inputs="$inputs" \
    ${scaffold_arg:+$scaffold_arg} \
    skip_existing=False \
    dump_trajectories=True \
    prevalidate_inputs=True \
    diffusion_batch_size="$diffusion_batch_size"
