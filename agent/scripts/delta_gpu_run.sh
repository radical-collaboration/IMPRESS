#!/bin/bash
#
# IMPRESS-A small-molecule-binding campaign - SLURM batch script (Delta HPC / GPU)
#
# Adapted from the original IMPRESS project's
# examples/small_molecule_binding/delta_gpu_run.sh.
#
# Set before calling sbatch (only SBATCH_ACCOUNT and WORK_DIR are required):
#   export SBATCH_ACCOUNT=<project>-delta-gpu
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
##SBATCH --mail-user=<your email>   # enable to mail someone other than the submitter
#SBATCH --mail-type=ALL
#SBATCH --output=impress_a_%j.out
# NOTE: IMPRESS-A log output (including errors) goes to .out, not .err, mirroring the
#   original IMPRESS scripts' own convention. On exit it is moved to
#   $WORK_DIR/impress_a_runs/<jobid>_<campaign>/slurm.out; it stays here as
#   impress_a_<jobid>.out only if the job died before that directory existed.

set -e

# ── Exit handling ─────────────────────────────────────────────────────────────
# One EXIT handler for everything the job leaves behind, so a run directory ends up
# self-contained whichever way the job ends (TIMEOUT's SIGTERM included; SIGKILL is not):
# the foundry /tmp copy goes, empty asyncflow session dirs and Dragon's ddict_orc* files go,
# the manifest gets its end time and exit code, and this job's SLURM .out moves in beside
# campaign.log as slurm.out. A job that dies before WORKDIR exists keeps its .out in the
# submit directory, which is where you would look for it anyway.
_manifest() {   # _manifest key=value ... - merge into ${WORKDIR}/manifest.json
    python3 - "${WORKDIR}/manifest.json" "$@" <<'PY'
import json, sys
path, *pairs = sys.argv[1:]
try:
    with open(path) as f:
        m = json.load(f)
except (OSError, ValueError):
    m = {}
for kv in pairs:
    k, _, v = kv.partition("=")
    m[k] = {"true": True, "false": False}.get(v, int(v) if v.lstrip("-").isdigit() else v)
with open(path, "w") as f:
    json.dump(m, f, indent=2)
    f.write("\n")
PY
}
_finish() {
    local rc=$?
    if [ -n "${_NVSMI_PID:-}" ]; then
        kill "${_NVSMI_PID}" 2>/dev/null || true
    fi
    # The arm-C control sidecar, children first. It is a subshell whose child is the
    # `impress-a control` actually holding the connection, and a non-interactive shell does
    # not give a background job its own process group - so there is no group to signal and
    # killing the subshell alone would leave a caller talking to a plane that is going away.
    if [ -n "${_SIDECAR_PID:-}" ]; then
        pkill -P "${_SIDECAR_PID}" 2>/dev/null || true
        kill "${_SIDECAR_PID}" 2>/dev/null || true
    fi
    # sacct and seff INSIDE the job, which cost a day to learn the other way round: a figure
    # queried afterwards cannot be reproduced, and `impress-a compare` charges every node an
    # arm held from `allocation_nodes` here rather than from the campaign's own clock. A
    # missing file makes the harness report the allocation as unknown rather than divide by a
    # guess - which is what once printed "at most nan% of the billed GPU time had a GPU task
    # running" as a finding.
    if [ -n "${WORKDIR:-}" ] && [ -d "${WORKDIR}" ] && [ -n "${SLURM_JOB_ID:-}" ]; then
        if command -v sacct >/dev/null 2>&1; then
            sacct -j "${SLURM_JOB_ID}" --json > "${WORKDIR}/sacct.json" 2>/dev/null || true
        fi
        if command -v seff >/dev/null 2>&1; then
            seff "${SLURM_JOB_ID}" > "${WORKDIR}/seff.txt" 2>/dev/null || true
        fi
    fi
    if [ -n "${_FOUNDRY_TMP:-}" ]; then
        echo "Removing ${_FOUNDRY_TMP}"
        rm -rf "${_FOUNDRY_TMP}" || true
    fi
    if [ -n "${WORKDIR:-}" ] && [ -d "${WORKDIR}" ]; then
        find "${WORKDIR}" -maxdepth 2 -name 'asyncflow.session.*' -type d -empty -delete || true
        rm -f "${WORKDIR}"/ddict_orc* || true
        _manifest "finished=$(date -Iseconds)" "exit_code=${rc}" || true
        local out="${SLURM_SUBMIT_DIR:-.}/impress_a_${SLURM_JOB_ID:-}.out"
        if [ -n "${SLURM_JOB_ID:-}" ] && [ -f "${out}" ]; then
            echo "Moving ${out} -> ${WORKDIR}/slurm.out"
            cp "${out}" "${WORKDIR}/slurm.out" && rm -f "${out}" || true
        fi
    fi
}
trap _finish EXIT

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

