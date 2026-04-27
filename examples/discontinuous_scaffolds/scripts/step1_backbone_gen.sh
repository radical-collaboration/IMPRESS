#!/bin/bash
set -euo pipefail

# Step 1: Backbone generation via RFDiffusion3 (apptainer)
# Args: $1=foundry_sif_path $2=output_dir $3=rfd_input_filepath $4=diffusion_batch_size

foundry_sif_path="$1"
output_dir="$2"
rfd_input_filepath="$3"
diffusion_batch_size="$4"

apptainer exec --nv "$foundry_sif_path" rfd3 design \
    out_dir="$output_dir" \
    inputs="$rfd_input_filepath" \
    skip_existing=False \
    prevalidate_inputs=True \
    diffusion_batch_size="$diffusion_batch_size"
