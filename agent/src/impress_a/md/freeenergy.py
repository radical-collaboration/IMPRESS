"""K5: free-energy samples from the ensemble K3 already ran. **No additional GPU time.**

The trajectories are written, the replicate spread exists, and an endpoint free energy is a
second product of the same frames. That is the whole economic argument for this module, and it
is why this is an episode rather than a proposal.

### What this computes, exactly, so that nobody has to guess later

MM/GBSA, **single trajectory**, endpoint, over the **holo** leg:

    dG_mmgbsa(frame) = E(complex) - E(receptor) - E(ligand)

with every term a single-point energy of the *same* frame's coordinates in **implicit** solvent
(OBC2, `igb=5`, with the ACE nonpolar surface term), and the receptor and ligand coordinates
taken from the complex rather than from separate runs. Each term is split into its gas-phase
molecular-mechanics part and its solvation part, because the split is free -- one extra
single-point per species -- and a number whose components are unavailable is a number nobody can
check.

**There is no entropy term, and the name says `dg_` anyway**, which is the one place this module
is deliberately loose about its own naming. The quantity is an interaction enthalpy plus
solvation. Normal-mode or quasi-harmonic entropy multiplies both the cost and the error bars, and
K5's exclusion list says so; `provenance["entropy_term"]` says it in the artifact, where a
reader of the corpus will actually be.

### The frames come from explicit water and the energies are evaluated in implicit water

That is standard MM/GBSA practice and it is also the single largest approximation here, so it is
recorded rather than assumed: `provenance["sampling_solvent"]` is TIP3P and
`provenance["energy_solvent"]` is OBC2. The waters and ions are **stripped**, not reparameterised,
and the strip is checked by name rather than by count -- see `DryTopologies.verify_against`.

### It is reported under its own metric name and never as `dg_abfe`

`dg_abfe` is ATM's measured value, and the *property* the bridge ingests for it is
`dg_corrected`. **The property name is what supersession matches on**, so an MM/GBSA number filed
under `dg_abfe` would silently supersede a prediction with something that is not the measurement
it claims to be, and nothing in the system would notice (item 36).

The consequence is worth stating plainly, because it looks like a gap and is not: `METRIC` is
**absent from `asteer.labels_workflow.PROPERTY_FOR_METRIC`**, so `MeasurementBridge.ingest`
refuses it by name. That refusal is correct. This is a cheap score and a candidate prior for
Model C's residual -- J14's input -- not a label that supersedes anything. It travels in the
task's own metrics and in `md_label.json`, the artifact K6's protocol writes beside the run, and
J14 reads it from there.

### Two sigmas, and only one of them is the label's

* **`sigma`** is the sample standard deviation over the *replicate means*. Same convention as
  K3 and K4, same meaning: how much of the number is the trajectory's own chaos.
* **`frame_sigma`** is the spread of the per-frame values *within* a replicate. It is the width
  of the distribution the plan asked for, and it is **not** an uncertainty on the mean -- an
  MM/GBSA frame distribution is tens of kcal/mol wide for a complex whose mean is well
  determined, and reporting it as an error bar would make every design look unmeasurable.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .params import LigandParameters
from .system import SystemBuildFailed, _run_tleap

#: The metric name. **Not `dg_abfe`, and not `dg_corrected`.** See the module docstring.
METRIC = "dg_mmgbsa"

#: What was done, in one string, for the provenance line a corpus outlives its checkout by.
METHOD = "MM/GBSA, single trajectory, endpoint, holo leg; no entropy term"

#: The implicit-solvent model the energies are evaluated in. OBC2 is `igb=5`, the MM/GBSA
#: workhorse, and `mbondi2` is the radius set it expects -- which is why the dry build sets
#: `PBRadii` explicitly rather than taking tleap's default.
GB_MODEL = "OBC2 (igb=5), ACE nonpolar surface term"
PB_RADII = "mbondi2"
SOLUTE_DIELECTRIC = 1.0
SOLVENT_DIELECTRIC = 78.5
SALT_MOLAR = 0.0

#: Three species, and the order is the order tleap builds them in: the complex is the protein
#: followed by the ligand, so the receptor is a prefix of it and the ligand is the remainder.
SPECIES = ("complex", "receptor", "ligand")

KCAL_PER_KJ = 1.0 / 4.184


class FreeEnergyFailed(RuntimeError):
    """A sample this module will not report, with the reason named."""


@dataclass
class DryTopologies:
    """The three solvent-free parameter sets the endpoint energies need."""

    directory: str
    prmtops: Dict[str, str] = field(default_factory=dict)
    n_atoms: Dict[str, int] = field(default_factory=dict)
    radii: str = PB_RADII
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def verify_against(self, solvated_prmtop: str) -> None:
        """**The strip is checked by name, not by count.**

        The dry complex has to be the leading atoms of the solvated system, in the same order,
        or slicing a trajectory frame to its first `n` atoms silently hands the receptor's
        energy function somebody else's coordinates. tleap builds `combine {PROT LIG}` and then
        appends solvent, so the prefix property holds -- and this is where that assumption stops
        being an assumption.

        **The names come out of the prmtop's own `ATOM_NAME` block**, not out of a built
        `System`. A check whose precondition is a force field is a check that cannot run before
        the thing it is checking.
        """
        dry = _atom_names(self.prmtops["complex"])
        wet = _atom_names(solvated_prmtop)
        if len(wet) < len(dry):
            raise FreeEnergyFailed(
                f"the solvated system has {len(wet)} atoms and the dry complex {len(dry)}; the "
                "dry build is not a strip of the solvated one"
            )
        head = wet[:len(dry)]
        if head != dry:
            first = next((i for i, (a, b) in enumerate(zip(dry, head)) if a != b), 0)
            raise FreeEnergyFailed(
                f"the dry complex is not the solvated system's first {len(dry)} atoms: they "
                f"differ at index {first} ({dry[first]!r} against {head[first]!r}). Slicing a "
                "frame to the dry atom count would hand each species the wrong coordinates, and "
                "the energies would be finite and wrong"
            )


@dataclass
class FreeEnergySamples:
    """One measurement's endpoint free energy: the distribution, both spreads, and why."""

    metric: str = METRIC
    value: Optional[float] = None
    sigma: Optional[float] = None
    unit: str = "kcal/mol"
    n_replicates: int = 0
    n_frames: int = 0
    per_replicate: List[Optional[float]] = field(default_factory=list)
    per_replicate_frames: List[int] = field(default_factory=list)
    per_replicate_sigma: List[Optional[float]] = field(default_factory=list)
    frame_sigma: Optional[float] = None
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    frames_reimaged: int = 0
    frames_dropped: int = 0
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -- the dry build -----------------------------------------------------------------------