# ── The arm ───────────────────────────────────────────────────────────────────
# Resolved HERE, above the trust ledger, and that order is load-bearing: the per-arm trust
# dir below interpolates ${MODEL}, and this block used to sit a hundred lines further down.
# There is no `set -u`, so an unset MODEL expanded to nothing and every arm of an array
# silently shared `_trust_arms/<experiment>/` - the one ledger the pre-registration calls
# mandatory to avoid, since four concurrent processes would each admit an instance of the
# same untrusted signature and one arm's evidence would subsidise the other three.
#
# `sbatch --array=0-3` submits four arms as one job, which is the right device: one
# submission means one submit time and one priority, and a comparison whose arms queued
# separately has a confound nobody can remove afterwards.
#
# $IMPRESS_A_ARMS sets the order; $IMPRESS_A_MODEL still wins for a single-arm run.
IMPRESS_A_ARMS="${IMPRESS_A_ARMS:-A,B,C,D}"
if [ -n "${SLURM_ARRAY_TASK_ID:-}" ] && [ -z "${IMPRESS_A_MODEL:-}" ]; then
    IFS=',' read -r -a _ARMS <<< "${IMPRESS_A_ARMS}"
    if [ "${SLURM_ARRAY_TASK_ID}" -ge "${#_ARMS[@]}" ]; then
        echo "ERROR: array index ${SLURM_ARRAY_TASK_ID} with only ${#_ARMS[@]} arm(s) in"
        echo "       IMPRESS_A_ARMS=${IMPRESS_A_ARMS}. An index past the end would silently"
        echo "       run the default arm and be scored as whichever letter the reader assumed."
        exit 1
    fi
    MODEL="${_ARMS[${SLURM_ARRAY_TASK_ID}]}"
    echo "Array task ${SLURM_ARRAY_TASK_ID} of ${IMPRESS_A_ARMS} -> model ${MODEL}"
fi
MODEL="${IMPRESS_A_MODEL:-${MODEL:-D}}"

# The trust ledger is SITE-scoped and must outlive the job. Without this it resolves
# relative to the per-job WORKDIR we cd into below, so every job started with an empty
# ledger, promotion counts consecutive clean runs within one file, and nothing could ever
# be promoted - the trusted path (no forced dry-run, no 10% cost cap, concurrent instances
# of one pattern) had never executed on Delta. Jobs 22684607 and 22692304 each wrote their
# own copy holding a single run.
#
# PER-ARM, when an experiment is named. Sharing one ledger across four concurrent arms would
# let each admit an instance of the same untrusted signature, breaking one-instance-in-flight
# ACROSS processes - and one arm's clean runs would subsidise the other three, so the arms
# would differ by which ran first. `plans/arms-preregistration.md` section 10 seeds each dir
# identically with `impress-a trust --assert`, so no arm spends allocation re-earning trust on
# a Toolkit that is already proven.
if [ -n "${IMPRESS_A_EXPERIMENT:-}" ] && [ -z "${IMPRESS_A_TRUST_DIR:-}" ]; then
    export IMPRESS_A_TRUST_DIR="${WORK_DIR}/_trust_arms/${IMPRESS_A_EXPERIMENT}/${MODEL}"
fi
export IMPRESS_A_TRUST_DIR="${IMPRESS_A_TRUST_DIR:-${WORK_DIR}/_trust}"
mkdir -p "${IMPRESS_A_TRUST_DIR}"

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
    export FOUNDRY_SIF_PATH="${_FOUNDRY_TMP}"     # removed by _finish
fi

