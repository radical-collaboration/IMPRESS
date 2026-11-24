"""K6: the four episodes as one call, so `MDLabelAgent.run` has something to call.

K2 builds the legs, K3 runs the seeded replicas, K4 measures the three labels and the telemetry,
K5 takes the free-energy samples out of the same frames. This module is the order they go in and
nothing else: no arithmetic lives here, and every number it returns comes from one of those four.

### What it refuses, and why each refusal is by name

* **No `design_dir`** -- `md_label` is a root and `compose/validate.py:79`-`:81` waves an
  unsatisfied root input through, so a campaign that forgets it would otherwise measure whatever
  an empty path points at.
* **No complex inside it.** The names tried are declared in `COMPLEX_NAMES`, in refinement order,
  and **which one was used is recorded in the result** -- the pattern J9 set for pocket rules. A
  measurement whose input file was chosen by a search nobody can see is a measurement nobody can
  reproduce.
* **No parameter directory.** This is the one refusal that is about meaning rather than
  plumbing: K1's artifact is what says ALR is GAFF2 and not CGenFF, and **a force field is part
  of what a measured number means**. Defaulting it would let a run inherit a force field by
  accident, which is the determination in [K1] turned into a silent variable.

### The platform is chosen, recorded, and never assumed

`CUDA` when the plugin and a device are both there, `CPU` otherwise, and the answer is in the
result. The protocol is identical on both -- that is the point of K2-K4 running on `CPU` in every
test -- but a label that does not say which it ran on cannot be compared with one that does.

### The cost telemetry, which is what K6 still owes

`gpu_hours_observed` and `ns_per_day` are measured here and reported. **They are not written
into the spec by this module**: `md_label`'s declared 8.1 GPU-h is 3.6 worst-observed x 2.25
where the 3.6 was never measured, and replacing an unmeasured number with a CPU extrapolation
would be the same defect with a fresher date on it. The first run on a GPU prints `ns_per_day`,
and item 21's rule turns that into the figure.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .system import LEGS

#: Where the design's relaxed complex is looked for inside `design_dir`, **in refinement
#: order**. `fastrelax.pdb` first because `rosetta_agents` writes it last and it is the structure
#: a design's own chain ends on; `packmin.pdb` is the same chain one stage earlier.
COMPLEX_NAMES = ("fastrelax.pdb", "packmin.pdb", "complex.pdb")

ARTIFACT_NAME = "md_label.json"


class ProtocolFailed(RuntimeError):
    """A measurement this module will not report, with the reason named."""


@dataclass
class Measured:
    """One design's measurement: the metrics, the files, and what it cost."""

    design_dir: str = ""
    out_dir: str = ""
    complex_pdb: str = ""
    complex_name: str = ""
    platform: str = ""
    ligand_resname: str = ""
    design_ligand_resname: str = ""
    legs: Dict[str, Any] = field(default_factory=dict)
    replicates: Dict[str, List[Any]] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    free_energy: Optional[Dict[str, Any]] = None
    trajectory: str = ""
    structure: str = ""
    ns_per_leg: Dict[str, float] = field(default_factory=dict)
    wall_seconds: float = 0.0
    gpu_hours_observed: float = 0.0
    ns_per_day: Optional[float] = None
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, directory: str = "") -> str:
        path = os.path.join(directory or self.out_dir, ARTIFACT_NAME)
        with open(path, "w") as handle:
            json.dump(self.as_dict(), handle, indent=1, default=str)
        return path


def resolve_complex(design_dir: str) -> tuple:
    """The design's relaxed complex, by the declared search order. Returns (path, name)."""
    if not design_dir:
        raise ProtocolFailed(
            "no design_dir. md_label is a root -- the complex arrives as a parameter and "
            "nothing upstream checks that it did"
        )
    if not os.path.isdir(design_dir):
        raise ProtocolFailed(f"design_dir {design_dir} is not a directory")
    for name in COMPLEX_NAMES:
        path = os.path.join(design_dir, name)
        if os.path.exists(path):
            return path, name
    raise ProtocolFailed(
        f"{design_dir} holds none of {list(COMPLEX_NAMES)}. Those are the names the real "
        "Rosetta adapters write (`rosetta_agents.py:354`, `:372`); a design directory with "
        "some other name for its complex needs that name added here, where the order is "
        "declared, rather than guessed at by this function"
    )


