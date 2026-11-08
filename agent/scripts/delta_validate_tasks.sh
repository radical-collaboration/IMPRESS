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

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPRESS_A_COMMAND=validate-tasks

# The exit code is the gate. `delta_gpu_run.sh` propagates the runner's status, and
# `impress-a validate-tasks` exits non-zero when any Task fails an INTEGRITY row - a weak
# design is not a broken Task (decision 0013), so acceptance rows are reported and do not
# fail the job. Read `validation/validate_tasks.txt` beside the manifest either way: a clean
# exit with acceptance rows short of their thresholds is the expected shape of a first pass.
exec "${HERE}/delta_gpu_run.sh" "$@"