echo "WORK_DIR:          ${WORK_DIR}"
echo "MPNN_DIR:          ${MPNN_DIR}"
echo "FOUNDRY_SIF_PATH:  ${FOUNDRY_SIF_PATH}"
echo "BOLTZ_CACHE:       ${BOLTZ_CACHE}"
echo "TRUST_DIR:         ${IMPRESS_A_TRUST_DIR}"

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
# One directory per job, named <jobid>_<campaign> so a listing says what each run was:
#   manifest.json  campaign.log  slurm.out  <campaign_id>-<model>/{provenance,jobs}
#   work/ (tool workdirs)  runinfo/ (Dragon's)
# IMPRESS_A_RUN_ROOT puts provenance directly in here rather than under campaigns/_runs,
# and the executor puts asyncflow's session dir under the same root. Tool workdirs and
# campaign.log still resolve against the CWD, hence the cd.
CAMPAIGN_STEM="$(basename "${CAMPAIGN}" .yaml)"
RUN_ID="${SLURM_JOB_ID:-manual-$(date +%Y%m%d-%H%M%S)}"
WORKDIR="${IMPRESS_A_WORKDIR:-${WORK_DIR}/impress_a_runs/${RUN_ID}_${CAMPAIGN_STEM}}"
mkdir -p "${WORKDIR}"
cd "${WORKDIR}"
export IMPRESS_A_RUN_ROOT="${WORKDIR}"

# ── Command ───────────────────────────────────────────────────────────────────
# Which subcommand this allocation is for. `run` is a campaign; `validate-tasks` executes each
# Task of the chain once and checks it, which is step 1 of the four-arm experiment and what
# `impress-a trust --assert` cites as its reason.
#
# A switch here rather than a second launcher, because everything above this line - the Cray PE
# module case, the FAB_LIB autodetect, dragon-config, the ssh/tcp/network-config combination,
# SLURM_OVERLAP, the per-job directory, the manifest, the EXIT trap - was bought one burned
# allocation at a time, and two copies of it would be two things to keep in step.
#
# THE ARM PICKS IT, because for arm C there is only one arrangement that exists. `impress-a
# run --model C` is refused outright (backlog C6): model C means an external caller steers the
# campaign, and `run` attaches no control plane, so its halves blocked on an inbox nothing fed,
# timed out and ran the declared fallback - a model-D campaign reported as model C. The refusal
# is right and the launcher has to meet it: left defaulting to `run`, `sbatch --array=0-3`
# killed arm C at argparse with the other three already queued, which is one submission spent
# to discover a flag.
#
# An exported IMPRESS_A_COMMAND still wins - that is how `delta_validate_tasks.sh` sets
# `validate-tasks`, and it is also how arm C can be pointed at a validation pass.
if [ -z "${IMPRESS_A_COMMAND:-}" ] && [ "${MODEL}" = "C" ]; then
    IMPRESS_A_COMMAND=serve
    # No `impress-a ...` spelling in this message: the launcher's argv lines are extracted by
    # that prefix and checked against the parser, and a sentence is not a command line.
    echo "Model C -> serve, plus the control sidecar. A C campaign cannot be run (C6)."
fi
IMPRESS_A_COMMAND="${IMPRESS_A_COMMAND:-run}"

