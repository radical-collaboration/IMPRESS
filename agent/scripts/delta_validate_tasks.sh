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
# Deliberately NOT set here: --nodes, --time, --partition. A validation pass is one width-1
# chain, so it wants a short interactive allocation rather than the campaign defaults - pass
# them to sbatch, as the example above does, where they are visible in the submission.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export IMPRESS_A_COMMAND=validate-tasks

# The exit code is the gate. `delta_gpu_run.sh` propagates the runner's status, and
# `impress-a validate-tasks` exits non-zero when any Task fails an INTEGRITY row - a weak
# design is not a broken Task (decision 0013), so acceptance rows are reported and do not
# fail the job. Read `validation/validate_tasks.txt` beside the manifest either way: a clean
# exit with acceptance rows short of their thresholds is the expected shape of a first pass.
exec "${HERE}/delta_gpu_run.sh" "$@"
