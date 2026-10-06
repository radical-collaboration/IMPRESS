#!/bin/bash
#
# IMPRESS-A small-molecule-binding campaign - SLURM batch script (Delta HPC / GPU)
#
# Adapted from the original IMPRESS project's
# examples/small_molecule_binding/delta_gpu_run.sh.
#
# Set before calling sbatch (only SBATCH_ACCOUNT and WORK_DIR are required):
#   export SBATCH_ACCOUNT=<project>-delta-gpu     # <project>-delta-gpu or <project>-delta-gpu
#   export WORK_DIR=/work/nvme/<project>/$USER        # NVMe-backed; see "Why NVMe" below
#
# Why NVMe, and why this replaced SCRATCH: every default path here used to hang off
# $SCRATCH, which on Delta resolves under /work/hdd - HDD-backed Lustre. Measured on
# that filesystem, `import pyrosetta` alone takes 471s (a 598 MB rosetta.so, demand-paged)
# and `import torch` ~280s, which is most of what LigandMPNN's 292.6s in job 22675512 was
# and the entire reason packmin could not start inside its 300s budget. $SCRATCH was also
# ambiguous - sometimes the allocation root, sometimes already the per-user directory -
# which is what scripts/_scratch_base.sh existed to paper over. WORK_DIR is unambiguous by
# construction and points at NVMe, so both problems go away together. Ported from the
# reference pipeline's IMPRESS commits 7ad76f6 and 3c7c67d (PR #67).
#
# Optional overrides:
#   export MPNN_DIR=/path/to/LigandMPNN
#   export BOLTZ_CACHE=/path/to/boltz_cache
#   export FOUNDRY_SIF_PATH=/path/to/extracted/foundry/sandbox   # skips tarball extraction
#   export FOUNDRY_TAR=/path/to/foundry_sandbox.tar.gz           # default: see below
#
# Example:
#   sbatch scripts/delta_gpu_run.sh                                    # full campaign
#   sbatch scripts/delta_gpu_run.sh campaigns/delta-small-molecule-smoke.yaml  # smoke test
#
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=240G
#SBATCH --time=12:00:00
# Sizing notes - measured by the original IMPRESS project, do not shrink casually:
#   cpus-per-task=64 - the whole node, and it is FREE. Requesting 4 GPUs already reserves
#     and bills the entire node, and billing is max(cpu*31.25, mem/8, gpu*500) under
#     PriorityFlags=MAX_TRES, so 64 cores resolves to the same gpu term (2000) as 16.
#     `seff` on three 4h TIMEOUT runs (21933600/21945304/21960876) showed 97.7-98.1% CPU
#     efficiency on 16 cores - those jobs were CPU-starved, which is why they never
#     finished. We were asking for the starved shape at the unstarved price.
#   mem=240G - node RealMemory is 257637MB less MemSpecLimit 8450, so 249187MB is the
#     allocatable ceiling.
#   time=12:00:00 - NOT the 48h partition maximum, deliberately. The wall clock is a
#     backstop against a hung Dragon teardown: on IMPRESS job 22491438 `flow.shutdown()`
#     never returned after all work finished, and the job sat 60 minutes before being
#     scancelled - ~64 GPU-h, 37% of its billed total, for zero output. A 48h request
#     would let an unattended hang bill proportionally more. `sbatch --test-only` returns
#     an identical queue start estimate for 8/12/16/24/48h, so shortening costs nothing in
#     scheduling, and billing is on elapsed time either way. Do not go below 12h: there is
#     no checkpoint or resume, so a TIMEOUT loses all in-memory campaign state.
#     We additionally bound teardown in code - see `backend_shutdown_timeout_s` - which
#     the upstream pipeline does not; the wall clock is our second line, not our first.
# Override nodes per run without editing this file:  sbatch --nodes=2 ...
#SBATCH --job-name=impress_a_sm_binding
#SBATCH --mail-user=<your email>
#SBATCH --mail-type=ALL
#SBATCH --output=impress_a_%j.out
# NOTE: IMPRESS-A log output (including errors) goes to .out, not .err, mirroring the
#   original IMPRESS scripts' own convention - on failure check impress_a_<jobid>.out.

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set - job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

if [ -z "${WORK_DIR:-}" ]; then
    echo "ERROR: WORK_DIR is not set."
    echo "       export WORK_DIR=/work/nvme/<project>/\$USER && sbatch scripts/delta_gpu_run.sh"
    if [ -n "${SCRATCH:-}" ]; then
        echo
        echo "       NOTE: \$SCRATCH is set (${SCRATCH}) but is no longer read. It pointed at"
        echo "       HDD-backed Lustre; WORK_DIR replaces it and should be on /work/nvme."
    fi
    exit 1
fi