GIT_SHA="$(git -C "${IMPRESS_A_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY=false
if [ -n "$(git -C "${IMPRESS_A_DIR}" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    GIT_DIRTY=true
fi
# `prereg_sha` and `spec_sha` are what `impress-a compare`'s one-variable guard reads: arms
# that disagree about the pre-registration or the spec are not comparable, and that has to be
# a refusal rather than a caveat. `seed_salt` because a draw nobody can name is one nobody can
# repeat (backlog G7), and `trust_dir` because which ledger an arm used decides what scrutiny
# it ran under.
PREREG="${IMPRESS_A_DIR}/plans/arms-preregistration.md"
PREREG_SHA="$( [ -f "${PREREG}" ] && sha256sum "${PREREG}" | cut -d' ' -f1 || echo none )"
SPEC_SHA="$(sha256sum "${CAMPAIGN}" | cut -d' ' -f1)"
_manifest "job_id=${RUN_ID}" "campaign=${CAMPAIGN_STEM}" "campaign_path=${CAMPAIGN}" \
          "model=${MODEL}" "nodes=${SLURM_NNODES:-1}" "git_sha=${GIT_SHA}" \
          "git_dirty=${GIT_DIRTY}" "started=$(date -Iseconds)" \
          "gpus_per_node=${SLURM_GPUS_PER_NODE:-4}" \
          "experiment=${IMPRESS_A_EXPERIMENT:-none}" \
          "arms=${IMPRESS_A_ARMS}" \
          "array_task=${SLURM_ARRAY_TASK_ID:-none}" \
          "seed_salt=${IMPRESS_A_SEED_SALT:-none}" \
          "trust_dir=${IMPRESS_A_TRUST_DIR}" \
          "model_profile=${IMPRESS_A_MODEL_PROFILE:-none}" \
          "prereg_sha=${PREREG_SHA}" "spec_sha=${SPEC_SHA}"
echo "Campaign:          ${CAMPAIGN}"
echo "Command:           ${IMPRESS_A_COMMAND}"
if [ "${IMPRESS_A_COMMAND}" = "validate-tasks" ]; then
    echo "Model:             (none - a validation pass has no reasoner)"
else
    echo "Model:             ${MODEL}"
    echo "Model profile:     ${IMPRESS_A_MODEL_PROFILE:-none (deterministic halves)}"
fi
echo "Working directory: ${WORKDIR}"

RUNNER="${IMPRESS_A_DIR}/scripts/delta_run_campaign.py"

# The live endpoint, when one is named. A profile reaches model A's four nodes and model B's
# oracle alike - one client, both slots - and model D ignores it, having no seam to fill. Named
# in the manifest above, because a figure attributed to a model is only as good as the record
# of what answered.
PROFILE_ARGS=()
if [ -n "${IMPRESS_A_MODEL_PROFILE:-}" ]; then
    PROFILE_ARGS=( --model-profile "${IMPRESS_A_MODEL_PROFILE}" )
fi

case "${IMPRESS_A_COMMAND}" in
    run)
        RUNNER_ARGS=( run "${CAMPAIGN}" --model "${MODEL}" "${PROFILE_ARGS[@]}" )
        ;;
    serve)
        # Arm C, and the only arrangement arm C has: `plane.steer` reaches `manager.policy`,
        # so the halves must be in the process serving the plane. `impress-a serve --model C`
        # registers them here and a third party steers it over loopback - which is also the
        # security boundary this configuration can defend, since the plane has no auth and no
        # TLS (backlog C7). A caller on another host is out of scope.
        # NO --port, and no --host. Both defaults are the hardening:
        #
        #   --host 127.0.0.1  the plane has no auth and no TLS (backlog C7), so loopback is
        #                     the only boundary this configuration can defend. ADR 0014
        #                     settles C7 for exactly this arrangement and for no other.
        #   --port 0          an EPHEMERAL port. A fixed one was written here first and that
        #                     was a regression against the default: it is guessable, it
        #                     collides with a second serve on the same node, and it would be
        #                     the one piece of this arrangement an unrelated process could
        #                     find without looking. The sidecar reads the URL from the file
        #                     `serve` writes instead of being told a number.
        #
        # What this does NOT defend against is another process of the SAME user on this node,
        # and a token would not either - the same user can read the token. What rules that out
        # is the node being the job's: 4 of 4 GPUs, 64 of 64 cores and 240G of ~249G leaves
        # nothing schedulable beside it. That is an inference from the resource request rather
        # than a guarantee, so `--exclusive` is the flag to add if it ever needs to be one.
        #
        # The sidecar below is the other half of the arrangement, and without it arm C is a
        # served campaign nobody steers: the halves wait `--caller-timeout` and the planner
        # stops, which is the designed refusal and not a run.
        RUNNER_ARGS=( serve "${CAMPAIGN}" --model "${MODEL}"
                      --caller-timeout "${IMPRESS_A_CALLER_TIMEOUT:-120}" )
        _SIDECAR=yes
        ;;
    validate-tasks)
        # No --model: there is no reasoner in a validation pass. The chain comes from the
        # spec and each Task runs once, so what is being tested is the toolkit rather than
        # any decision about it.
        RUNNER_ARGS=( validate-tasks "${CAMPAIGN}" --out "${WORKDIR}/validation" )
        ;;
    *)
        echo "ERROR: IMPRESS_A_COMMAND must be run | serve | validate-tasks, got "
        echo "       '${IMPRESS_A_COMMAND}'"
        exit 1
        ;;
