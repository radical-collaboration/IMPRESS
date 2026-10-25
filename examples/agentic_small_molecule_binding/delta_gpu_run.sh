#!/bin/bash
#
# Agentic Small Molecule Binding — SLURM batch script (Delta HPC / GPU)
#
# Same allocation, same toolkit and same task placement as the reference
# examples/small_molecule_binding launcher this is derived from; the difference
# is that an LLM chooses what runs, through an OpenAI-compatible endpoint.
#
# Additional settings:
#   export IMPRESS_MODEL_PROFILE=claude-opus   # a profile in models.yaml
#   export ANTHROPIC_API_KEY=...               # whatever that profile needs
#   export IMPRESS_MAX_LLM_TURNS=200
#
# The key must also be visible to the runner. On a multi-node run `dragon -w
# ssh` forwards only its own allowlist, so export the key from ~/.bashrc the
# way MPNN_DIR and friends already are.
#
# Set before calling sbatch:
#   export SBATCH_ACCOUNT=<project>-delta-gpu
#   export WORK_DIR=/work/nvme/<project>/$USER
#
# Optional overrides (default under $WORK_DIR):
#   export MPNN_DIR=/path/to/LigandMPNN
#   export BOLTZ_CACHE=/path/to/boltz_cache
#
# Foundry container (RFD3):
#   Stored as a .tar.gz under WORK_DIR (built by pull_foundry.sh).
#   Extracted to /tmp at job start and removed on exit.
#   Override FOUNDRY_TAR to point to a different archive, or set
#   FOUNDRY_SIF_PATH directly to skip extraction entirely.
#
# Example:
#   sbatch delta_gpu_run.sh
#   IMPRESS_MODEL_PROFILE=scripted sbatch delta_gpu_run.sh   # no LLM, no key
#
# Account: set SBATCH_ACCOUNT=<project>-delta-gpu before calling sbatch
##SBATCH --account=<project>-delta-gpu
#SBATCH --partition=gpuA40x4
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=240G
#SBATCH --time=12:00:00
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
#   time=12:00:00 — NOT the 48h partition maximum, deliberately.  Sized as
#     ~6.8h expected compute (measured on job 22491438; unchanged by allocation
#     width, since each pipeline independently accumulates its own max_tasks
#     entries) + ~1h teardown + slack down to ~62% of baseline throughput.
#     The wall limit is the ONLY backstop against a hung Dragon teardown: on
#     22491438 `flow.shutdown()` never returned after all 16 pipelines finished,
#     the job sat 60 minutes and had to be scancelled, burning ~64 GPU-h (37% of
#     its billed total) for zero output.  At 8 nodes that is 32 GPU-h per hung
#     hour, so a 48h request would let an unattended hang bill ~1536 GPU-h
#     versus 384 at 12h.  `sbatch --test-only` returns an identical queue start
#     estimate for 8/12/16/24/48h, so shortening costs nothing in scheduling,
#     and billing is on elapsed rather than requested time either way.
#     Do not go below 12h: there is no checkpoint or resume, so a TIMEOUT loses
#     all in-memory ensemble state (the failure the scale-up was done to fix),
#     and 8h would leave only a 1.18x margin over expected compute.
# Override nodes per run without editing this file:  sbatch --nodes=2 ...
#SBATCH --job-name=impress_sm_binding
##SBATCH --mail-user=you@example.edu
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

if [ -z "${WORK_DIR:-}" ]; then
    echo "ERROR: WORK_DIR is not set."
    echo "       export WORK_DIR=/work/nvme/<project>/\$USER && sbatch delta_gpu_run.sh"
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
IMPRESS_VENV="${IMPRESS_VENV:-${WORK_DIR}/ve/small_mol}"
# Keep this unset so srun's default --export=ALL carries this environment to any
# srun steps.  Note the multi-node path below (`dragon -w ssh`) does NOT use
# srun: tasks on remote nodes see only Dragon's BASE_ENV_VARNAMES plus whatever
# the ssh login shell's ~/.bashrc exports -- which is where WORK_DIR, MPNN_DIR,
# BOLTZ_CACHE and FOUNDRY_SIF_PATH must come from for rfd3.sh/boltz.sh there.
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

# Boltz-2 model weights cache.  Pre-warm once on a login node via
# delta_env_setup.sh's Step 13 (boltz has no dedicated "download weights"
# subcommand; weights auto-download on first `boltz predict` call).
export BOLTZ_CACHE="${BOLTZ_CACHE:-${WORK_DIR}/.cache/boltz}"
mkdir -p "${BOLTZ_CACHE}"

