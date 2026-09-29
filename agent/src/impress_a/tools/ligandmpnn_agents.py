"""LigandMPNN task agent - ligand-context-aware inverse folding + side-chain packing.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`mpnn()` step: `python $MPNN_DIR/run.py --model_type ligand_mpnn ...`, run from the cloned
checkout (`$MPNN_DIR`), not a pip package.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ._subprocess import first_dep_output, run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest

# LigandMPNN writes confidence into its FASTA headers, e.g.:
# >design, id=1, overall_confidence=0.6421, ligand_confidence=0.5817
_CONF_RE = re.compile(r"overall_confidence=([\d.]+),\s*ligand_confidence=([\d.]+)")


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
        cmd = [
            "python", str(root / "run.py"),
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