esac
_manifest "command=${IMPRESS_A_COMMAND}"

# Stale Dragon dictionary-orchestrator files from a previous run in this directory.
rm -f ddict_orc*

# A6: the cheap environment check, BEFORE Dragon comes up. Four defects reached real hardware
# that a preflight would have caught at submit cost, and the deep form is run once on a login
# node where its 900 s LigandMPNN probe is free. `--quick` here because a GPU allocation is
# not the place to discover MPNN_DIR is unset.
if ! impress-a preflight --quick "${CAMPAIGN}"; then
    echo "ERROR: preflight failed. Fix the environment rather than spending the allocation"
    echo "       finding out which tool cannot import - see scripts/delta_env_setup.sh."
    exit 1
fi

# G8's other half: nothing has ever sampled GPU use, and the figure that matters -
# GPU-busy share of billed GPU time - was inferred at <= 17% from task timings rather than
# measured. Batch node only; `_finish` stops it.
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,utilization.gpu,utilization.memory,memory.used \
               --format=csv,noheader -l 10 > "${WORKDIR}/gpusample.csv" 2>/dev/null &
    _NVSMI_PID=$!
    echo "GPU sampling:      ${WORKDIR}/gpusample.csv (pid ${_NVSMI_PID})"
fi

# ── Arm C's other half: the control sidecar ───────────────────────────────────
# `serve --model C` registers the inbox halves and then waits to be steered. Nothing in this
# job steered it, so arm C would have served a campaign, waited `--caller-timeout`, and
# stopped on the planner's `on_timeout="stop"` - the designed refusal, correctly reported, and
# not a run. This is the caller.
#
# It is STARTED BEFORE Dragon and polls, because the URL does not exist until `serve` is up:
# the port is ephemeral (deliberately - see the serve branch above), so the sidecar discovers
# the plane by reading the 0600 file `serve` writes rather than by being told a number.
# The file's PARENT DIRECTORY is the campaign id, by construction: `serve` writes
# `<spec.root>/<spec.campaign_id>/control_plane.url` and the plane registers under that same
# `spec.campaign_id`, so deriving the id from the path cannot disagree with the server. Parsing
# the YAML here could.
#
# --model B, not --model C. The caller IS the reasoner; `--model C` on this side would build
# the inbox halves a second time and stop after one `--caller-timeout` with nobody steering the
# steerer. B is the same Beam-backed oracle arm B runs in-process, so B and C differ in exactly
# one thing - whether the reasoner sits in the executor's process or drives it over the plane -
# which is the only contrast arm C can honestly claim.
if [ "${_SIDECAR:-}" = "yes" ]; then
    _SIDECAR_MODEL="${IMPRESS_A_SIDECAR_MODEL:-B}"
    _SIDECAR_WAIT="${IMPRESS_A_SIDECAR_WAIT_S:-1800}"
    (
        _url_file=""
        for _ in $(seq 1 "${_SIDECAR_WAIT}"); do
            _url_file="$(find "${WORKDIR}" -maxdepth 2 -name control_plane.url -print -quit \
                         2>/dev/null)"
            [ -n "${_url_file}" ] && break
            sleep 1
        done
        if [ -z "${_url_file}" ]; then
            echo "ERROR: sidecar saw no control_plane.url under ${WORKDIR} in ${_SIDECAR_WAIT}s."
            echo "       Arm C is unsteered; the served campaign will stop on caller timeout."
            exit 1
        fi
        _cid="$(basename "$(dirname "${_url_file}")")"
        _url="$(cat "${_url_file}")"
        echo "Sidecar:           control --connect ${_url} --campaign ${_cid}" \
             "--model ${_SIDECAR_MODEL}"
        impress-a control --connect "${_url}" --campaign "${_cid}" \
                  --model "${_SIDECAR_MODEL}" "${PROFILE_ARGS[@]}"
    ) &
    _SIDECAR_PID=$!
    echo "Control sidecar:   pid ${_SIDECAR_PID} (model ${_SIDECAR_MODEL}, waiting for the url)"
fi

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
