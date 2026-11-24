"""The two physics-label adapters. **`md_label` now runs; `abfe_label` still refuses.**

`toolkits/asteer_labels/` declares both tools completely — ports, parameters, metrics, QC gates,
cost models — and `ToolSpec.entry` points here.

**K6 (2026-11-24) gave `md_label` a body.** `impress_a.md` is the protocol: tleap builds an apo
and a holo leg, OpenMM equilibrates and runs a seeded replicate ensemble, the three labels and
the convergence telemetry come out of the frames with a σ from the replicate spread, and MM/GBSA
takes free-energy samples from the same frames. `MDLabelAgent.run` composes those four steps
through `impress_a.md.protocol.measure` and reports what it measured. **It needs tleap**, which
is not pip-installable — `delta_env_setup.sh` reports where it resolved from, and the agent
refuses by name when it is absent rather than part-way through a build.

**`abfe_label` still refuses, and the refusal is still the deliverable.** It needs an
ATM/alchemical engine that nothing here has, and the alternative shapes are both worse:

* **Not declaring the tool until the body exists** would leave the chain's types, metric names
  and gates unsettled through three more episodes — the thing EI.21 was written to stop. A
  `ToolSpec` is checkable without its adapter: the registry loads it, gate 1 types the chain, gate
  2 demands its QC gates, gate 5 reads its cost model. All of that is worth having now.
* **Returning plausible numbers** would be the most expensive silent failure available here. A
  label's output *supersedes a prediction* and is never recomputed, so an invented `dg_abfe` does
  not merely report a wrong number once — it writes itself into the design tree as the measured
  truth, trains Model C against itself, and leaves no `__superseded` trail saying where the real
  measurement should have been. `toolkits/mock/` is where a stand-in belongs, under
  `toolkit: mock`, where gate 6 refuses it from a campaign declaring `tool_delivery: real`.

**The refusal happens at parameterize time, which is the only layer that can catch the root
input.** `md_label` is a root — the complex arrives as the `design_dir` *parameter* — and nothing
upstream checks that it arrived: `compose/validate.py:79`–`:81` is a literal `pass` for an
unsatisfied required input on a node with no dependencies, with the comment "roots may be
satisfied from campaign inputs". So a campaign that forgets `design_dir` composes cleanly, runs,
and measures whatever the default empty string points at. Checking it here is item 36's root-input
decision, and it is checked *before* the missing-implementation refusal so the error a caller gets
names the thing they can fix.

**Where this came from (episode H7/H8 of the re-homing, 2026-11-21).** It was
`asteer.impress.labels`, in the integration repo, and the two `entry:` strings in
`toolkits/asteer_labels/` named it there. Nothing in `asteer` imports it and nothing here did
either; it was only ever hosted across the seam. Unlike `asteer_design_agents.py` it needs no
`asteer` import at all -- these two adapters are stdlib plus `TaskAgent` -- so the move leaves
impress-a's dependency surface exactly as it was.

**impress-a has no other label tool**, which is why this is a module of its own rather than a
merge: there was no existing analogue to merge into, and `md_label`/`abfe_label` are the first
of their kind here.
"""
from __future__ import annotations

import os
from typing import Any

from .agent import TaskAgent, TaskRequest

__all__ = [
    "ABFELabelAgent",
    "LabelAdapterNotImplemented",
    "MDLabelAgent",
    "MissingRootInput",
]


class MissingRootInput(ValueError):
    """A root tool was given no path to the thing it is supposed to measure."""


class LabelAdapterNotImplemented(NotImplementedError):
    """The spec is complete and the protocol body is not. Named, not generic.

    A bare `NotImplementedError` from inside a task body reads like a bug. This says which
    episode owns the work and what the tool would need, so the message is a pointer rather
    than a dead end.
    """