IMPRESS_A_DIR="${IMPRESS_A_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# WORK_DIR is taken as-is: it IS the per-user directory, which is the whole point of
# replacing $SCRATCH (see the header). No _scratch_base.sh, no $USER appending, no way for
# setup and run to disagree about where the tool trees live.
WORK_DIR="${WORK_DIR%/}"
export WORK_DIR

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
# These were hardcoded to CUDA 25.3 / mpich 8.1.32 / libfabric 1.22.0. Delta removed all
# three in a Cray PE upgrade (/opt/cray/pe is now an NFS mount of cpe-26.5.3) - even the
# case changed, `ofi/gnu` -> `ofi/GNU`. Single-node runs never noticed: `dragon -s` starts
# no transport agent, so dead LD_LIBRARY_PATH entries are inert. Multi-node is a different
# story - the transport dlopens libdfabric_ofi.so out of FAB_LIB and hangs with almost no
# diagnostic if it is missing. Autodetect so the next site upgrade doesn't silently
# re-break this.
CUDA_HOME="${CUDA_HOME:-$(ls -d /opt/nvidia/hpc_sdk/Linux_x86_64/*/cuda/12.* 2>/dev/null | sort -V | tail -1)}"
MPI_LIB="${MPI_LIB:-$(ls -d /opt/cray/pe/mpich/*/ofi/GNU/*/lib-abi-mpich 2>/dev/null | sort -V | tail -1)}"
FAB_LIB="${FAB_LIB:-$(ls -d /opt/cray/libfabric/*/lib64 2>/dev/null | sort -V | tail -1)}"
export CUDA_HOME MPI_LIB FAB_LIB
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

# Fail loudly rather than at Dragon bring-up: `dragon-config add` does NOT validate the
# path it stores, so a bad FAB_LIB is only ever discovered as a hang.
for _v in CUDA_HOME MPI_LIB FAB_LIB; do
    if [ -z "${!_v}" ] || [ ! -d "${!_v}" ]; then
        echo "ERROR: ${_v} does not resolve to an existing directory: '${!_v}'"
        echo "       Delta's Cray PE layout changed. Check:"
        echo "         ls -d /opt/nvidia/hpc_sdk/Linux_x86_64/*/cuda/12.*"
        echo "         ls -d /opt/cray/pe/mpich/*/ofi/GNU/*/lib-abi-mpich"
        echo "         ls -d /opt/cray/libfabric/*/lib64"
        exit 1
    fi
done
echo "CUDA_HOME:         ${CUDA_HOME}"
echo "MPI_LIB:           ${MPI_LIB}"
echo "FAB_LIB:           ${FAB_LIB}"

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_A_VENV="${IMPRESS_A_VENV:-${IMPRESS_A_DIR}/.venv}"
# Dragon launches its per-node backends with a plain `srun` and no `--export`, so srun's
# default `--export=ALL` is what carries PATH (the venv), WORK_DIR and the tool paths. Left
# at NONE, every remote task loses the venv.
unset SLURM_EXPORT_ENV
# Dragon issues its own srun steps inside this allocation and does not pass `--overlap`
# itself; without this they collide with the batch step and hang at "job step creation
# temporarily disabled".
export SLURM_OVERLAP=1
source "${IMPRESS_A_VENV}/bin/activate"
# `-c` first: `dragon-config add` APPENDS when a key already exists, so a stale
# ofi_runtime_lib would survive as the first entry of a colon-joined list - which is
# exactly what happened here while the hardcoded FAB_LIB above pointed at a removed path.
dragon-config -c >/dev/null 2>&1 || true
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths (read by the rfd3/ligandmpnn/rosetta/boltz task agents) ────────
export MPNN_DIR="${MPNN_DIR:-${WORK_DIR}/LigandMPNN}"
export BOLTZ_CACHE="${BOLTZ_CACHE:-${WORK_DIR}/.cache/boltz}"
mkdir -p "${BOLTZ_CACHE}"

# ── Foundry sandbox: extract to /tmp at job start, clean up on exit ───────────
for _sif in "${WORK_DIR}/foundry.sif"; do
    if [ -z "${FOUNDRY_SIF_PATH:-}" ] && [ -f "${_sif}" ]; then
        export FOUNDRY_SIF_PATH="${_sif}"
    fi
done
if [ -z "${FOUNDRY_SIF_PATH:-}" ]; then
    FOUNDRY_TAR="${FOUNDRY_TAR:-${WORK_DIR}/foundry_sandbox.tar.gz}"
    if [ ! -f "${FOUNDRY_TAR}" ]; then
        echo "ERROR: foundry sandbox tarball not found: ${FOUNDRY_TAR}"
        echo "       Build it the way the original IMPRESS examples' pull_foundry.sh does,"
        echo "       or set FOUNDRY_SIF_PATH to an existing .sif/sandbox."
        exit 1
    fi
    _FOUNDRY_TMP="/tmp/foundry_${SLURM_JOB_ID:-$$}"
    echo "Extracting foundry sandbox from ${FOUNDRY_TAR} to ${_FOUNDRY_TMP} ..."
    mkdir -p "${_FOUNDRY_TMP}"
    tar -xzf "${FOUNDRY_TAR}" -C "${_FOUNDRY_TMP}" --strip-components=1
    export FOUNDRY_SIF_PATH="${_FOUNDRY_TMP}"
    # shellcheck disable=SC2064
    trap "echo 'Removing ${_FOUNDRY_TMP}'; rm -rf '${_FOUNDRY_TMP}'" EXIT
