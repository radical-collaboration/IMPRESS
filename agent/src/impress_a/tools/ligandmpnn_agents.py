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

from ._ensemble import member_index, select_best
from ._subprocess import child_env, input_path, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

# LigandMPNN writes confidence into its FASTA headers, e.g.:
# >design, id=1, overall_confidence=0.6421, ligand_confidence=0.5817
_CONF_RE = re.compile(r"overall_confidence=([\d.]+),\s*ligand_confidence=([\d.]+)")


def _parse_all_confidences(fasta_text: str) -> list[dict[str, float]]:
    """One entry per header that carries confidences, in file order.

    Real LigandMPNN writes **every candidate for a design into one file**, so a parser that
    stops at the first header reads one candidate and ignores the rest. The reference pipeline
    recorded exactly that: `analysis_sequence` "silently never compared MPNN candidates against
    each other", which is what made `mpnn_ensemble_size` inert there until it was fixed.

    A header the regex cannot read is skipped rather than recorded as 0.0/0.0 - a parser
    failure must not be indistinguishable from a genuinely bad design, and omitted it is caught
    by the integrity gate `metrics_reported`.
    """
    out = []
    for header in fasta_text.splitlines():
        if m := _CONF_RE.search(header):
            out.append({"overall_confidence": round(float(m.group(1)), 3),
                        "ligand_confidence": round(float(m.group(2)), 3)})
    return out


def _parse_confidence(fasta_text: str) -> dict[str, float]:
    """The BEST candidate's confidences, or empty if none parses.

    Best by `overall_confidence`, which is the metric the spec's acceptance gate reads - so the
    candidate carried forward is the one judged, rather than whichever appeared first.
    """
    candidates = _parse_all_confidences(fasta_text)
    best = select_best(candidates, lambda c: c.get("overall_confidence"))
    return best[1] if best is not None else {}

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
import sys

# CPython prepends this script's own directory to sys.path, and this script is written
# into a LigandMPNN *output* directory - so that directory would otherwise sit ahead of
# the stdlib for the whole run, invisible until something writes a .py-named file in
# there. `-P` is the interpreter flag for exactly this, but it is 3.11+ and the package
# floor is 3.10 (README), where it is a hard `Unknown option: -P` before this script ever
# starts. So the job is done here, where it holds on every version.
#
# Above `runpy`/`warnings`/`numpy` and not below: those are shadowable, while `os` and
# `sys` are in sys.modules before this script runs, so reaching them up here is safe.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if p and os.path.abspath(p) != _here]

import runpy
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


def ligandmpnn_command(params: dict[str, Any], *, python: Any, shim: Any, mpnn_dir: Any,
                       backbone: Any, out_dir: Any) -> list[str]:
    """THE command `ligandmpnn_design` runs. Pure: every path is an argument.

        <python> <shim> <mpnn_dir> --model_type ligand_mpnn --checkpoint_... --pdb_path ...

    `python` is `sys.executable`, `shim` is `MPNN_SHIM` written into the task's workdir,
    and `mpnn_dir` is `$MPNN_DIR` (a LigandMPNN checkout); none is in the spec. The command
    runs with `cwd=$MPNN_DIR`. `num_seqs` is declared by the spec and passed nowhere here.
    """
    root = Path(mpnn_dir)
    cmd = [
        str(python), str(shim), str(root),
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
        "--pdb_path", str(backbone),
        "--out_folder", str(out_dir),
        "--temperature", str(params["temperature"]),
        # ONE WIDE BATCH, not several narrow ones. `--batch_size` is candidates per
        # forward pass and `--number_of_batches` is passes, so the old form - batches set
        # to `num_seqs` with `--batch_size` left at its default of 1 - asked for N
        # sequential batches of one, which is the worse of the two options for a model
        # tuned for batched output. The comment here used to say "confirm against
        # `run.py --help` before raising it", and that is now `impress-a preflight`'s job:
        # A3's lesson is that a tool's contract was not merely unverified but WRONG
        # (RFD3 was invoked with flags its real CLI does not have), so a flag nobody has
        # run is a flag that may not exist.
        "--batch_size", str(params["batch_size"]),
        "--number_of_batches", str(params["number_of_batches"]),
    ]
    if params.get("seed") is not None:
        cmd += ["--seed", str(params["seed"])]
    if params["pack_side_chains"]:
        # `--number_of_packs_per_design` defaults to 4 in run.py, and the adapter uses
        # packed[0]. Job 22684607 produced backbone_0_packed_1_{1,2,3,4}.pdb and threw
        # three away - and reported count: 4 for ONE sequence, which is wrong twice
        # over: four packs of one design are not four candidates, and breadth in this
        # project comes from `replicas`, never from a tool's internal N. The reference
        # pipeline passes 1 explicitly (scripts/mpnn.sh:30).
        cmd += ["--pack_side_chains", "1", "--pack_with_ligand_context", "1",
                "--number_of_packs_per_design", "1"]
    if params.get("fixed_residues"):
        cmd += ["--fixed_residues", params["fixed_residues"]]
    return cmd


