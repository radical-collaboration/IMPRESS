#!/bin/bash
#
# Small Molecule Binding Pipeline — SLURM batch script (Delta HPC / GPU)
#
# Set before calling sbatch (only SBATCH_ACCOUNT and SCRATCH are required;
# the rest default to standard Delta locations):
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export SCRATCH=/scratch/<allocation>
#
# Optional overrides (all have defaults based on $SCRATCH, which on Delta is
# already per-user, e.g. /scratch/<alloc>/<user> -- do not add $USER again):
#   export MPNN_DIR=/path/to/LigandMPNN
#   export BOLTZ_CACHE=/path/to/boltz_cache
#
# Foundry container (RFD3):
#   The foundry sandbox is stored as a .tar.gz on scratch (built by pull_foundry.sh).
#   This script extracts it to /tmp at job start (no scratch quota cost) and removes
#   it on exit.  Override FOUNDRY_TAR to point to a different archive, or set
#   FOUNDRY_SIF_PATH directly to skip extraction entirely (e.g. a pre-extracted dir).
#
# Example:
#   sbatch delta_gpu_run.sh
#   sbatch delta_gpu_run.sh run_nonadaptive.py   # non-adaptive runner
#
# Account: set SBATCH_ACCOUNT=<project>-delta-gpu before calling sbatch
#SBATCH --account=bdyk-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=240G
#SBATCH --time=48:00:00
# Sizing notes (measured, do not shrink casually):
#   cpus-per-task=64 — the whole node.  Requesting 4 GPUs already reserves and
#     bills the entire node, and billing is max(cpu*31.25, mem/8, gpu*500) under
#     PriorityFlags=MAX_TRES, so 64 cores costs exactly the same as 16 (both
#     resolve to the gpu term, 2000).  `seff` on the three 4h TIMEOUT runs
#     (21933600/21945304/21960876) showed 97.7-98.1% CPU efficiency on 16 cores
#     — the job was CPU-starved, which is why those runs never finished.
#   mem=240G — node RealMemory is 257637MB but MemSpecLimit=8450 is reserved,
#     so 249187MB is the allocatable ceiling.  Those same runs used only ~65GB
#     for 4 pipelines (~16GB each), so 240G covers 8+ pipelines with headroom.
#   time=48:00:00 — the gpuA40x4 partition maximum.  There is no checkpoint or
#     resume: on TIMEOUT all in-memory ensemble state is lost.  Billing is on
#     elapsed, not requested, time, and `sbatch --test-only` showed identical
#     queue start estimates for 4h and 48h, so a short request buys nothing.
# Override nodes per run without editing this file:  sbatch --nodes=2 ...
#SBATCH --job-name=impress_sm_binding
#SBATCH --mail-user=mh1314@scarletmail.rutgers.edu
#SBATCH --mail-type=ALL
#SBATCH --output=impress_%j.out
##SBATCH --error=logs/impress_%j.err
# NOTE: logs/ must exist before sbatch is called.  Create it once with:
#   mkdir -p <small_molecule_binding_dir>/logs
# NOTE: IMPRESS log output (including errors) goes to .out, not .err.
#   On failure, check logs/impress_<jobid>.out — the .err file will only
#   contain Python interpreter crashes or output from non-IMPRESS processes.

set -e

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ -z "${SBATCH_ACCOUNT:-}${SLURM_JOB_ACCOUNT:-}" ]; then
    echo "WARNING: SBATCH_ACCOUNT is not set — job may be charged to default account."
fi
echo "Account: ${SLURM_JOB_ACCOUNT:-unknown}"

if [ -z "${SCRATCH:-}" ]; then
    echo "ERROR: SCRATCH is not set."
    echo "       export SCRATCH=/scratch/<allocation> && sbatch delta_gpu_run.sh"
    exit 1
fi

# ── System library paths (Delta-specific, required by Dragon) ─────────────────
# These were hardcoded to CUDA 25.3 / mpich 8.1.32 / libfabric 1.22.0, all of
# which Delta removed in a Cray PE upgrade (/opt/cray/pe is now an NFS mount of
# cpe-26.5.3).  Single-node runs never noticed: `dragon -s` starts no transport
# agent, so three dead LD_LIBRARY_PATH entries are inert.  Multi-node is a
# different story — `dragon -m` loads HSTA, which dlopens libdfabric_ofi.so out
# of FAB_LIB and hangs with almost no diagnostic if it is missing.  Autodetect
# instead of hardcoding so the next site upgrade doesn't silently re-break this.
CUDA_HOME="${CUDA_HOME:-$(ls -d /opt/nvidia/hpc_sdk/Linux_x86_64/*/cuda/12.* 2>/dev/null | sort -V | tail -1)}"
MPI_LIB="${MPI_LIB:-$(ls -d /opt/cray/pe/mpich/*/ofi/GNU/*/lib-abi-mpich 2>/dev/null | sort -V | tail -1)}"
FAB_LIB="${FAB_LIB:-$(ls -d /opt/cray/libfabric/*/lib64 2>/dev/null | sort -V | tail -1)}"
export CUDA_HOME MPI_LIB FAB_LIB
export LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${MPI_LIB}:${FAB_LIB}:${LD_LIBRARY_PATH:-}