def _require_design_dir(spec_id: str, params: dict[str, Any]) -> str:
    """The root-input check no gate performs. Raises rather than measuring nothing."""
    design_dir = str(params.get("design_dir") or "").strip()
    if not design_dir:
        raise MissingRootInput(
            f"{spec_id}: no `design_dir`. This tool is a root, so the complex arrives as a path "
            "parameter and NOTHING UPSTREAM CHECKS IT -- compose/validate.py:79-:81 is a literal "
            "`pass` for an unsatisfied root input ('roots may be satisfied from campaign "
            "inputs'). A campaign that omits it composes cleanly and would measure whatever the "
            "empty default points at, at several GPU-hours a design. Set it in the campaign's "
            "`params`, or have the dispatcher carry it per launch."
        )
    return design_dir


def _require_structure(spec_id: str, req: Any, params: dict[str, Any]) -> str:
    """`abfe_label`'s root-input check, which decision L1 made necessary.

    The spec declares `structure: {type: Complex}` and that port is real: it is what types
    `[md_label, abfe_label]` when the two are composed as one graph (item 36's gate-1
    argument). **But L1 split them into two campaigns**, so at runtime this tool is a root in
    its own graph — and `compose/validate.py:79`-`:81` waves an unsatisfied required input
    through for a node with no dependencies. Measured on 2026-11-19: `mock_abfe_label` alone
    passes gate 1 *and every other gate* with `structure` unwired.

    So it accepts either route and refuses when it has neither: the wired port when composed,
    `structure_path` when it is a campaign of its own. Eighteen declared GPU-hours is too much
    to spend on a default empty string.
    """
    wired = dict(getattr(req, "inputs", None) or {}).get("structure")
    path = str(params.get("structure_path") or "").strip()
    if wired or path:
        return str(wired or path)
    raise MissingRootInput(
        f"{spec_id}: no structure. The `structure` port is unwired and `structure_path` is "
        "empty, and NOTHING UPSTREAM CHECKS EITHER -- compose/validate.py:79-:81 waves an "
        "unsatisfied required input through for a node with no dependencies, so a campaign "
        "that forgets it composes cleanly and would measure whatever an empty path points at, "
        "at 18 declared GPU-hours a ligand. Wire it from md_label when the two are one graph, "
        "or set `structure_path` when this runs as its own campaign (decision L1)."
    )


def _require_md_params(spec_id: str, params: dict[str, Any]) -> str:
    """K1's parameter artifact, passed explicitly. **Never defaulted.**

    `ligand_params_path` beside it is a *Rosetta* `.params` — atom types and charges for
    Rosetta's scoring function, from which nothing transfers to an MD force field. This is the
    directory holding `ligand_parameters.json`, `ligand.mol2` and `ligand.frcmod`, and it is
    what says the ligand is GAFF2/AM1-BCC rather than CGenFF. A default here would let a run
    inherit a force field by accident, and a force field is part of what a measured number
    means — which is the whole content of K1's determination.
    """
    path = str(params.get("md_params_dir") or "").strip()
    if not path:
        raise MissingRootInput(
            f"{spec_id}: no md_params_dir. The MD protocol needs K1's parameter artifact — the "
            "directory with ligand_parameters.json, ligand.mol2 and ligand.frcmod — and it is "
            "not defaulted, because that artifact is what records the force field and a force "
            "field is part of what a measured number means. The committed one for ALR is "
            "IMPRESS/agent/campaigns/data/alr/md. `ligand_params_path` is NOT it: that is a "
            "Rosetta .params file and nothing transfers from it"
        )
    if not os.path.isdir(path):
        raise MissingRootInput(f"{spec_id}: md_params_dir {path} is not a directory")
    return path


def _require_tleap(spec_id: str, params: dict[str, Any]) -> str:
    """tleap, by where it resolved from. The one dependency `pip install` cannot supply.

    Checked here rather than inside the build because tleap's own answer to a problem is
    `Fatal Error` followed by exiting 0, and a task that has already spent minutes solvating
    is an expensive place to discover a missing binary.
    """
    import shutil  # noqa: PLC0415

    amberhome = str(params.get("amberhome") or os.environ.get("AMBERHOME", ""))
    if amberhome and os.path.exists(os.path.join(amberhome, "bin", "tleap")):
        return os.path.join(amberhome, "bin", "tleap")
    found = shutil.which("tleap")
    if found:
        return found
    raise LabelAdapterNotImplemented(
        f"{spec_id}: tleap is not on PATH and AMBERHOME does not hold it. The MD protocol "
        "builds both legs with AmberTools and there is deliberately no second path — a system "
        "assembled two ways is a ligand whose parameters exist in two formats. AmberTools is "
        "not installable from PyPI, so it comes from a cluster module, a conda-forge "
        "`ambertools` environment, or a user build; `delta_env_setup.sh` prints which of those "
        "resolved. The twin for a laptop run with no AmberTools is `mock_md_label`"
    )


