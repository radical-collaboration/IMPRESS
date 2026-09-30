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


def _container_env() -> dict[str, str]:
    """The environment the `foundry` container should see - ours, minus the three
    variables that would make it import this campaign's Python instead of its own.

    apptainer bind-mounts `$HOME` by default and passes the whole environment through,
    so without this the container inherits `PYTHONPATH` (this repo, via the editable
    install), `PYTHONUSERBASE`, and `~/.local/lib/python3.x/site-packages` - a second,
    incompatible torch/numpy stack layered over the image's own. The original IMPRESS
    pipeline unsets exactly these three and sets `PYTHONNOUSERSITE` before exec
    (`scripts/rfd3.sh:19-22`); this is that, as a dict.

    Note `PYTHONNOUSERSITE` is *set*, not unset: it is read for presence, so any value
    - including "0" - disables user site-packages.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONUSERBASE", "PYTHONDONTWRITEBYTECODE")}
    env["PYTHONNOUSERSITE"] = "1"
    return env


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
            # False, not the CLI's default True: upstream measured trajectories at
            # 11.85 MB of each 11.92 MB output dir - 99.4% - and flipped it (IMPRESS
            # 0800ad8), taking a campaign from ~30 GB to ~3.8 GB. Safe for us because
            # nothing here reads them: the candidates are discovered by globbing
            # `*.cif.gz`, and trajectory files ship no sidecar `.json` (see G2).
            "dump_trajectories=False",
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
        ], env=_container_env(), timeout_s=float(self.spec.resources.walltime_s))

        # A candidate is a model that carries a sidecar metadata JSON - NOT whatever a bare
        # `*.cif.gz` glob turns up first. RFD3 writes its trajectories as `.cif.gz` too
        # (`*_denoised_model_*`, `*_noisy_model_*`), and `denoised` sorts BEFORE the design's
        # own name, so `sorted(work.glob("*.cif.gz"))[0]` converted a multi-frame trajectory
        # and handed it downstream as the backbone. Measured on job 22536706: a 5.7 MB
        # backbone_0.pdb built from a 1.7 MB trajectory sitting beside the real 19 KB design,
        # with ss_fraction computed on the stack. `dump_trajectories=False` above happens to
        # hide it by not writing those files, which is exactly why selection must not depend
        # on that flag. Same discovery rule as the reference IMPRESS pipeline; see backlog G2.
        cif_models = []
        for meta in sorted(work.glob("*_model_*.json")):
            cif = meta.with_name(meta.name[:-len(".json")] + ".cif.gz")
            if cif.exists():
                cif_models.append(cif)

        if not cif_models:
            stray = sorted(work.glob("*.cif.gz"))
            if stray:
                # Structures with no metadata beside them. Picking one would be a guess at
                # which of them is a design, and this project's whole thesis is that a
                # confident guess is worse than a loud failure.
                raise RuntimeError(
                    f"rfd3_design: {len(stray)} .cif.gz in {work} but none carries a sidecar "
                    f"*_model_*.json (first: {stray[0].name}). rfd3 writes that JSON for every "
                    "design and none for a trajectory, so this is not an out_dir we can pick a "
                    "candidate from - check dump_prediction_metadata_json.")
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