# Fail loudly rather than at Dragon bring-up: `dragon-config add` does NOT
# validate the path it stores, so a bad FAB_LIB is only discovered as a hang.
for _v in CUDA_HOME MPI_LIB FAB_LIB; do
    if [ -z "${!_v}" ] || [ ! -d "${!_v}" ]; then
        echo "ERROR: ${_v} does not resolve to an existing directory: '${!_v}'"
        echo "       Delta's Cray PE layout changed. Check:"
        echo "         ls -d /opt/cray/libfabric/*/lib64"
        echo "         ls -d /opt/cray/pe/mpich/*/ofi/GNU/*/lib-abi-mpich"
        echo "         ls -d /opt/nvidia/hpc_sdk/Linux_x86_64/*/cuda/12.*"
        exit 1
    fi
done
echo "CUDA_HOME:         ${CUDA_HOME}"
echo "MPI_LIB:           ${MPI_LIB}"
echo "FAB_LIB:           ${FAB_LIB}"

# ── Environment ───────────────────────────────────────────────────────────────
IMPRESS_VENV="${IMPRESS_VENV:-${HOME}/ve/impress}"
# Keep this unset: Dragon launches its per-node backends with a plain
# `srun --nodes=N --ntasks=N` and no --export flag, so srun's default
# --export=ALL is what carries PATH (the venv), SCRATCH, MPNN_DIR, BOLTZ_CACHE
# and FOUNDRY_SIF_PATH to the remote nodes.  If SLURM_EXPORT_ENV were left at
# NONE, every remote task would lose the venv and boltz.sh would exit 127.
unset SLURM_EXPORT_ENV
# Dragon's launcher issues its own srun steps inside this allocation; without
# --overlap they can collide with the batch step and hang at "job step creation
# temporarily disabled".  Dragon does not pass --overlap itself.
export SLURM_OVERLAP=1
source "${IMPRESS_VENV}/bin/activate"
# `dragon-config add` APPENDS when a key already exists, so a stale
# ofi_runtime_lib would survive as the first entry of a colon-joined list.
# Clear it first so FAB_LIB above is authoritative.
dragon-config -c >/dev/null 2>&1 || true
dragon-config add --ofi-runtime-lib="${FAB_LIB}"

# ── Tool paths (read by SmallMoleculeBindingPipeline via env vars) ─────────────
# These are picked up by the pipeline's __init__ when not passed as kwargs.
export MPNN_DIR="${MPNN_DIR:-${SCRATCH}/LigandMPNN}"

# Boltz-2 model weights cache — kept on scratch to avoid home quota exhaustion.
# Pre-warm once on a login node via delta_env_setup.sh's Step 13 (boltz has no
# dedicated "download weights" subcommand; weights auto-download on first
# `boltz predict` call).
export BOLTZ_CACHE="${BOLTZ_CACHE:-${SCRATCH}/.cache/boltz}"
mkdir -p "${BOLTZ_CACHE}"

# ── Foundry sandbox: extract to /tmp at job start, clean up on exit ───────────
# Extracting to /tmp avoids the scratch quota. Compute nodes have ample /tmp
# space that is not quota-counted.  If FOUNDRY_SIF_PATH is already set (e.g.
# a pre-built .sif or a persistent sandbox on a large allocation), extraction
# is skipped entirely.
if [ -z "${FOUNDRY_SIF_PATH:-}" ] && [ -f "${SCRATCH}/foundry.sif" ]; then
    export FOUNDRY_SIF_PATH="${SCRATCH}/foundry.sif"