def build_dry_topologies(
    *,
    holo_dir: str,
    params_dir: str,
    out_dir: str = "",
    amberhome: str = "",
) -> DryTopologies:
    """Three prmtops -- complex, receptor, ligand -- from the **same inputs K2 built from**.

    `holo_dir` is the holo leg's directory, and the protein this reads is the `protein.pdb`
    `_split_complex` wrote there. Rebuilding it from the design complex would re-derive a file
    that already exists and could differ; reading K2's own is what makes the prefix property in
    `verify_against` true by construction rather than by luck.
    """
    protein_pdb = os.path.join(holo_dir, "protein.pdb")
    if not os.path.exists(protein_pdb):
        raise FreeEnergyFailed(
            f"{holo_dir} holds no protein.pdb. The dry build reads the file K2's tleap read, "
            "so this runs after a holo build and not instead of one"
        )
    artifact = LigandParameters.load(params_dir)
    artifact.verify(params_dir)
    out_dir = out_dir or os.path.join(holo_dir, "mmgbsa")
    os.makedirs(out_dir, exist_ok=True)

    script_path = os.path.join(out_dir, "dry.leap")
    with open(script_path, "w") as handle:
        handle.write(_dry_tleap_script(
            protein_pdb=protein_pdb, params_dir=params_dir, artifact=artifact, out_dir=out_dir))
    try:
        _run_tleap(script_path, out_dir=out_dir, amberhome=amberhome)
    except SystemBuildFailed as exc:  # one failure class out of this module, named
        raise FreeEnergyFailed(f"the dry build failed: {exc}") from exc

    prmtops: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for name in SPECIES:
        path = os.path.join(out_dir, f"{name}.prmtop")
        if not os.path.exists(path):
            raise FreeEnergyFailed(
                f"tleap wrote no {name}.prmtop and returned 0, which is what it does for a "
                f"missing template. Its log is {os.path.join(out_dir, 'leap.log')}"
            )
        prmtops[name] = path
        counts[name] = _prmtop_atom_count(path)
    if counts["receptor"] + counts["ligand"] != counts["complex"]:
        raise FreeEnergyFailed(
            f"the three dry systems do not add up: {counts['receptor']} + {counts['ligand']} "
            f"!= {counts['complex']}. The endpoint difference is only a binding energy if the "
            "two halves are exactly the complex"
        )
    if counts["ligand"] != artifact.n_atoms:
        raise FreeEnergyFailed(
            f"the dry ligand has {counts['ligand']} atoms and K1's artifact declares "
            f"{artifact.n_atoms}. The ligand came from the committed mol2 in both builds, so a "
            "disagreement means they are not the same parameterised unit"
        )
    return DryTopologies(
        directory=out_dir, prmtops=prmtops, n_atoms=counts,
        notes=(f"protein {os.path.basename(protein_pdb)} + {artifact.resname} from "
               f"{artifact.files['mol2']}, {PB_RADII} radii, no solvent and no ions"),
    )


