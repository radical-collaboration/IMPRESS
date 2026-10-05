"""LigandMPNN task agent - ligand-context-aware inverse folding + side-chain packing.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`mpnn()` step: `python $MPNN_DIR/run.py --model_type ligand_mpnn ...`, run from the cloned
checkout (`$MPNN_DIR`), not a pip package.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from ._subprocess import first_dep_output, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

# LigandMPNN writes confidence into its FASTA headers, e.g.:
# >design, id=1, overall_confidence=0.6421, ligand_confidence=0.5817
_CONF_RE = re.compile(r"overall_confidence=([\d.]+),\s*ligand_confidence=([\d.]+)")

# Written into the task workdir and run instead of `run.py` itself. Same device as the
# reference pipeline's `scripts/mpnn_run.py`, and the same device as the `_*_WORKER`
# constants in `rosetta_agents.py`: a helper script lives here as a string rather than as
# a package file, so nothing has to be located at runtime.
#
# Why it has to exist: LigandMPNN vendors a copy of openfold written against pre-1.20
# numpy. `np.int` (residue_constants.py, three sites) and `np.object` (data/templates.py,
# two sites) are on the import path `run.py` -> `sc_utils` -> `openfold.data` ->
# `openfold.np`, and numpy removed both in 1.24. This venv carries numpy 2.x because
# Boltz and the rest of the stack require it, so pinning down to LigandMPNN's own 1.23.5
# is not available to us. Job 22669509 spent a queue slot proving the import dies here.
#
# `np.bool` is deliberately NOT forced: numpy 2.x defines it as its own bool scalar, so
# `hasattr` is True, and it is a valid dtype. The only `np.bool` site in the checkout is
# `openfold/np/relax/utils.py`, which is off the import path anyway.
MPNN_SHIM = '''\
"""Run LigandMPNN's run.py under a numpy that still has the aliases it expects.