fi
if [ -z "${FOUNDRY_SIF_PATH:-}" ]; then
    # The /tmp sandbox is extracted on THIS node only, so a multi-node job would
    # hand remote rfd3 tasks a FOUNDRY_SIF_PATH that does not exist there (and
    # the cleanup trap below would only clean this node).  Refuse rather than
    # fail deep inside apptainer on a compute node an hour into the run.
    if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
        echo "ERROR: multi-node job (--nodes=${SLURM_NNODES}) but no shared foundry image."
        echo "       The /tmp sandbox extraction is node-local and will not be"
        echo "       visible to rfd3 tasks scheduled on other nodes."
        echo "       Put the .sif on Lustre: ${SCRATCH}/foundry.sif"
        echo "       (or set FOUNDRY_SIF_PATH to a shared path)"
        exit 1
    fi
    FOUNDRY_TAR="${FOUNDRY_TAR:-${SCRATCH}/foundry_sandbox.tar.gz}"
    if [ ! -f "${FOUNDRY_TAR}" ]; then
        echo "ERROR: foundry sandbox tarball not found: ${FOUNDRY_TAR}"
        echo "       Build it first: sbatch pull_foundry.sh"
        echo "       (or set FOUNDRY_SIF_PATH to an existing .sif/sandbox)"
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

echo "MPNN_DIR:          ${MPNN_DIR}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "BOLTZ_CACHE:       ${BOLTZ_CACHE}"

# ── Tool existence checks ──────────────────────────────────────────────────────
if [ ! -d "${MPNN_DIR}" ]; then
    echo "ERROR: MPNN_DIR does not exist: ${MPNN_DIR}"
    echo "       Clone LigandMPNN: git clone https://github.com/dauparas/LigandMPNN ${MPNN_DIR}"
    exit 1
fi

# ── Working directory ─────────────────────────────────────────────────────────
#WORKDIR="${IMPRESS_SCRIPTS_DIR:-${SCRATCH}/${USER}/IMPRESS/examples/small_molecule_binding}"
WORKDIR="${IMPRESS_SCRIPTS_DIR:-${SCRATCH}/IMPRESS/examples/small_molecule_binding}"
cd "${WORKDIR}"
mkdir -p logs

# IMPRESS_WORK_DIR: where pipeline task dirs (p1/, p2/, …) are written.
# Defaults under logs/ so all run artifacts stay out of the source tree and are
# covered by .gitignore.  Override to write outputs elsewhere.
#
# Scoped per job.  Task dirs are {work_dir}/{name}/{taskcount}_{taskname} and
# taskcount restarts at 1 every run, so a shared work dir means each run
# OVERWRITES the previous run's task dirs in place -- silently destroying older
# artifacts and making any `logs/p*` analysis mix runs together (job 22491438
# inherited 73 stale dirs from 22466127 in p1+p2 alone).
export IMPRESS_WORK_DIR="${IMPRESS_WORK_DIR:-${WORKDIR}/logs/${SLURM_JOB_ID:-manual}}"
mkdir -p "${IMPRESS_WORK_DIR}"
echo "IMPRESS_WORK_DIR:  ${IMPRESS_WORK_DIR}"

# asyncflow writes its session dir (runinfo, captured task stdout/stderr) under
# the process cwd, which is WORKDIR above -- on Lustre, so it survives the job.

# IMPRESS_BACKEND: "dragon" (default, multi-node HPC) or "local" (single-node,
# ProcessPoolExecutor — useful for development / non-Dragon clusters).
# Set before sbatch:  IMPRESS_BACKEND=local sbatch delta_gpu_run.sh
export IMPRESS_BACKEND="${IMPRESS_BACKEND:-dragon}"
echo "IMPRESS_BACKEND:   ${IMPRESS_BACKEND}"

# IMPRESS_N_PIPELINES: concurrent design pipelines.  Each pipeline's run() is a
# sequential state machine, so this IS the job's total concurrency and it keeps
# roughly one GPU busy — default to the allocated GPU count (4 per gpuA40x4
# node) so no GPU sits idle.  Capped at the number of p{i}_in/ input dirs that
# actually exist; to go higher:  cp -r p1_in p9_in  (p1_in..p8_in are
# byte-identical replicas of the same design problem, verified by checksum).
_n_inputs=$(ls -d "${WORKDIR}"/p[0-9]*_in 2>/dev/null | wc -l)
IMPRESS_N_PIPELINES="${IMPRESS_N_PIPELINES:-$(( ${SLURM_NNODES:-1} * 4 ))}"
if [ "${_n_inputs}" -gt 0 ] && [ "${IMPRESS_N_PIPELINES}" -gt "${_n_inputs}" ]; then
    echo "NOTE: capping pipelines at ${_n_inputs} (only p{i}_in dirs that exist)"
    IMPRESS_N_PIPELINES="${_n_inputs}"
fi
export IMPRESS_N_PIPELINES
echo "N_PIPELINES:       ${IMPRESS_N_PIPELINES}"