fi

echo "WORK_DIR:          ${WORK_DIR}"
echo "MPNN_DIR:          ${MPNN_DIR}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "BOLTZ_CACHE:       ${BOLTZ_CACHE}"

# ── Tool existence checks ──────────────────────────────────────────────────────
if [ ! -d "${MPNN_DIR}" ]; then
    echo "ERROR: MPNN_DIR does not exist: ${MPNN_DIR}"
    echo "       Run scripts/delta_env_setup.sh first (clones LigandMPNN)."
    exit 1
fi

# ── Campaign spec ──────────────────────────────────────────────────────────────
# Resolve before cd'ing into WORKDIR - a relative path (as in the smoke-test example
# above) would otherwise be looked up inside the per-job scratch dir, not the repo.
CAMPAIGN="${1:-${IMPRESS_A_DIR}/campaigns/delta-small-molecule.yaml}"
if [ ! -f "${CAMPAIGN}" ]; then
    echo "ERROR: campaign spec not found: ${CAMPAIGN} (relative to $(pwd))"
    exit 1
fi
CAMPAIGN="$(realpath "${CAMPAIGN}")"

# ── Working directory ─────────────────────────────────────────────────────────
# No IMPRESS_WORK_DIR/IMPRESS_SESSION_DIR indirection here (unlike the old scripts) -
# impress_a's CampaignSpec.root and asyncflow's own session dir both resolve relative to
# the process CWD (see CLAUDE.md's asyncflow-writes-into-CWD gotcha), so `cd`ing into a
# per-job scratch directory before launch is sufficient.
WORKDIR="${IMPRESS_A_WORKDIR:-${WORK_DIR}/impress_a_runs/${SLURM_JOB_ID:-manual}}"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"

# ── Model ────────────────────────────────────────────────────────────
MODEL="${IMPRESS_A_MODEL:-D}"
echo "Campaign:          ${CAMPAIGN}"
echo "Model:             ${MODEL}"
echo "Working directory: ${WORKDIR}"

RUNNER="${IMPRESS_A_DIR}/scripts/delta_run_campaign.py"
RUNNER_ARGS=( run "${CAMPAIGN}" --model "${MODEL}" )

# Stale Dragon dictionary-orchestrator files from a previous run in this directory.
rm -f ddict_orc*

if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
    # NOT `dragon -m`. Its slurm launcher builds `srun --nodelist=` from gethostname(),
    # which on Delta returns FQDNs (gpub039.delta.ncsa.illinois.edu) while Slurm's node
    # naming is short (gpub039). The step is then unsatisfiable and the whole job hangs
    # until the wall clock - confirmed on IMPRESS job 22456499:
    #   srun: error: Unable to create step for job 22456499: Requested node
    #   configuration is not available
    # `--hostlist` is not a workaround: SlurmWLM.__init__ accepts `_hostlist` and never
    # references it. The working combination is three-part:
    #   -w ssh            no --nodelist is ever built. Delta sets HostbasedAuthentication
    #                     and EnableSSHKeysign cluster-wide, so this needs no user keys.
    #   -t tcp            skips the HSTA/OFI path that dlopens libdfabric_ofi.so.
    #   --network-config  satisfies the "SSH workload manager requires a valid hostlist
    #                     or hostfile" check, which gates on the config being non-None.
    # `dragon-network-config` writes <wlm>.yaml into its CWD, so generate it in a per-job
    # directory - a bare slurm.yaml in a shared WORKDIR collides between concurrent jobs.
    NETCONF_DIR="${WORKDIR}/netconf_${SLURM_JOB_ID:-manual}"
    mkdir -p "${NETCONF_DIR}"
    ( cd "${NETCONF_DIR}" && dragon-network-config --output-to-yaml )
    NETCONF="${NETCONF_DIR}/slurm.yaml"
    if [ ! -s "${NETCONF}" ]; then
        echo "ERROR: dragon-network-config produced no usable ${NETCONF}"
        ls -la "${NETCONF_DIR}"
        exit 1
    fi
    echo "Network config:    ${NETCONF}"
    echo "Running: dragon -w ssh --network-config ${NETCONF} -t tcp ${RUNNER} ${RUNNER_ARGS[*]}  (nodes=${SLURM_NNODES})"
    dragon -w ssh --network-config "${NETCONF}" -t tcp "${RUNNER}" "${RUNNER_ARGS[@]}"
else
    echo "Running: dragon -s ${RUNNER} ${RUNNER_ARGS[*]}  (nodes=1)"
    dragon -s "${RUNNER}" "${RUNNER_ARGS[@]}"
fi

echo "=== IMPRESS-A small-molecule-binding campaign done: $(date) ==="
