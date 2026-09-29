"""RFD3 (RFdiffusion3) task agent - backbone generation inside the `foundry` container.

Adapted from `IMPRESS/examples/small_molecule_binding/scripts/rfd3.sh`'s real, working
invocation (cross-checked directly against the installed `rfd3` CLI's source,
`rfd3.cli:design` - a Typer app with `allow_extra_args=True, ignore_unknown_options=True`
that forwards every arg as a Hydra config override into `hydra.compose(...)`). There are
NO `--flag` options: `rfd3 design out_dir=... inputs=... key=value ...`, never
`--config`/`--out`. Guided vs. unguided diffusion is selected entirely by which
`inputs=` JSON file is pointed at (a `DesignInputSpecification`: input PDB, contig,
ligand, select_exposed/select_buried, ...) - RFD3 has no scaffold/guidance CLI override.

All heavy/optional imports (gemmi, Biopython) happen inside `run()`, never at module
scope - `Registry.load()` and `Validator.dry_run()` must work with none of them installed.
"""
from __future__ import annotations

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
        if not params["input_spec_path"]:
            raise RuntimeError(
                "rfd3_design: input_spec_path is empty - set it to a real "
                "DesignInputSpecification JSON (see campaigns/data/alr/ALR_binder_design.json)")

        work = workdir_for(req, "rfd3")
        overrides = [
            f"out_dir={work}",
            f"inputs={params['input_spec_path']}",
            "skip_existing=False",
            "dump_trajectories=True",
            "prevalidate_inputs=True",
            f"diffusion_batch_size={params['num_designs']}",
            f"inference_sampler.num_timesteps={params['diffusion_steps']}",
        ]
        if params.get("seed") is not None:
            overrides.append(f"seed={params['seed']}")

        # --bind $SCRATCH: apptainer binds $HOME, /tmp and the CWD by default, and nothing
        # else. `inputs=` points into the repo and `out_dir=` into the per-job scratch
        # tree, both under $SCRATCH on Delta and neither reachable in the container
        # without this. The original IMPRESS pipeline binds the same way
        # (`scripts/rfd3.sh`). Deliberately NOT adding its `--writable-tmpfs`: that gives
        # the container a throwaway writable root, and the same pipeline records rfd3
        # exiting 0 having written its output into that overlay, leaving an empty out_dir
        # - a silent failure. Add it only if a real run shows the container needs it.
        binds: list[str] = []
        if scratch := os.environ.get("SCRATCH"):
            binds = ["--bind", f"{scratch}:{scratch}"]

        await run_cmd([
            "apptainer", "exec", "--nv", *binds, foundry,
            "rfd3", "design", *overrides,
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