Usage: python mpnn_run.py <mpnn_dir> [run.py args...]
"""
import os
import runpy
import sys
import warnings

import numpy as np

# numpy 2.x answers `hasattr(np, "object")` through a module __getattr__ that emits a
# FutureWarning before raising. Probing must not put two warning lines at the head of
# every LigandMPNN stderr - that stderr is the diagnostic, and job 22536706 is what it
# cost to lose it once.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    for _alias, _builtin in (("int", int), ("float", float), ("bool", bool),
                             ("complex", complex), ("object", object), ("str", str)):
        if not hasattr(np, _alias):
            setattr(np, _alias, _builtin)

# Fail on our own preconditions by name. Without this, a mis-set $MPNN_DIR surfaces as a
# bare FileNotFoundError three frames inside runpy, which reads like a LigandMPNN bug.
if len(sys.argv) < 2:
    raise SystemExit("mpnn_run.py: expected <mpnn_dir> as argv[1]")
mpnn_dir = sys.argv[1]
if not os.path.isfile(os.path.join(mpnn_dir, "run.py")):
    raise SystemExit(f"mpnn_run.py: no run.py under {mpnn_dir!r} - "
                     "is $MPNN_DIR a LigandMPNN checkout?")

sys.argv = [os.path.join(mpnn_dir, "run.py"), *sys.argv[2:]]
# Everything in the checkout imports its siblings unqualified (`from sc_utils import ...`,
# `from model_utils import ...`). Checked against this venv: none of the checkout's
# top-level names (data_utils, model_utils, openfold, run, sc_utils, score) shadows a
# stdlib module or an installed one.
sys.path.insert(0, mpnn_dir)
os.chdir(mpnn_dir)
# `run_name="__main__"` because run.py does all of its work under an `if __name__ ==
# "__main__"` guard; imported any other way it defines `main` and exits having done
# nothing, which would look exactly like a successful run that produced no output.
#
# The usual runpy hazard does not apply, and it is worth saying so rather than having it
# re-derived: under multiprocessing's `spawn`, children re-import __main__ - which here is
# this shim - and would re-run run.py. `run.py` uses no DataLoader, no multiprocessing and
# no num_workers (checked), so no child is ever spawned. That stops being true if it does.
runpy.run_path(os.path.join(mpnn_dir, "run.py"), run_name="__main__")
'''


class LigandMPNNDesignAgent(TaskAgent):
    """Sequence design + side-chain packing conditioned on a backbone and its ligand."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        mpnn_dir = os.environ.get("MPNN_DIR")
        if not mpnn_dir:
            raise RuntimeError("MPNN_DIR is not set - see scripts/delta_env_setup.sh")

        backbone_pdb = first_dep_output(req.inputs, "backbone")
        if not backbone_pdb:
            raise RuntimeError("ligandmpnn_design: no upstream 'backbone' output found")

        root = Path(mpnn_dir)
        out = workdir_for(req, "ligandmpnn")
        # Not `run.py` directly: it cannot import under this venv's numpy. See MPNN_SHIM.
        #
        # `sys.executable` rather than a bare "python": PATH was in fact correct on job
        # 22669509 (the launcher activates the venv before `dragon -s`, and the failure
        # proves it found our numpy and torch), so this is not a bug fix - it removes the
        # dependency on that staying true.
        #
        # `-P` keeps the shim's own directory off sys.path. CPython otherwise prepends the
        # script's directory, which would put a LigandMPNN *output* directory ahead of the
        # stdlib for the whole run - harmless today, and a shadowing bug with a traceback
        # pointing at torch on the day anything writes a .py-named file in there.
        shim = out / "mpnn_run.py"
        shim.write_text(MPNN_SHIM)
        cmd = [
            sys.executable, "-P", str(shim), str(root),
            "--model_type", "ligand_mpnn",
            # Both checkpoints, ABSOLUTE and explicit. `run.py` defaults them to
            # "./model_params/..." - relative to the CURRENT WORKING DIRECTORY, which for
            # us is the campaign root, not the checkout. Left implicit, every invocation
            # fails on a missing path. The original IMPRESS pipeline guards this twice
            # over: it passes both flags AND chdir's into the checkout (its
            # `scripts/mpnn_run.py` shim); we do the same below.
            "--checkpoint_ligand_mpnn",
            str(root / "model_params" / "ligandmpnn_v_32_010_25.pt"),
            "--checkpoint_path_sc",
            str(root / "model_params" / "ligandmpnn_sc_v_32_002_16.pt"),
            "--pdb_path", str(backbone_pdb),
            "--out_folder", str(out),
            "--temperature", str(params["temperature"]),
            # `--number_of_batches` is batches, not sequences; with `--batch_size`
            # unset (default 1) one batch is one sequence, so this holds only while
            # num_seqs stays small. Confirm against `run.py --help` before raising it.
            "--number_of_batches", str(params["num_seqs"]),
        ]
        if params.get("seed") is not None:
            cmd += ["--seed", str(params["seed"])]
        if params["pack_side_chains"]:
            cmd += ["--pack_side_chains", "1", "--pack_with_ligand_context", "1"]
        if params.get("fixed_residues"):
            cmd += ["--fixed_residues", params["fixed_residues"]]
        # cwd=$MPNN_DIR: every other relative path inside `run.py` and its bundled
        # openfold resolves the same way the checkpoints do. `--out_folder` and
        # `--pdb_path` are absolute, so nothing lands in the checkout.
        await run_cmd(cmd, cwd=root,
                      timeout_s=float(self.spec.resources.walltime_s))

        fastas = sorted(out.glob("seqs/*.fa")) or sorted(out.glob("**/*.fa"))
        packed = sorted(out.glob("**/packed/*.pdb")) or sorted(out.glob("**/*.pdb"))
        if not fastas or not packed:
            return {"result": None, "count": 0, "outputs": {}, "metrics": {}}

        overall = ligand = 0.0
        for header in fastas[0].read_text().splitlines():
            if m := _CONF_RE.search(header):
                overall, ligand = float(m.group(1)), float(m.group(2))
                break

        return {
            "result": "structure",
            "count": len(packed),
            "outputs": {"structure": packed[0]},
            "metrics": {"overall_confidence": round(overall, 3),
                        "ligand_confidence": round(ligand, 3)},
        }
