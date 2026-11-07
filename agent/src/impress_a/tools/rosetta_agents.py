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

from ._subprocess import input_path, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

_PACKMIN_WORKER = r"""
# Phase timings to stderr, flushed. `-mute all` below silences every Rosetta tracer, so
# without these a stage that stalls reports nothing at all about where its time went -
# which is how job 22675512's packmin burned a 300s timeout leaving an empty work dir and
# no way to tell import from work. run_cmd now drains the pipes on a timeout kill, so
# these survive even when the worker never reaches its own output.
import sys, time as _time
_T0 = _LAST = _time.monotonic()
def phase(name):
    global _LAST
    now = _time.monotonic()
    sys.stderr.write("[phase] %-18s %7.1fs  (total %7.1fs)\n" % (name, now - _LAST, now - _T0))
    sys.stderr.flush()
    _LAST = now

import json
import pyrosetta
phase("import pyrosetta")

# A seed makes a replica lineage an independent, REPRODUCIBLE draw; without one,
# replicas of a deterministic protocol are just the same run repeated N times.
def _init(seed_arg, ligand_params_arg):
    flags = "-mute all"
    if seed_arg != "none":
        flags += " -run:constant_seed -run:jran %d" % (int(seed_arg) % 2147483647)
    if ligand_params_arg != "none":
        flags += (" -extra_res_fa %s -ignore_unrecognized_res"
                  " -ignore_zero_occupancy" % ligand_params_arg)
    pyrosetta.init(flags)

in_pdb, out_pdb, cycles, seed, ligand_params, result_json = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6])
_init(seed, ligand_params)
phase("pyrosetta.init")

pose = pyrosetta.pose_from_pdb(in_pdb)
phase("pose_from_pdb")
sfxn = pyrosetta.get_fa_scorefxn()
phase("get_fa_scorefxn")
task_factory = pyrosetta.rosetta.core.pack.task.TaskFactory()
task_factory.push_back(pyrosetta.rosetta.core.pack.task.operation.RestrictToRepacking())
pack_mover = pyrosetta.rosetta.protocols.minimization_packing.PackRotamersMover(sfxn)
pack_mover.task_factory(task_factory)
min_mover = pyrosetta.rosetta.protocols.minimization_packing.MinMover()
for _ in range(cycles):
    pack_mover.apply(pose)
    min_mover.apply(pose)
phase("pack+min x%d" % cycles)
pose.dump_pdb(out_pdb)
json.dump({"total_score": sfxn(pose)}, open(result_json, "w"))
"""

_FASTRELAX_WORKER = r"""
# Phase timings to stderr, flushed. `-mute all` below silences every Rosetta tracer, so
# without these a stage that stalls reports nothing at all about where its time went -
# which is how job 22675512's packmin burned a 300s timeout leaving an empty work dir and
# no way to tell import from work. run_cmd now drains the pipes on a timeout kill, so
# these survive even when the worker never reaches its own output.
import sys, time as _time
_T0 = _LAST = _time.monotonic()
def phase(name):
    global _LAST
    now = _time.monotonic()
    sys.stderr.write("[phase] %-18s %7.1fs  (total %7.1fs)\n" % (name, now - _LAST, now - _T0))
    sys.stderr.flush()
    _LAST = now

import json
import pyrosetta
phase("import pyrosetta")

# A seed makes a replica lineage an independent, REPRODUCIBLE draw; without one,
# replicas of a deterministic protocol are just the same run repeated N times.
def _init(seed_arg, ligand_params_arg):
    flags = "-mute all"
    if seed_arg != "none":
        flags += " -run:constant_seed -run:jran %d" % (int(seed_arg) % 2147483647)
    if ligand_params_arg != "none":
        flags += (" -extra_res_fa %s -ignore_unrecognized_res"
                  " -ignore_zero_occupancy" % ligand_params_arg)
    pyrosetta.init(flags)

in_pdb, out_pdb, cycles, nstruct, seed, ligand_params, result_json = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6],
    sys.argv[7])
_init(seed, ligand_params)
phase("pyrosetta.init")

start = pyrosetta.pose_from_pdb(in_pdb)
phase("pose_from_pdb")
sfxn = pyrosetta.get_fa_scorefxn()
relax = pyrosetta.rosetta.protocols.relax.FastRelax(sfxn, cycles)
phase("build FastRelax")

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
    phase("relax trajectory")

best.dump_pdb(out_pdb)
scores = best.scores
metrics = {"total_score": best_score}

# OMITTED, not defaulted. `scores.get("fa_rep", 0.0)` reported a fabricated zero for a term
# Rosetta had not computed - and 0.0 is a PASSING fa_rep, so a broken score function read as
# a perfectly packed structure. An adapter omits what it could not read; `metrics_reported`
# is what turns that into an integrity failure.
try:
    metrics["fa_rep"] = float(scores["fa_rep"])
except Exception as exc:
    sys.stderr.write("fa_rep unavailable: %r\n" % (exc,))

# Interaction energy between the ligand and everything else - the one number this stage
# reports that measures BINDING rather than geometry, and it was never computed at all
# (backlog G4). A converged, well-packed pose that does not bind was indistinguishable from
# a real binder by anything the campaign measured.
#
# SELECTOR-BASED, so it is correct whatever the chain layout is. Upstream's own
# `scripts/fastrelax.py` uses exactly this pair - ResiduePropertySelector(LIGAND) against
# its complement - and that is the port: a `Chain chains="A"/"B"` split would only be right
# if the ligand were its own chain, which is a property of the input rather than of the tool.
try:
    from pyrosetta.rosetta.core.simple_metrics.metrics import InteractionEnergyMetric
    from pyrosetta.rosetta.core.select.residue_selector import (
        NotResidueSelector, ResiduePropertySelector)
    from pyrosetta.rosetta.core.chemical import ResidueProperty

    ligand_sel = ResiduePropertySelector(ResidueProperty.LIGAND)
    if not any(ligand_sel.apply(best)):
        # No ligand residue: there is no interface to measure, and a number computed against
        # an empty selection would be a confident zero. Omitted, loudly.
        raise RuntimeError("no LIGAND-property residue in the pose")
    metric = InteractionEnergyMetric()
    metric.set_scorefunction(sfxn)
    metric.set_residue_selectors(ligand_sel, NotResidueSelector(ligand_sel))
    metric.apply(best)            # also records it in the pose's energies, as upstream does
    metrics["interaction_energy"] = float(metric.calculate(best))
except Exception as exc:
    sys.stderr.write("interaction_energy unavailable: %r\n" % (exc,))
phase("interaction_energy")

json.dump(metrics, open(result_json, "w"))
"""