def _dry_tleap_script(*, protein_pdb: str, params_dir: str,
                      artifact: LigandParameters, out_dir: str) -> str:
    """The same force field as K2's build, solvated by nothing.

    `set default PBRadii mbondi2` is **not** optional and **not** tleap's default. OBC2 reads
    the radii out of the prmtop, so a prmtop built with the default `bondi` set gives a
    different solvation energy for the same coordinates -- the kind of discrepancy that looks
    like a result.
    """
    mol2 = os.path.abspath(os.path.join(params_dir, artifact.files["mol2"]))
    frcmod = os.path.abspath(os.path.join(params_dir, artifact.files["frcmod"]))
    protein_pdb = os.path.abspath(protein_pdb)
    out_dir = os.path.abspath(out_dir)
    lines = [
        "source leaprc.protein.ff14SB",
        "source leaprc.gaff2",
        "source leaprc.water.tip3p",
        f"loadamberparams {frcmod}",
        # After the sources, because each `source` can set it.
        f"set default PBRadii {PB_RADII}",
        f"LIG = loadmol2 {mol2}",
        f"PROT = loadpdb {protein_pdb}",
        "CPLX = combine {PROT LIG}",
    ]
    for unit_name, name in (("CPLX", "complex"), ("PROT", "receptor"), ("LIG", "ligand")):
        lines.append(
            f"saveamberparm {unit_name} {os.path.join(out_dir, name + '.prmtop')} "
            f"{os.path.join(out_dir, name + '.inpcrd')}")
    lines += ["quit", ""]
    return "\n".join(lines)


def _atom_names(path: str) -> List[str]:
    """Atom names out of a prmtop's `ATOM_NAME` block. Four characters each, twenty per line."""
    block = _prmtop_block(path, "ATOM_NAME")
    names: List[str] = []
    for line in block:
        for i in range(0, len(line.rstrip("\n")), 4):
            chunk = line[i:i + 4].strip()
            if chunk:
                names.append(chunk)
    return names


