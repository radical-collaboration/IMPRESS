#!/usr/bin/env bash
# Step 1 of the four-arm experiment: execute each Task of a campaign's chain once, on real
# hardware, and check it. Nothing else in the experiment may start until this exits 0.
#
#   sbatch --partition=gpuA40x4-interactive --time=00:40:00 \
#          scripts/delta_validate_tasks.sh campaigns/delta-small-molecule-arms-smoke.yaml
#
# WHY THIS EXISTS. `impress-a trust --assert` grants a pattern trust without the three clean
# runs the interlock would otherwise require, on the grounds that the Tasks are proven in
# `examples/small_molecule_binding`. That argument is only honest if they are proven on THIS
# hardware, in THIS venv, through THESE adapters - otherwise it asserts trust in code nobody
# has run. This job's id is what the assertion's `--reason` cites, so the chain of reasoning
# from "trusted" back to "observed" is a thing a reader can follow.
#
# WHY IT IS A WRAPPER AND NOT A LAUNCHER. Everything that makes a Delta job work here - the
# Cray PE module-name case change, the FAB_LIB autodetect, `dragon-config -c` before `add`,
# the `-w ssh` / `-t tcp` / `--network-config` combination, SLURM_OVERLAP, the per-job
# directory, the manifest, the EXIT trap that rescues slurm.out - was bought one burned
# allocation at a time and lives in `delta_gpu_run.sh`. A second copy would be a second thing
# to keep in step, and the one that is run less often is the one that rots. So this sets the
# command and execs that script.
#
# The RESOURCE shape, which must be here and cannot be inherited. Slurm parses `#SBATCH` lines
# out of the file it is handed, at submit time; this script `exec`s `delta_gpu_run.sh` at RUN
# time, long after that parse, so none of that file's ten directives apply to a job submitted
# through this one. Without these, the documented command line above fails at submit with
#
#   sbatch: error: Jobs requesting no GPU resources must be submitted under CPU type accounts
#
# which names the account and not the missing request. Found by running the documented command;
# it had never been submitted.
#
# Same sizing as `delta_gpu_run.sh`, and for the same reason: 4 GPUs already reserves and bills
# the whole node, so 64 cores and 240G are free at that price, and a validation pass that ran
# on a narrower shape than the arms would not be validating the arms' hardware. `--output` is
# load-bearing - the EXIT trap looks for `impress_a_<jobid>.out` by that exact name to move it
# in beside the manifest.
#SBATCH --nodes=1
#SBATCH --tasks-per-node=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=4
#SBATCH --mem=240G
#SBATCH --output=impress_a_%j.out
#
# Deliberately NOT set here: --time, --partition. A validation pass is one width-1 chain, so it
# wants a short interactive allocation rather than the campaign defaults - pass them to sbatch,
# as the example above does, where they are visible in the submission.
set -euo pipefail

# NOT `dirname "${BASH_SOURCE[0]}"` alone. Under sbatch this file is a COPY at
# `/var/spool/slurmd/job<ID>/slurm_script`, so its own path points at the node's spool
# directory and the `exec` below died with
#
#   /var/spool/slurmd/job23669777/slurm_script: line 58:
#   /var/spool/slurmd/job23669777/delta_gpu_run.sh: No such file or directory
#
# seven seconds in, exit 127 - on the only way this script is ever meant to be used. The
# submission directory is where the repo actually is.
#
# $SLURM_SUBMIT_DIR FIRST, AND $IMPRESS_A_DIR REFUSED WHEN IT DISAGREES. The order used to be
# the other way round, and job 23680592 is what that cost: this session's environment carried
# a stale `IMPRESS_A_DIR=/work/hdd/bdyk/hooten1/impress_a`, `sbatch --export=ALL` handed it to
# the job, and this loop exec'd THAT checkout's `delta_gpu_run.sh` - a copy predating the
# `validate-tasks` branch, so it ignored the `IMPRESS_A_COMMAND` exported below, fell back to
# its own `run`/`MODEL=D` defaults, and spent 19m49s on four A40s running an arm-D campaign
# nobody asked for, from `/work/hdd/.../delta_run_campaign.py`.
#
# That is C11 happening again rather than being remembered, and the guard added for it could
# not help: `delta_gpu_run.sh` refuses when an inherited $IMPRESS_A_DIR disagrees with the
# submission directory, but the guard lives in the copy this loop declined to run. A check
# that only exists in the file you failed to reach is not a check. So the precedence is
# reversed here, and a disagreement is fatal at this hop instead of being resolved silently
# in favour of the variable C11 says not to trust.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "${HERE}/delta_gpu_run.sh" ]; then
    for _candidate in "${SLURM_SUBMIT_DIR:-}" "${IMPRESS_A_DIR:-}"; do
        if [ -n "${_candidate}" ] && [ -f "${_candidate}/scripts/delta_gpu_run.sh" ]; then
            HERE="${_candidate}/scripts"
            break
        fi
    done
fi
if [ -n "${SLURM_SUBMIT_DIR:-}" ] && [ -n "${IMPRESS_A_DIR:-}" ] \
   && [ -f "${SLURM_SUBMIT_DIR}/scripts/delta_gpu_run.sh" ] \
   && [ "$(cd "${IMPRESS_A_DIR}" 2>/dev/null && pwd)" \
        != "$(cd "${SLURM_SUBMIT_DIR}" && pwd)" ]; then
    echo "ERROR: \$IMPRESS_A_DIR names a different checkout than the one this job was"
    echo "       submitted from, and a job that runs code from neither of the two is how"
    echo "       job 23680592 ran a campaign where a validation pass was asked for."
    echo "         IMPRESS_A_DIR  ${IMPRESS_A_DIR}"
    echo "         SUBMIT_DIR     ${SLURM_SUBMIT_DIR}"
    echo "       Unset it, or submit from the checkout it names."
    exit 1
fi
if [ ! -f "${HERE}/delta_gpu_run.sh" ]; then
    echo "ERROR: cannot find delta_gpu_run.sh next to this script or under"
    echo "       \$IMPRESS_A_DIR / \$SLURM_SUBMIT_DIR. Submit from the checkout."
    echo "         this script   ${BASH_SOURCE[0]}"
    echo "         IMPRESS_A_DIR ${IMPRESS_A_DIR:-<unset>}"
    echo "         SUBMIT_DIR    ${SLURM_SUBMIT_DIR:-<unset>}"
    exit 1
fi
export IMPRESS_A_COMMAND=validate-tasks

# The exit code is the gate. `delta_gpu_run.sh` propagates the runner's status, and
# `impress-a validate-tasks` exits non-zero when any Task fails an INTEGRITY row - a weak
# design is not a broken Task (decision 0013), so acceptance rows are reported and do not
# fail the job. Read `validation/validate_tasks.txt` beside the manifest either way: a clean
# exit with acceptance rows short of their thresholds is the expected shape of a first pass.
exec "${HERE}/delta_gpu_run.sh" "$@"