class LigandMPNNDesignAgent(TaskAgent):
    """Sequence design + side-chain packing conditioned on a backbone and its ligand."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        mpnn_dir = os.environ.get("MPNN_DIR")
        if not mpnn_dir:
            raise RuntimeError("MPNN_DIR is not set - see scripts/delta_env_setup.sh")

        backbone_pdb = input_path(req, "backbone")
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
        # No `-P` here: keeping the shim's own directory off sys.path is the shim's own
        # first act, because the flag is 3.11+ and this package supports 3.10. See the
        # comment at that line in MPNN_SHIM for why the guarantee is needed at all.
        shim = out / "mpnn_run.py"
        shim.write_text(MPNN_SHIM)
        cmd = ligandmpnn_command(params, python=sys.executable, shim=shim, mpnn_dir=root,
                                 backbone=backbone_pdb, out_dir=out)
        # cwd=$MPNN_DIR: every other relative path inside `run.py` and its bundled
        # openfold resolves the same way the checkpoints do. `--out_folder` and
        # `--pdb_path` are absolute, so nothing lands in the checkout.
        await run_cmd(cmd, cwd=root, env=child_env(req),
                      timeout_s=float(self.spec.resources.walltime_s))

        fastas = sorted(out.glob("seqs/*.fa")) or sorted(out.glob("**/*.fa"))
        packed = sorted(out.glob("**/packed/*.pdb")) or sorted(out.glob("**/*.pdb"))
        if not fastas or not packed:
            return {"result": None, "count": 0, "outputs": {}, "metrics": {}}

        # Every candidate in the file, then the best of them - not the first. Real LigandMPNN
        # writes all of a design's candidates into one `.fa`, so reading one header was reading
        # one candidate out of `num_seqs` and paying for the rest.
        candidates = _parse_all_confidences(fastas[0].read_text())
        choice = select_best(candidates, lambda c: c.get("overall_confidence"))
        metrics = dict(choice[1]) if choice is not None else {}
        metrics["ensemble_size"] = float(len(candidates) or len(packed))

        # The packed structure that belongs to the chosen candidate. Paired by member number;
        # if the two sets cannot be paired one-to-one, keep index 0 and SAY so rather than
        # selecting confidently from a mismatched pair - two independently-sorted globs agree
        # only by luck, which is the bug this whole helper exists for.
        structure, paired = packed[0], False
        if choice is not None and len(packed) == len(candidates) > 1:
            idx = choice[0]
            by_index = {member_index(p): p for p in packed}
            if None not in by_index and idx in by_index:
                structure, paired = by_index[idx], True
            elif idx < len(packed):
                structure, paired = packed[idx], True
        metrics["ensemble_paired"] = 1.0 if paired or len(packed) == 1 else 0.0

        return {
            "result": "structure",
            "count": len(packed),
            "outputs": {"structure": structure},
            "metrics": metrics,
        }
