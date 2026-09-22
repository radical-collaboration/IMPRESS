#!/bin/bash
# Resolve SCRATCH_BASE - the per-user directory every default path hangs off.
#
# Sourced by delta_env_setup.sh and delta_gpu_run.sh. It exists because both used to
# write "${SCRATCH}/${USER}" inline, and on Delta $SCRATCH is just as often ALREADY the
# per-user directory (/work/hdd/<project>/<user>) as the allocation root
# (/work/hdd/<project>). Appending $USER unconditionally produced
# /work/hdd/<project>/$USER/hooten1/..., and that is not cosmetic:
#
#   * the two scripts compute their defaults independently, so setup could clone
#     LigandMPNN to one path while the run looked for it at another;
#   * BOLTZ_CACHE's default would point at a directory the launcher then CREATES with
#     mkdir -p, so a doubled path yields an empty-but-present cache. Boltz treats that
#     as a cold cache and tries to download weights - on a compute node with no outbound
#     network that stalls silently until the 600s task timeout, which is exactly the
#     shape of a hang;
#   * the artifacts of a run end up somewhere other than where the operator is looking.
#
# Any explicitly exported MPNN_DIR / BOLTZ_CACHE / FOUNDRY_SIF_PATH still wins, which is
# how the doubled path stayed invisible: overriding all three hides it.
if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: _scratch_base.sh sourced with SCRATCH unset." >&2
    # `return` from a sourced file only leaves the file - the caller would carry on with
    # SCRATCH_BASE unset - so abort the calling script outright. Both callers check
    # SCRATCH themselves first; this is the backstop. An interactive shell is spared.
    case $- in
        *i*) return 1 ;;
        *)   exit 1 ;;
    esac
fi

# delta_env_setup.sh runs under `set -u`, and a batch environment does not always
# export USER (delta_gpu_run.sh unsets SLURM_EXPORT_ENV, which prunes the job env).
USER="${USER:-$(id -un)}"

SCRATCH_BASE="${SCRATCH%/}"
if [ "$(basename "${SCRATCH_BASE}")" != "${USER}" ]; then
    SCRATCH_BASE="${SCRATCH_BASE}/${USER}"
fi
export SCRATCH_BASE