# ── Foundry sandbox: extract to /tmp at job start, clean up on exit ───────────
# Extracting to /tmp avoids the scratch quota. Compute nodes have ample /tmp
# space that is not quota-counted.  If FOUNDRY_SIF_PATH is already set (e.g.
# a pre-built .sif or a persistent sandbox on a large allocation), extraction
# is skipped entirely.
if [ -z "${FOUNDRY_SIF_PATH:-}" ] && [ -f "${WORK_DIR}/foundry.sif" ]; then
    export FOUNDRY_SIF_PATH="${WORK_DIR}/foundry.sif"
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
        echo "       Put the .sif on shared storage: ${WORK_DIR}/foundry.sif"
        echo "       (or set FOUNDRY_SIF_PATH to a shared path)"
        exit 1
    fi
    FOUNDRY_TAR="${FOUNDRY_TAR:-${WORK_DIR}/foundry_sandbox.tar.gz}"
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
WORKDIR="${IMPRESS_SCRIPTS_DIR:-${WORK_DIR}/IMPRESS/examples/agentic_small_molecule_binding}"
# Inputs and tool scripts are the reference example's, unmodified -- that is
# what makes the two runs comparable. Only the decision-making lives here.
REF_DIR="$(cd "${WORKDIR}/../small_molecule_binding" && pwd)"
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
# actually exist in the reference example; to go higher:
#   cp -r ../small_molecule_binding/p1_in ../small_molecule_binding/p9_in
_n_inputs=$(ls -d "${REF_DIR}"/p[0-9]*_in 2>/dev/null | wc -l)
IMPRESS_N_PIPELINES="${IMPRESS_N_PIPELINES:-$(( ${SLURM_NNODES:-1} * 4 ))}"
if [ "${_n_inputs}" -gt 0 ] && [ "${IMPRESS_N_PIPELINES}" -gt "${_n_inputs}" ]; then
    echo "NOTE: capping pipelines at ${_n_inputs} (only p{i}_in dirs that exist)"
    IMPRESS_N_PIPELINES="${_n_inputs}"
fi
export IMPRESS_N_PIPELINES
echo "N_PIPELINES:       ${IMPRESS_N_PIPELINES}"

# ── Model profile and endpoint reachability ───────────────────────────────────
# Fail here, on the batch node, in seconds -- not an hour into the run on a
# compute node. A compute node that cannot reach the endpoint turns the whole
# allocation into the scripted fallback route, which is not the experiment.
export IMPRESS_MODEL_PROFILE="${IMPRESS_MODEL_PROFILE:-scripted}"
export IMPRESS_MAX_LLM_TURNS="${IMPRESS_MAX_LLM_TURNS:-200}"
echo "MODEL_PROFILE:     ${IMPRESS_MODEL_PROFILE}"
echo "MAX_LLM_TURNS:     ${IMPRESS_MAX_LLM_TURNS}"

# A dragon_vllm profile has nothing to reach yet -- the server is started by
# the runner, inside this allocation, and the runner's own wait_healthy() is
# the gate. Probing here would always fail.
_PROFILE_KIND=$(python3 - "${WORKDIR}/models.yaml" "${IMPRESS_MODEL_PROFILE}" <<'PYKIND' 2>/dev/null || echo unknown
import sys, yaml
cfg = (yaml.safe_load(open(sys.argv[1])) or {}).get("profiles", {}).get(sys.argv[2]) or {}
print(cfg.get("kind", "openai_compat"))
PYKIND
)
echo "PROFILE_KIND:      ${_PROFILE_KIND}"

if [ "${_PROFILE_KIND}" = "dragon_vllm" ]; then
    # Weights come from the shared cache; never download from a compute node
    # with four pipelines racing. Pre-stage on a login node.
    # Set, not defaulted. ~/.bashrc exports HF_HOME to a path that does not
    # exist on this system, and with HF_HUB_OFFLINE=1 an inherited wrong value
    # means the server can never find the weights and the job burns its whole
    # allocation waiting for a health check that will never pass. Override
    # deliberately with IMPRESS_HF_HOME if you really mean a different cache.
    export HF_HOME="${IMPRESS_HF_HOME:-${WORK_DIR}/.cache/huggingface}"
    export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
    if [ ! -d "${HF_HOME}/hub" ]; then
        echo "ERROR: no HF cache at ${HF_HOME}/hub. Pre-stage the weights on a"
        echo "       login node first; a compute node with HF_HUB_OFFLINE=1"
        echo "       cannot fetch them."
        exit 1
    fi
    export VLLM_VENV="${VLLM_VENV:-${WORK_DIR}/ve/vllm_srv}"
    echo "HF_HOME:           ${HF_HOME} (offline=${HF_HUB_OFFLINE})"
    echo "VLLM_VENV:         ${VLLM_VENV}"
    if [ ! -x "${VLLM_VENV}/bin/vllm" ]; then
        echo "ERROR: no vllm in ${VLLM_VENV}. Build it first (separate venv:"
        echo "       vLLM's torch must not be installed over ve/small_mol)."
        exit 1
    fi
    if [ "${SLURM_NNODES:-1}" -lt 2 ]; then
        echo "ERROR: ${IMPRESS_MODEL_PROFILE} hosts the model in-allocation and"
        echo "       needs --nodes=2 so it does not share GPUs with the pipelines."
        exit 1
    fi
