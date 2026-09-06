#!/bin/bash
set -e

# Step 1: Sequence prediction via ProteinMPNN
# Args: $1=mpnn_script $2=input_path $3=output_dir $4=mpnn_path $5=num_seqs $6=chain

mpnn_script="$1"
input_path="$2"
output_dir="$3"
mpnn_path="$4"
num_seqs="$5"
chain="$6"

# Re-activate the IMPRESS venv if running inside a subprocess (VIRTUAL_ENV is exported by sbatch).
[ -n "${VIRTUAL_ENV:-}" ] && source "${VIRTUAL_ENV}/bin/activate"

# Prevent any SLURM-aware library from installing signal handlers that keep the
# process group alive after MPNN exits (same class of issue fixed in s4_boltz.sh).
unset SLURM_JOB_ID SLURM_NTASKS SLURM_NODEID SLURM_LOCALID \
      SLURM_PROCID SLURM_STEP_ID SLURM_STEP_NUM_TASKS SLURM_NODELIST

python3 "$mpnn_script" \
    -pdb="$input_path" \
    -out="$output_dir" \
    -mpnn="$mpnn_path" \
    -seqs="$num_seqs" \
    -is_monomer=0 \
    -chains="$chain"