def pick_platform(preferred: str = "") -> str:
    """`CUDA` if it is really there, else `CPU`, and the answer is returned rather than assumed.

    "Really there" means a `Context` can be made: the CUDA plugin loads without a device, so
    `getPlatformByName("CUDA")` succeeds on a login node and then fails inside the run.
    """
    import openmm  # noqa: PLC0415

    names = [openmm.Platform.getPlatform(i).getName()
             for i in range(openmm.Platform.getNumPlatforms())]
    if preferred:
        if preferred not in names:
            raise ProtocolFailed(
                f"platform {preferred!r} is not available here; this build has {names}")
        return preferred
    if "CUDA" in names:
        try:
            system = openmm.System()
            system.addParticle(1.0)
            openmm.Context(system, openmm.VerletIntegrator(0.001),
                           openmm.Platform.getPlatformByName("CUDA"))
            return "CUDA"
        except Exception:  # no device behind the plugin
            pass
    return "CPU" if "CPU" in names else names[0]


def measure(
    *,
    design_dir: str,
    params_dir: str,
    out_dir: str,
    apo_ns: float = 15.0,
    holo_ns: float = 15.0,
    md_replicates: int = 3,
    seed: int = 0,
    platform: str = "",
    mmgbsa: bool = True,
    mmgbsa_stride: int = 1,
    amberhome: str = "",
    padding_nm: float = 0.0,
    heat_ps: float = 0.0,
    npt_ps: float = 0.0,
    frames_per_ns: int = 0,
    hmr: Optional[bool] = None,
) -> Measured:
    """Both legs, the ensemble, the metrics, and -- when asked -- the free-energy samples.

    The keyword-only arguments after `mmgbsa_stride` are the ones a test turns down to make a
    smoke finish. They default to the module's own production values, so an agent that passes
    only what `md_label`'s spec declares gets the protocol as specified.
    """
    from .analysis import measure_all  # noqa: PLC0415
    from .ensemble import DEFAULT_REPLICATES, MAX_REPLICATES, run_replicate  # noqa: PLC0415
    from .params import LigandParameters  # noqa: PLC0415
    from .system import (  # noqa: PLC0415
        DEFAULT_HMR,
        HEAT_PS,
        NPT_PS,
        SOLVENT_PADDING_NM,
        build_leg,
        equilibrate,
    )

    if not params_dir:
        raise ProtocolFailed(
            "no parameter directory. K1's artifact is what records that this ligand is GAFF2 "
            "and not CGenFF, and a force field is part of what a measured number means -- so "
            "this is passed explicitly rather than defaulted. The committed one is "
            "campaigns/data/alr/md"
        )
    md_replicates = int(md_replicates or DEFAULT_REPLICATES)
    # `None`, not `False`, so "nothing said" is distinguishable from "2 fs was asked for".
    hmr = DEFAULT_HMR if hmr is None else bool(hmr)
    if not 1 <= md_replicates <= MAX_REPLICATES:
        raise ProtocolFailed(
            f"md_replicates={md_replicates} is outside the spec's own 1-{MAX_REPLICATES}")
    complex_pdb, complex_name = resolve_complex(design_dir)
    artifact = LigandParameters.load(params_dir)
    platform = pick_platform(platform)
    os.makedirs(out_dir, exist_ok=True)
    ns = {"apo": float(apo_ns), "holo": float(holo_ns)}
    started = time.time()

    legs: Dict[str, Any] = {}
    reps: Dict[str, List[Any]] = {}
    for leg in LEGS:
        built = build_leg(leg=leg, complex_pdb=complex_pdb, params_dir=params_dir,
                          out_dir=os.path.join(out_dir, leg), amberhome=amberhome,
                          padding_nm=padding_nm or SOLVENT_PADDING_NM)
        legs[leg] = equilibrate(built, platform=platform, heat_ps=heat_ps or HEAT_PS,
                                npt_ps=npt_ps or NPT_PS, hmr=hmr, seed=seed)
        reps[leg] = [
            run_replicate(legs[leg], index=i, base_seed=seed, ns=ns[leg], platform=platform,
                          hmr=hmr,
                          **({"frames_per_ns": frames_per_ns} if frames_per_ns else {}))
            for i in range(md_replicates)
        ]

    metrics = measure_all(
        legs=legs, replicates=reps, complex_pdb=complex_pdb,
        design_ligand_resname=artifact.pdb_resname or artifact.resname,
        ligand_resname=artifact.resname,
    )
    free_energy = None
    if mmgbsa:
        free_energy = _free_energy(
            legs["holo"], reps["holo"], params_dir=params_dir, amberhome=amberhome,
            stride=mmgbsa_stride)

    wall = time.time() - started
    sampled = sum(ns[leg] * md_replicates for leg in LEGS)
    return Measured(
        design_dir=design_dir, out_dir=out_dir, complex_pdb=complex_pdb,
        complex_name=complex_name, platform=platform,
        ligand_resname=artifact.resname,
        design_ligand_resname=artifact.pdb_resname or artifact.resname,
        legs={k: v.as_dict() for k, v in legs.items()},
        replicates={k: [r.as_dict() for r in v] for k, v in reps.items()},
        metrics={k: v.as_dict() for k, v in metrics.items()},
        free_energy=free_energy,
        # The two artifacts the spec declares. The `structure` port is the equilibrated holo
        # frame, which is what makes [md_label, abfe_label] type at all.
        trajectory=reps["holo"][0].trajectory,
        structure=legs["holo"].equilibrated_pdb,
        ns_per_leg=dict(ns), wall_seconds=round(wall, 1),
        # Observed, not declared. One GPU for the whole call, so wall clock IS the GPU-hour
        # figure -- and on `CPU` this number is not a GPU-hour at all, which is why the
        # platform travels beside it.
        gpu_hours_observed=round(wall / 3600.0, 4),
        ns_per_day=(round(sampled * 86400.0 / wall, 2) if wall > 0 else None),
        notes=(f"{md_replicates} replicas per leg, {sampled:.3f} ns sampled in total, "
               f"platform {platform}"),
    )