elif [ "${IMPRESS_MODEL_PROFILE}" != "scripted" ]; then
    _probe=$(python3 - "${WORKDIR}/models.yaml" "${IMPRESS_MODEL_PROFILE}" <<'PYPROBE'
import os, sys, urllib.request, yaml
cfg = (yaml.safe_load(open(sys.argv[1])) or {}).get("profiles", {}).get(sys.argv[2])
if cfg is None:
    print(f"ERROR: no profile {sys.argv[2]!r} in models.yaml"); sys.exit(1)
env = cfg.get("api_key_env")
if env and not os.environ.get(env):
    print(f"ERROR: profile {sys.argv[2]!r} needs {env} exported"); sys.exit(1)
url = (cfg.get("base_url") or "").rstrip("/") + "/models"
try:
    req = urllib.request.Request(url)
    if env:
        req.add_header("Authorization", f"Bearer {os.environ[env]}")
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"OK: {url} -> HTTP {r.status}")
except Exception as exc:
    # A 4xx here still proves the host is reachable, which is the thing a
    # compute node is most likely to lack.
    code = getattr(exc, "code", None)
    if code:
        print(f"OK: {url} -> HTTP {code} (reachable)")
    else:
        print(f"ERROR: cannot reach {url}: {exc!r}"); sys.exit(1)
PYPROBE
    ) || { echo "${_probe}"; echo "Aborting before the allocation is spent."; exit 1; }
    echo "ENDPOINT:          ${_probe}"
fi

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

RUNNER="${1:-run_agentic_smb.py}"

# Run config forwarded as argv (see the comment at the dragon invocations below).
RUNNER_ARGS=( --n-pipelines "${IMPRESS_N_PIPELINES}" --work-dir "${IMPRESS_WORK_DIR}"
              --model-profile "${IMPRESS_MODEL_PROFILE}"
              --max-llm-turns "${IMPRESS_MAX_LLM_TURNS}" )

# The runner records how it ended here; see the check after the run.
RUNNER_STATUS_FILE="${IMPRESS_WORK_DIR}/runner_status"
rm -f "${RUNNER_STATUS_FILE}"

# Per-GPU utilisation and memory every 10 s.  Telemetry has gpu_percent but no
# GPU memory, and memory is what limits packing more tools onto a GPU.  This
# runs on the batch node only, so a multi-node job logs just that node.  It is
# stopped after the run; on an early exit or TIMEOUT Slurm reaps it with the job.
NVSMI_PID=""
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=timestamp,index,utilization.gpu,memory.used,memory.total \
               --format=csv,noheader,nounits -l 10 \
               > "${IMPRESS_WORK_DIR}/nvsmi.csv" 2>&1 &
    NVSMI_PID=$!
    echo "GPU log:           ${IMPRESS_WORK_DIR}/nvsmi.csv (pid ${NVSMI_PID})"
fi

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

# `dragon` exits 0 even when the runner dies with a traceback (job 22692267
# was recorded COMPLETED), so set -e never fires on a failed run.  Take the
# job's exit status from the runner's own record instead.  A missing record
# means the runner died before reaching its __main__ block (e.g. an import
# error), which only run_agentic_smb.py writes, so the other runners are only
# warned about.
[ -n "${NVSMI_PID}" ] && kill "${NVSMI_PID}" 2>/dev/null || true
RUNNER_STATUS="$(cat "${RUNNER_STATUS_FILE}" 2>/dev/null || echo missing)"
echo "=== Agentic Small Molecule Binding pipeline done: $(date) (runner status: ${RUNNER_STATUS}) ==="
if [ "${RUNNER_STATUS}" != "ok" ]; then
    if [ "${RUNNER_STATUS}" != "missing" ] || [ "$(basename "${RUNNER}")" = "run_agentic_smb.py" ]; then
        echo "ERROR: runner did not finish cleanly; exiting 1 so Slurm records FAILED"
        exit 1
    fi
    echo "WARNING: ${RUNNER} wrote no ${RUNNER_STATUS_FILE}; exit status unknown"
fi
