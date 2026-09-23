"""PyRosetta task agents - packmin, fastrelax, filter_shape.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`packmin()`, `fastrelax()` and `filter_shape()` steps. Each agent writes a tiny standalone
worker script and runs it with `sys.executable` as a fresh subprocess - PyRosetta's
`pyrosetta.init()` is process-global, so P2 fan-out needs one interpreter per call, not a
shared one. `import pyrosetta` therefore never happens in THIS process, only inside the
worker subprocess, so `Registry.load()`/`dry_run()` work without PyRosetta installed here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ._subprocess import first_dep_output, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

_PACKMIN_WORKER = r"""
import json, sys
import pyrosetta

# A seed makes a replica lineage an independent, REPRODUCIBLE draw; without one,
# replicas of a deterministic protocol are just the same run repeated N times.
def _init(seed_arg, ligand_params_arg):
    flags = "-mute all"
    if seed_arg != "none":
        flags += " -run:constant_seed -run:jran %d" % (int(seed_arg) % 2147483647)
    if ligand_params_arg != "none":
        flags += " -extra_res_fa %s -ignore_unrecognized_res -ignore_zero_occupancy" % ligand_params_arg
    pyrosetta.init(flags)

in_pdb, out_pdb, cycles, seed, ligand_params, result_json = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6])
_init(seed, ligand_params)

pose = pyrosetta.pose_from_pdb(in_pdb)
sfxn = pyrosetta.get_fa_scorefxn()
task_factory = pyrosetta.rosetta.core.pack.task.TaskFactory()
task_factory.push_back(pyrosetta.rosetta.core.pack.task.operation.RestrictToRepacking())
pack_mover = pyrosetta.rosetta.protocols.minimization_packing.PackRotamersMover(sfxn)
pack_mover.task_factory(task_factory)
min_mover = pyrosetta.rosetta.protocols.minimization_packing.MinMover()
for _ in range(cycles):
    pack_mover.apply(pose)
    min_mover.apply(pose)
pose.dump_pdb(out_pdb)
json.dump({"total_score": sfxn(pose)}, open(result_json, "w"))
"""

_FASTRELAX_WORKER = r"""
import json, sys
import pyrosetta

# A seed makes a replica lineage an independent, REPRODUCIBLE draw; without one,
# replicas of a deterministic protocol are just the same run repeated N times.
def _init(seed_arg, ligand_params_arg):
    flags = "-mute all"
    if seed_arg != "none":
        flags += " -run:constant_seed -run:jran %d" % (int(seed_arg) % 2147483647)
    if ligand_params_arg != "none":
        flags += " -extra_res_fa %s -ignore_unrecognized_res -ignore_zero_occupancy" % ligand_params_arg
    pyrosetta.init(flags)

in_pdb, out_pdb, cycles, nstruct, seed, ligand_params, result_json = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6],
    sys.argv[7])
_init(seed, ligand_params)

start = pyrosetta.pose_from_pdb(in_pdb)
sfxn = pyrosetta.get_fa_scorefxn()
relax = pyrosetta.rosetta.protocols.relax.FastRelax(sfxn, cycles)

# `nstruct` independent trajectories from the same start, keeping the best. It used to
# be accepted, range-checked and budgeted, and then never passed here at all - while the
# agent reported `count: nstruct` for the single structure it actually produced.
best, best_score = None, None
for _ in range(max(1, nstruct)):
    pose = start.clone()
    relax.apply(pose)
    score = sfxn(pose)
    if best_score is None or score < best_score:
        best, best_score = pose, score

best.dump_pdb(out_pdb)
scores = best.scores
json.dump({
    "total_score": best_score,
    "fa_rep": scores.get("fa_rep", 0.0) if hasattr(scores, "get") else 0.0,
}, open(result_json, "w"))
"""

_FILTER_SHAPE_WORKER = r"""
import json, sys
import pyrosetta
in_pdb, ligand_params, result_json = sys.argv[1], sys.argv[2], sys.argv[3]
flags = "-mute all"
if ligand_params != "none":
    flags += " -extra_res_fa %s -ignore_unrecognized_res -ignore_zero_occupancy" % ligand_params
