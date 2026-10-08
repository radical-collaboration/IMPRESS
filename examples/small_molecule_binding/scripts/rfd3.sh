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

# dump_trajectories=False: the per-step *_noisy_* and *_denoised_* cif.gz files
# are 11.85 MB of each 11.92 MB output dir -- 99.4% of rfd3's footprint and ~88%
# of a whole campaign's.  Nothing in the repo reads them, and analysis_backbone
# cannot pick one up by accident: it builds its candidate list from .json files
# containing '_model_' and only then derives the structure via
# .replace('.json', '.cif.gz'), while trajectory files ship no .json at all.
# Only the 4 *_model_*.cif.gz designs and their .json metrics are kept (~71 KB).
# To inspect a trajectory for one design, re-run that rfd3 task with this True.
#
# The WORK_DIR bind is what makes inputs, outputs and the RFD3 checkpoints
# visible inside the container.  On a remote node of a `dragon -w ssh` run,
# WORK_DIR comes only from ~/.bashrc -- without it the bind is silently dropped.
apptainer exec --nv --writable-tmpfs ${WORK_DIR:+--bind "${WORK_DIR}:${WORK_DIR}"} "$foundry_sif_path" rfd3 design \
    out_dir="$output_dir" \
    inputs="$inputs" \
    skip_existing=False \
    dump_trajectories=False \
    prevalidate_inputs=True \
    diffusion_batch_size="$diffusion_batch_size"