def _prmtop_block(path: str, flag: str) -> List[str]:
    with open(path) as handle:
        lines = handle.read().split("\n")
    out: List[str] = []
    collecting = False
    for line in lines:
        if line.startswith("%FLAG "):
            collecting = line[6:].strip() == flag
            continue
        if line.startswith("%FORMAT") or line.startswith("%VERSION"):
            continue
        if collecting:
            out.append(line)
    if not out:
        raise FreeEnergyFailed(f"{path} carries no {flag} block; it is not a prmtop")
    return out


def _prmtop_atom_count(path: str) -> int:
    """Atom count out of a prmtop's POINTERS block, without loading a force field for it."""
    with open(path) as handle:
        lines = handle.read().split("\n")
    for i, line in enumerate(lines):
        if line.startswith("%FLAG POINTERS"):
            for row in lines[i + 1:]:
                if row.startswith("%FORMAT"):
                    continue
                return int(row.split()[0])
    raise FreeEnergyFailed(f"{path} carries no POINTERS block; it is not a prmtop")


# -- the energies ------------------------------------------------------------------------


class _Endpoint:
    """Six contexts -- three species, implicit and gas -- built once and reused per frame.

    Built once because a `Context` carries the whole force-field setup: rebuilding one per
    frame would make the arithmetic correct and the module useless, which on a 20-frame smoke
    is invisible and on a 1500-frame production run is hours.
    """

    def __init__(self, dry: DryTopologies, *, platform: str = "CPU") -> None:
        import openmm  # noqa: PLC0415
        from openmm import app, unit  # noqa: PLC0415

        self.n_atoms = dict(dry.n_atoms)
        self._contexts: Dict[tuple, Any] = {}
        plat = openmm.Platform.getPlatformByName(platform)
        for name in SPECIES:
            prm = app.AmberPrmtopFile(dry.prmtops[name])
            shared = dict(nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False,
                          removeCMMotion=False)
            systems = {
                "gb": prm.createSystem(
                    implicitSolvent=app.OBC2, gbsaModel="ACE",
                    soluteDielectric=SOLUTE_DIELECTRIC, solventDielectric=SOLVENT_DIELECTRIC,
                    implicitSolventSaltConc=SALT_MOLAR * unit.molar, **shared),
                "gas": prm.createSystem(**shared),
            }
            for kind, system in systems.items():
                # The integrator is never stepped. A Context needs one; this one is a formality
                # and its timestep is meaningless.
                self._contexts[(name, kind)] = openmm.Context(
                    system, openmm.VerletIntegrator(0.001), plat)

    def energies(self, positions) -> Dict[str, float]:
        """Six single points, in kcal/mol, for one frame's coordinates in nanometres."""
        from openmm import unit  # noqa: PLC0415

        n_rec = self.n_atoms["receptor"]
        slices = {"complex": positions,
                  "receptor": positions[:n_rec],
                  "ligand": positions[n_rec:]}
        out: Dict[str, float] = {}
        for (name, kind), context in self._contexts.items():
            context.setPositions(unit.Quantity(slices[name], unit.nanometer))
            state = context.getState(getEnergy=True)
            out[f"{name}_{kind}"] = state.getPotentialEnergy().value_in_unit(
                unit.kilocalorie_per_mole)
        return out


def _reimage(positions, n_receptor: int, box) -> tuple:
    """Put the ligand in the periodic image nearest the receptor. Returns (positions, moved).

    OpenMM's reporter wraps **whole molecules**, so the protein arrives intact and the ligand --
    a separate molecule -- can arrive a lattice vector away. The energies here use `NoCutoff`,
    which does not know about the box, so an unreimaged frame yields a ligand bound to nothing
    and a `dG` near zero. That is the failure this function exists for, and it is silent.
    """
    import numpy as np  # noqa: PLC0415

    positions = np.array(positions, dtype=float)
    lengths = np.asarray(box, dtype=float)
    if np.any(lengths <= 0):
        return positions, False
    rec = positions[:n_receptor].mean(axis=0)
    lig = positions[n_receptor:].mean(axis=0)
    shift = -np.round((lig - rec) / lengths) * lengths
    if not np.any(np.abs(shift) > 1e-9):
        return positions, False
    positions[n_receptor:] += shift
    return positions, True