_FILTER_SHAPE_WORKER = r"""
# Phase timings to stderr, flushed. `-mute all` below silences every Rosetta tracer, so
# without these a stage that stalls reports nothing at all about where its time went -
# which is how job 22675512's packmin burned a 300s timeout leaving an empty work dir and
# no way to tell import from work. run_cmd now drains the pipes on a timeout kill, so
# these survive even when the worker never reaches its own output.
import sys, time as _time
_T0 = _LAST = _time.monotonic()
def phase(name):
    global _LAST
    now = _time.monotonic()
    sys.stderr.write("[phase] %-18s %7.1fs  (total %7.1fs)\n" % (name, now - _LAST, now - _T0))
    sys.stderr.flush()
    _LAST = now

import json
import pyrosetta
phase("import pyrosetta")
in_pdb, ligand_params, result_json = sys.argv[1], sys.argv[2], sys.argv[3]
flags = "-mute all"
if ligand_params != "none":
    flags += " -extra_res_fa %s -ignore_unrecognized_res -ignore_zero_occupancy" % ligand_params
pyrosetta.init(flags)
phase("pyrosetta.init")

pose = pyrosetta.pose_from_pdb(in_pdb)
phase("pose_from_pdb")

# WHICH INTERFACE IS MEASURED (backlog G5). This was `jump="1"` with the default
# scorefunction, and `jump="1"` assumes a particular chain and jump arrangement in the
# relaxed pose: if the ligand is not across jump 1 the number is not wrong in an obvious way,
# it is a shape complementarity between two parts of the protein. Upstream splits by chain
# instead (`Chain chains="A"` against `Chain chains="B"`), which is right only when the ligand
# is its own chain - a property of the input, not of the tool.
#
# So: the ligand RESIDUE PROPERTY against its complement, which is the same pair the
# interaction_energy port uses and is correct whatever the chain layout is.
#
# `quick="0"` is explicit because the default is Rosetta's, not ours, and quick mode is a
# faster and less accurate SC - upstream sets it too. `beta_nov16` is declared to match
# upstream's protocol, and the comment is the honest part: ShapeComplementarity is GEOMETRIC
# and takes no scorefunction, so this does not change the number. It is here so that a filter
# added later inherits the same energy model rather than Rosetta's default.
xml = (
    '<SCOREFXNS><ScoreFunction name="sfxn_clean" weights="beta_nov16"/></SCOREFXNS>'
    '<RESIDUE_SELECTORS>'
    '<ResidueProperty name="ligand" properties="LIGAND"/>'
    '<Not name="not_ligand" selector="ligand"/>'
    '</RESIDUE_SELECTORS>'
    '<FILTERS><ShapeComplementarity name="sc" quick="0" verbose="0"'
    ' residue_selector1="ligand" residue_selector2="not_ligand"/></FILTERS>')
try:
    objs = pyrosetta.rosetta.protocols.rosetta_scripts.XmlObjects.create_from_string(xml)
    sc_filter = objs.get_filter("sc")
except Exception as exc:
    # Loudly, never by falling back to a chain split: a fallback would keep producing numbers
    # while measuring a different interface, and nothing downstream could tell. The remedy is
    # named because this XML is the one part of the port that no local test can exercise.
    sys.stderr.write("selector-based ShapeComplementarity could not be built: %r\n" % (exc,))
    raise RuntimeError(
        "filter_shape: the selector-based ShapeComplementarity filter failed to build. "
        "Check the RosettaScripts selector names against this PyRosetta build "
        "(ResidueProperty, Not) - see backlog G5. Refusing rather than falling back to "
        "jump=1 or a chain split, which would measure a different interface silently.")

# An empty ligand selection means there is nothing to measure against. SC of a selection
# against everything-but-nothing is a confident number about the wrong question.
ligand_sel = objs.get_residue_selector("ligand")
if not any(ligand_sel.apply(pose)):
    raise RuntimeError(
        "filter_shape: no LIGAND-property residue in the pose, so there is no "
        "protein-ligand interface to measure. Check that -extra_res_fa was passed with the "
        "ligand .params; without it the ligand is dropped by -ignore_unrecognized_res.")

value = sc_filter.report_sm(pose)
phase("ShapeComplementarity")
json.dump({
    "shape_complementarity": value,
    # Which interface produced the number, as a metric rather than a log line, so one real
    # run settles G5 from provenance. 1.0 = the ligand-property selector pair above. A future
    # change that reverts to a jump or chain split must report a different value here, or the
    # harness cannot tell two campaigns' numbers apart.
    "sc_selector_mode": 1.0,
}, open(result_json, "w"))
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
        structure = input_path(req, "structure")
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
        structure = input_path(req, "structure")
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
        structure = input_path(req, "structure")
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