def _free_energy(holo, replicates, *, params_dir: str, amberhome: str, stride: int):
    """K5, over the holo leg. **A failure here does not fail the measurement.**

    The three labels are what this tool exists to produce, and the free-energy sample is a
    second product of the same frames. A dry build that fails costs the sample and has not
    stopped the instrument working -- which is why `dg_mmgbsa` is deliberately absent from
    `metrics_reported`, and why this is caught rather than raised.
    """
    from . import freeenergy  # noqa: PLC0415

    try:
        dry = freeenergy.build_dry_topologies(
            holo_dir=holo.directory, params_dir=params_dir, amberhome=amberhome)
        samples = freeenergy.mmgbsa(
            runs=[(r.trajectory, holo.equilibrated_pdb) for r in replicates],
            dry=dry, solvated_prmtop=holo.prmtop, params_dir=params_dir, stride=stride)
        return samples.as_dict()
    except (freeenergy.FreeEnergyFailed, OSError) as exc:
        return {"metric": freeenergy.METRIC, "value": None, "sigma": None,
                "reason": f"not sampled: {exc}"}


def as_task_result(measured: Measured) -> Dict[str, Any]:
    """The adapter's return value: the two ports, the metrics, and the provenance beside them.

    Only metrics with a value are reported. A metric reported as `None` would be read by
    `metrics_reported` as present -- which is how a gate passes on a measurement that was never
    made.
    """
    metrics: Dict[str, Any] = {}
    for name, m in measured.metrics.items():
        if name == "pocket_residues":
            continue
        if m.get("value") is not None:
            metrics[name] = m["value"]
    fe = measured.free_energy or {}
    if fe.get("value") is not None:
        metrics[fe.get("metric", "dg_mmgbsa")] = fe["value"]
    pocket = (measured.metrics.get("pocket_residues") or {}).get("value")
    fe_prov = (measured.free_energy or {}).get("provenance") or {}
    return {
        "result": "md_label",
        "count": 1,
        "outputs": {"trajectory": measured.trajectory, "structure": measured.structure},
        "metrics": metrics,
        # The sigmas travel beside the values rather than as metrics: a sigma is not a measured
        # quantity of the molecule, and `labels_workflow.POSTERIOR_ONLY` refuses that class of
        # name for exactly this reason. `LabelRecord.sigma` is where they are consumed.
        "sigmas": {name: m.get("sigma") for name, m in measured.metrics.items()
                   if m.get("sigma") is not None},
        # **The path, not the payload.** The full record is tens of kilobytes -- every replica's
        # seeds, frame counts and file paths -- and a task result is carried in campaign state
        # and written into provenance lines. What goes here is what a reader needs to compare
        # this label with a prediction, and where the rest of it is.
        "artifact": os.path.join(measured.out_dir, ARTIFACT_NAME),
        "provenance": {
            "platform": measured.platform,
            "complex": measured.complex_name,
            "ligand_resname": measured.ligand_resname,
            "design_ligand_resname": measured.design_ligand_resname,
            # The pocket's SIZE is provenance about the selection, not a quantity of the
            # molecule -- but it is the number that says whether the label and Model B's
            # prediction are about the same residues, so it travels with the label.
            "pocket_residues": pocket,
            "ns_per_leg": dict(measured.ns_per_leg),
            "wall_seconds": measured.wall_seconds,
            "gpu_hours_observed": measured.gpu_hours_observed,
            "ns_per_day": measured.ns_per_day,
            "force_field": {k: fe_prov.get(k) for k in
                            ("ligand_force_field", "ligand_charge_method",
                             "protein_force_field")} if fe_prov else {},
        },
    }