def _extent(xyz) -> float:
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(xyz, dtype=float)
    return float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))


def mmgbsa(
    *,
    runs: Sequence[tuple],
    dry: DryTopologies,
    solvated_prmtop: str = "",
    platform: str = "CPU",
    stride: int = 1,
    max_frames: int = 0,
    params_dir: str = "",
) -> FreeEnergySamples:
    """Endpoint free energies over the holo replicas. `runs` is (trajectory, topology) pairs.

    The pairs are the same shape K4's analyses take, and for the same reason: the two legs have
    different atom counts, so a topology is a property of a leg rather than of a measurement.
    **Only the holo leg has a complex**, so only the holo leg appears here.
    """
    import numpy as np  # noqa: PLC0415

    from .analysis import _load  # noqa: PLC0415
    from .ensemble import spread  # noqa: PLC0415

    if not runs:
        raise FreeEnergyFailed("no holo replica to sample; the free energy is of the complex")
    if solvated_prmtop:
        dry.verify_against(solvated_prmtop)
    stride = max(1, int(stride))
    endpoint = _Endpoint(dry, platform=platform)
    n_dry = dry.n_atoms["complex"]
    n_rec = dry.n_atoms["receptor"]

    per_mean: List[Optional[float]] = []
    per_sigma: List[Optional[float]] = []
    per_frames: List[int] = []
    pooled_var: List[float] = []
    totals: Dict[str, List[float]] = {}
    reimaged = dropped = n_frames = 0

    for trajectory, topology_pdb in runs:
        traj = _load(trajectory, topology_pdb)
        if traj.n_atoms < n_dry:
            raise FreeEnergyFailed(
                f"{trajectory} has {traj.n_atoms} atoms and the dry complex {n_dry}; this "
                "trajectory is not of the system the dry build was stripped from"
            )
        if traj.unitcell_angles is not None and len(traj.unitcell_angles):
            if np.any(np.abs(np.asarray(traj.unitcell_angles) - 90.0) > 1.0):
                raise FreeEnergyFailed(
                    "the box is not orthorhombic, and the reimaging here assumes it is. "
                    "tleap's solvatebox gives a rectangular box; a truncated octahedron would "
                    "need the real minimum-image convention"
                )
        frames = list(range(0, traj.n_frames, stride))
        if max_frames:
            frames = frames[:max_frames]
        values: List[float] = []
        reference_extent = 0.0
        for f in frames:
            xyz = traj.xyz[f, :n_dry, :]
            box = (traj.unitcell_lengths[f] if traj.unitcell_lengths is not None
                   else np.zeros(3))
            xyz, moved = _reimage(xyz, n_rec, box)
            reimaged += int(moved)
            # A molecule split across the boundary jumps to about a box length, so an extent
            # check catches it. The receptor's own extent is the reference: it is one molecule
            # and the reporter keeps it whole, so a frame where it grew is a frame to drop
            # rather than a frame to trust.
            ext = _extent(xyz[:n_rec])
            if not reference_extent:
                reference_extent = ext
            if ext > 1.5 * reference_extent:
                dropped += 1
                continue
            e = endpoint.energies(xyz)
            delta = _deltas(e)
            for key, val in delta.items():
                totals.setdefault(key, []).append(val)
            values.append(delta["dg_total"])
        n_frames += len(values)
        per_frames.append(len(values))
        if not values:
            per_mean.append(None)
            per_sigma.append(None)
            continue
        mean = sum(values) / len(values)
        per_mean.append(mean)
        if len(values) > 1:
            var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            per_sigma.append(math.sqrt(var))
            pooled_var.append(var)
        else:
            per_sigma.append(None)

    stats = spread([v for v in per_mean if v is not None])
    reason = ""
    if stats["n"] == 0:
        reason = "no replica yielded a frame this module would evaluate"
    elif stats["sigma"] is None:
        reason = ("1 replica: the sigma here is the spread over replicate means, and one "
                  "replica has none. frame_sigma is the distribution's width, not an error bar")
    artifact = LigandParameters.load(params_dir) if params_dir else None
    return FreeEnergySamples(
        value=stats["value"], sigma=stats["sigma"],
        n_replicates=len([v for v in per_mean if v is not None]),
        n_frames=n_frames,
        per_replicate=per_mean, per_replicate_sigma=per_sigma, per_replicate_frames=per_frames,
        frame_sigma=(math.sqrt(sum(pooled_var) / len(pooled_var)) if pooled_var else None),
        components={k: (sum(v) / len(v) if v else None) for k, v in sorted(totals.items())},
        provenance=provenance(artifact=artifact, dry=dry, stride=stride, platform=platform),
        frames_reimaged=reimaged, frames_dropped=dropped, reason=reason,
    )


