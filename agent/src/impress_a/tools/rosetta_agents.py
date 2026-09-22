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
import tempfile
from pathlib import Path
from typing import Any

from .agent import TaskAgent, TaskRequest
from ._subprocess import first_dep_output, run_cmd

_PACKMIN_WORKER = r"""
import json, sys
import pyrosetta
pyrosetta.init("-mute all")
in_pdb, out_pdb, cycles, result_json = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

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
pyrosetta.init("-mute all")
in_pdb, out_pdb, cycles, result_json = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]

pose = pyrosetta.pose_from_pdb(in_pdb)
sfxn = pyrosetta.get_fa_scorefxn()
relax = pyrosetta.rosetta.protocols.relax.FastRelax(sfxn, cycles)
relax.apply(pose)
pose.dump_pdb(out_pdb)
scores = pose.scores
json.dump({
    "total_score": sfxn(pose),
    "fa_rep": scores.get("fa_rep", 0.0) if hasattr(scores, "get") else 0.0,
}, open(result_json, "w"))
"""

_FILTER_SHAPE_WORKER = r"""
import json, sys
import pyrosetta
pyrosetta.init("-mute all")
in_pdb, result_json = sys.argv[1], sys.argv[2]

pose = pyrosetta.pose_from_pdb(in_pdb)
xml = '<SCOREFXNS/><RESIDUE_SELECTORS/><FILTERS><ShapeComplementarity name="sc" jump="1"/></FILTERS>'
objs = pyrosetta.rosetta.protocols.rosetta_scripts.XmlObjects.create_from_string(xml)
sc_filter = objs.get_filter("sc")
value = sc_filter.report_sm(pose)
json.dump({"shape_complementarity": value}, open(result_json, "w"))
"""


async def _run_worker(script: str, args: list[str], timeout_s: float) -> Path:
    script_path = Path(tempfile.mkstemp(suffix=".py")[1])
    script_path.write_text(script)
    result_json = Path(tempfile.mktemp(suffix=".json"))
    await run_cmd([sys.executable, str(script_path), *args, str(result_json)],
                  timeout_s=timeout_s)
    return result_json


class PackMinAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("packmin: no upstream 'structure' output found")
        out_pdb = tempfile.mktemp(suffix=".pdb", prefix="packmin_")
        result_json = await _run_worker(
            _PACKMIN_WORKER, [structure, out_pdb, str(params["cycles"])],
            timeout_s=float(self.spec.resources.walltime_s))
        metrics = json.loads(Path(result_json).read_text())
        return {"result": "structure", "count": 1,
                "outputs": {"structure": out_pdb}, "metrics": metrics}


class FastRelaxAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("fastrelax: no upstream 'structure' output found")
        out_pdb = tempfile.mktemp(suffix=".pdb", prefix="fastrelax_")
        result_json = await _run_worker(
            _FASTRELAX_WORKER, [structure, out_pdb, str(params["relax_cycles"])],
            timeout_s=float(self.spec.resources.walltime_s))
        metrics = json.loads(Path(result_json).read_text())
        return {"result": "structure", "count": params["nstruct"],
                "outputs": {"structure": out_pdb}, "metrics": metrics}


class FilterShapeAgent(TaskAgent):
    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        structure = first_dep_output(req.inputs, "structure")
        if not structure:
            raise RuntimeError("filter_shape: no upstream 'structure' output found")
        result_json = await _run_worker(
            _FILTER_SHAPE_WORKER, [structure],
            timeout_s=float(self.spec.resources.walltime_s))
        metrics = json.loads(Path(result_json).read_text())
        return {"result": "structure", "count": 1,
                "outputs": {"structure": structure}, "metrics": metrics}