# ── Thread caps ───────────────────────────────────────────────────────────────
# Deliberately NOT set here.  Nothing in scripts/ or the pipeline caps threads,
# so every OpenMP/MKL/PyTorch runtime would otherwise grab all 64 cores, and 11
# of the 13 tasks run as concurrent subprocesses of the runner.  But exporting
# the cap from this script does not work on a multi-node run: `dragon -w ssh`
# propagates only an allowlist (see the Run section below), so OMP_NUM_THREADS
# never reaches the runner.  run_small_molecule_binding.py therefore sets it in
# os.environ itself, where the subprocesses that matter actually inherit it, and
# sizes it from the pipeline count in use.

# ── Run ───────────────────────────────────────────────────────────────────────

RUNNER="${1:-run_small_molecule_binding.py}"

# Run config forwarded as argv (see the comment at the dragon invocations below).
RUNNER_ARGS=( --n-pipelines "${IMPRESS_N_PIPELINES}" --work-dir "${IMPRESS_WORK_DIR}" )

if [ "${IMPRESS_BACKEND}" = "dragon" ]; then
    rm -f ddict_orc*
    if [ "${SLURM_NNODES:-1}" -gt 1 ]; then
        # Multi-node.  Do NOT use `dragon -m` here: its slurm backend launcher
        # builds `srun --nodelist=` from gethostname(), which on Delta returns
        # FQDNs (dt-login03.delta.ncsa.illinois.edu) while Slurm's node naming
        # is short (scontrol: NodeName=gpub039, NodeAddr=gpub039).  The step is
        # then unsatisfiable and the whole job hangs until the wall clock:
        #   srun: error: Unable to create step for job 22456499:
        #         Requested node configuration is not available
        # (confirmed job 22456499; its network-config step, which carries no
        # --nodelist, succeeded on both nodes -- that was the only difference).
        # `--hostlist` is not a workaround: SlurmWLM.__init__ accepts _hostlist
        # and never references it.
        #
        # Instead pre-generate the network config and launch over ssh with the
        # TCP transport (the approach in ARCHIVE-run_impress.slurm):
        #   * -w ssh      -> backends are started with ssh, so no srun
        #                    --nodelist is ever built and FQDNs are fine.
        #                    Delta sets HostbasedAuthentication/EnableSSHKeysign
        #                    cluster-wide, so this needs no user ssh keys.
        #   * -t tcp      -> skips the HSTA/OFI path that dlopens libdfabric
        #                    out of FAB_LIB (the other multi-node hazard).
        #   * --network-config -> satisfies the "SSH workload manager requires a
        #                    valid hostlist or hostfile" check, which is gated
        #                    on a config file being absent.
        NETCONF_DIR="${IMPRESS_WORK_DIR}/netconf_${SLURM_JOB_ID:-$$}"
        mkdir -p "${NETCONF_DIR}"
        # dragon-network-config writes <wlm>.yaml into its *cwd*, so generate it
        # inside a per-job dir -- a bare slurm.yaml in the shared WORKDIR would
        # collide between concurrent jobs.
        ( cd "${NETCONF_DIR}" && dragon-network-config --output-to-yaml )
        NETCONF="${NETCONF_DIR}/slurm.yaml"
        if [ ! -s "${NETCONF}" ]; then
            echo "ERROR: dragon-network-config produced no usable ${NETCONF}"
            ls -la "${NETCONF_DIR}"
            exit 1
        fi
        # Pass run config as ARGV, not environment: `dragon -w ssh` forwards only
        # BASE_ENV_VARNAMES (PATH, PYTHONPATH, LD_LIBRARY_PATH, PYTHONSTARTUP,
        # VIRTUAL_ENV, DRAGON_*) to the backends, so IMPRESS_N_PIPELINES exported
        # above never reaches the runner -- job 22466127 silently ran the PROD
        # defaults for exactly this reason.  Everything after PROG is forwarded.
        echo "Running: dragon -w ssh --network-config ${NETCONF} -t tcp ${RUNNER} ${RUNNER_ARGS[*]}  (nodes=${SLURM_NNODES})"
        dragon -w ssh --network-config "${NETCONF}" -t tcp \
               "${RUNNER}" "${RUNNER_ARGS[@]}"
    else
        # Single node inherits the environment normally, but pass the flags too
        # so both paths behave identically.
        echo "Running: dragon -s ${RUNNER} ${RUNNER_ARGS[*]}  (nodes=1)"
        dragon -s "${RUNNER}" "${RUNNER_ARGS[@]}"
    fi
else
    echo "Running: python3 ${RUNNER}  (backend=${IMPRESS_BACKEND})"
    python3 "${RUNNER}"
fi

echo "=== Small Molecule Binding pipeline done: $(date) ==="