pyrosetta.init(flags)

pose = pyrosetta.pose_from_pdb(in_pdb)
xml = '<SCOREFXNS/><RESIDUE_SELECTORS/><FILTERS><ShapeComplementarity name="sc" jump="1"/></FILTERS>'
objs = pyrosetta.rosetta.protocols.rosetta_scripts.XmlObjects.create_from_string(xml)
sc_filter = objs.get_filter("sc")
value = sc_filter.report_sm(pose)
json.dump({"shape_complementarity": value}, open(result_json, "w"))
"""


async def _run_worker(script: str, args: list[str], timeout_s: float,
                      work: Path) -> Path:
    """Run a PyRosetta worker in its own interpreter, inside the task's work directory.

    Was `mkstemp(...)[1]`, which discarded the open descriptor and leaked one per call,
    plus `mktemp` for the outputs - the deprecated, racy variant. Both are unnecessary
    once the task has a directory of its own.
    """
    script_path = work / "worker.py"
    script_path.write_text(script)
    result_json = work / "result.json"
    await run_cmd([sys.executable, str(script_path), *args, str(result_json)],
                  timeout_s=timeout_s)
    return result_json


def _read_metrics(result_json: Path) -> dict[str, Any] | None:
    """The worker's metrics, or None if it produced nothing usable.

    A worker can exit 0 and still leave no readable JSON - PyRosetta dying after its own
    cleanup, or a truncated write. Reading unconditionally turned that into a
    FileNotFoundError escaping `run()`, which the campaign records as an infrastructure
    crash. It is a QC failure: the tool ran and did not produce a result.
    """
    try:
        return json.loads(result_json.read_text())
    except (OSError, ValueError):
        return None


_NO_RESULT = {"result": None, "count": 0, "outputs": {}, "metrics": {}}


def _seed_arg(params: dict[str, Any]) -> str:
    return "none" if params.get("seed") is None else str(params["seed"])


def _ligand_params_arg(params: dict[str, Any]) -> str:
    return params.get("ligand_params_path") or "none"


class PackMinAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("packmin: no upstream 'structure' output found")
        work = workdir_for(req, "packmin")
        out_pdb = work / "packmin.pdb"
        result_json = await _run_worker(
            _PACKMIN_WORKER,
            [structure, str(out_pdb), str(params["cycles"]), _seed_arg(params),
             _ligand_params_arg(params)],
            timeout_s=float(self.spec.resources.walltime_s), work=work)
        metrics = _read_metrics(result_json)
        if metrics is None:
            return dict(_NO_RESULT)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": out_pdb}, "metrics": metrics}


class FastRelaxAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("fastrelax: no upstream 'structure' output found")
        work = workdir_for(req, "fastrelax")
        out_pdb = work / "fastrelax.pdb"
        result_json = await _run_worker(
            _FASTRELAX_WORKER,
            [structure, str(out_pdb), str(params["relax_cycles"]),
             str(params["nstruct"]), _seed_arg(params), _ligand_params_arg(params)],
            timeout_s=float(self.spec.resources.walltime_s), work=work)
        metrics = _read_metrics(result_json)
        if metrics is None:
            return dict(_NO_RESULT)
        # One structure is written - the best of `nstruct` trajectories - so that is
        # what `count` reports.
        return {"result": "structure", "count": 1,
                "outputs": {"structure": out_pdb}, "metrics": metrics}


class FilterShapeAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("filter_shape: no upstream 'structure' output found")
        work = workdir_for(req, "filter_shape")
        result_json = await _run_worker(
            _FILTER_SHAPE_WORKER, [structure, _ligand_params_arg(params)],
            timeout_s=float(self.spec.resources.walltime_s), work=work)
        metrics = _read_metrics(result_json)
        if metrics is None:
            return dict(_NO_RESULT)
        return {"result": "structure", "count": 1,
                "outputs": {"structure": Path(structure)}, "metrics": metrics}