def _refuse(spec_id: str, needs: str, owner: str) -> LabelAdapterNotImplemented:
    return LabelAdapterNotImplemented(
        f"{spec_id}: the ToolSpec is complete but the protocol body is not implemented. "
        f"It needs {needs}. The twin for laptop runs is `mock_{spec_id}` in toolkits/mock "
        f"(toolkit: mock, so tool_delivery: real refuses it). Implementation is {owner}. "
        "This refuses rather than returning numbers because a label's output supersedes a "
        "prediction and is never recomputed."
    )


class MDLabelAgent(TaskAgent):
    """Apo + holo MD → the three quantities Model B predicts, each with a measured σ.

    Produces `preorg_rmsd`, `rotamer_entropy` and `ligand_rmsf`, the convergence telemetry the
    integrity gate reads, `dg_mmgbsa` when `mmgbsa` is on, and two artifacts — a `Trajectory`
    and the equilibrated holo frame as a `Complex`, the second of which is what makes
    `[md_label, abfe_label]` pass gate 1 at all.

    **Three things it refuses by name, before any physics runs.** A missing `design_dir`, which
    nothing upstream checks; a missing `md_params_dir`, because K1's artifact is what records
    that this ligand is GAFF2 and not CGenFF and **a force field is part of what a measured
    number means**; and a missing tleap, which is the one dependency `pip` cannot supply, so it
    is worth a sentence rather than a stack trace from inside a build.

    **A sigma is reported for every metric that has one**, under `sigmas` rather than as a
    metric. `LabelRecord.sigma` is where the replicate spread is consumed, and
    `labels_workflow.POSTERIOR_ONLY` refuses `sigma_*` as a metric name on purpose: a sigma
    describes a distribution, not a molecule.
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        from ._subprocess import workdir_for  # noqa: PLC0415

        design_dir = _require_design_dir(self.spec.id, params)
        params_dir = _require_md_params(self.spec.id, params)
        _require_tleap(self.spec.id, params)
        from ..md import protocol  # noqa: PLC0415

        work = workdir_for(req, "md_label")
        measured = protocol.measure(
            design_dir=design_dir,
            params_dir=params_dir,
            out_dir=str(work),
            apo_ns=float(params.get("apo_ns", 15.0)),
            holo_ns=float(params.get("holo_ns", 15.0)),
            md_replicates=int(params.get("md_replicates") or 1),
            # `req.seed` and not a draw: the engine owns the seed, and two replicates are only
            # independent if the per-replica derivation gets a stable base to mix.
            seed=int(params.get("seed") or getattr(req, "seed", None) or 0),
            mmgbsa=bool(params.get("mmgbsa", True)),
            mmgbsa_stride=int(params.get("mmgbsa_stride") or 1),
            amberhome=str(params.get("amberhome") or ""),
        )
        measured.save()
        return protocol.as_task_result(measured)


class ABFELabelAgent(TaskAgent):
    """ATM alchemical transfer → the measured ΔG that supersedes Model C's prediction.

    Would produce `dg_abfe`, `dg_sem`, `n_lambda` and the overlap diagnostics. Note that the
    metric is `dg_abfe` and the *property* the bridge ingests is `dg_corrected`: the property
    name is what supersession matches on, and a mismatch is accepted silently (item 36).
    """

    async def run(self, req: TaskRequest, params: dict[str, Any]) -> dict[str, Any]:
        # A root under L1, whatever the port says. See `_require_structure`.
        _require_structure(self.spec.id, req, params)
        raise _refuse(
            self.spec.id,
            "an ATM/alchemical engine, a GPU, and an equilibrated holo frame from md_label",
            "item 20's remaining half, at M3",
        )
