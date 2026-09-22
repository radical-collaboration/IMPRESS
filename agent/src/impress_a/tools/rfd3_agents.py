"""RFD3 (RFdiffusion3) task agent - backbone generation inside the `foundry` container.

Adapted from `IMPRESS/examples/small_molecule_binding/small_molecule_binding.py`'s
`rfd3()` step: an Apptainer/Singularity `rfd3 design` invocation against a JSON input
spec, producing `.cif.gz` backbone models plus a per-model metrics JSON.

All heavy/optional imports (gemmi, Biopython) happen inside `run()`, never at module
scope - `Registry.load()` and `Validator.dry_run()` must work with none of them installed.
"""
from __future__ import annotations

import json
import os
from typing import Any

from ._subprocess import run_cmd, workdir_for
from .agent import TaskAgent, TaskRequest


class RFD3DesignAgent(TaskAgent):
    """De novo backbone generation. More `diffusion_steps` trades wall-clock for quality."""

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        foundry = os.environ.get("FOUNDRY_SIF_PATH")
        if not foundry:
            raise RuntimeError(
                "FOUNDRY_SIF_PATH is not set - see scripts/delta_env_setup.sh / "
                "the original IMPRESS pull_foundry.sh")

        work = workdir_for(req, "rfd3")
        spec_path = work / "rfd3_input.json"
        rfd3_spec: dict[str, Any] = {
            "contig": params["contig"],
            "ligand_resname": params["ligand_resname"],
            "num_designs": params["num_designs"],
            "diffusion_steps": params["diffusion_steps"],
        }
        if params.get("seed") is not None:
            rfd3_spec["seed"] = params["seed"]
        spec_path.write_text(json.dumps(rfd3_spec))

        await run_cmd([
            "apptainer", "exec", "--nv", foundry,
            "rfd3", "design",
            "--config", str(spec_path),
            "--out", str(work),
        ], timeout_s=float(self.spec.resources.walltime_s))

        cif_models = sorted(work.glob("*.cif.gz"))
        if not cif_models:
            return {"result": None, "count": 0, "outputs": {},
                    "metrics": {"ss_fraction": 0.0}}

        from ._pdbtools import cif_gz_to_pdb, secondary_structure_fraction

        best_pdb = work / "backbone_0.pdb"
        cif_gz_to_pdb(cif_models[0], best_pdb)
        ss_fraction = secondary_structure_fraction(best_pdb)

        return {
            "result": "backbone",
            "count": len(cif_models),
            "outputs": {"backbone": best_pdb},
            "metrics": {"ss_fraction": ss_fraction, "num_models": len(cif_models)},
        }