def _deltas(e: Dict[str, float]) -> Dict[str, float]:
    """The endpoint differences, and the split that makes the total checkable.

    `dg_total` is `de_mm + dg_solv` by construction, so a reader can see which half moved. The
    two halves of an MM/GBSA binding energy are large and opposite -- tens to hundreds of
    kcal/mol each for a charged ligand -- and a total reported without them is a number whose
    cancellation nobody can inspect.
    """
    def diff(kind: str) -> float:
        return (e[f"complex_{kind}"] - e[f"receptor_{kind}"] - e[f"ligand_{kind}"])

    de_mm = diff("gas")
    solv = {name: e[f"{name}_gb"] - e[f"{name}_gas"] for name in SPECIES}
    dg_solv = solv["complex"] - solv["receptor"] - solv["ligand"]
    return {"de_mm": de_mm, "dg_solv": dg_solv, "dg_total": de_mm + dg_solv}


def provenance(*, artifact: Optional[LigandParameters], dry: Optional[DryTopologies],
               stride: int = 1, platform: str = "") -> Dict[str, Any]:
    """Everything a reader needs to know what this number is, in the record beside it.

    **A force field is part of what a measured value means.** K1 recorded that ALR is GAFF2 and
    not CGenFF because no typer was available offline; a free energy carrying that ligand's
    parameters inherits the determination, and a corpus row that does not say so is a row that
    will be compared against a CGenFF number later as though they were the same measurement.
    """
    out: Dict[str, Any] = {
        "metric": METRIC,
        "method": METHOD,
        "energy_solvent": GB_MODEL,
        "sampling_solvent": "TIP3P, explicit, from K3's production run",
        "pb_radii": PB_RADII,
        "solute_dielectric": SOLUTE_DIELECTRIC,
        "solvent_dielectric": SOLVENT_DIELECTRIC,
        "salt_molar": SALT_MOLAR,
        "entropy_term": ("none. This is an interaction enthalpy plus solvation and is not a "
                         "binding free energy with an entropy in it"),
        "not": ("not dg_abfe and not dg_corrected: ATM's measured value and Model C's "
                "prediction keep those names, and the property name is what supersession "
                "matches on"),
        "stride": stride,
        "platform": platform,
    }
    if artifact is not None:
        out["ligand_force_field"] = artifact.force_field
        out["ligand_charge_method"] = artifact.charge_method
        out["protein_force_field"] = artifact.protein_force_field
        out["ligand_resname"] = artifact.resname
        out["ligand_net_charge"] = artifact.net_charge
    if dry is not None:
        out["dry_atoms"] = dict(dry.n_atoms)
    return out
