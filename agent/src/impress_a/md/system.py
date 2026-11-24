"""K2: build the holo and apo systems, and equilibrate them. Production is K3.

**The apo leg is the new thing here, and it is the whole point.** Audit finding 3 of
2026-11-23: *no apo structure and no MD trajectory exists anywhere in this project's data*, so
`preorg_rmsd`, `rotamer_entropy` and `ligand_rmsf` have no measured values at all. Pre-organisation
is the difference between the pocket with the ligand in it and the pocket without -- so the apo
leg is not a control, it is half the measurement, and it has to be generated.

### The two legs

| Leg | What it is |
|---|---|
| `holo` | the design's relaxed complex, ligand included, solvated and neutralised |
| `apo` | **the same structure with the ligand deleted**, re-solvated and re-equilibrated |

Re-solvated and re-equilibrated rather than reused: deleting a ligand leaves a vacuum where it
was, and a water box built around the holo complex has no molecules in that cavity. Equilibrating
the apo leg from the holo box would measure how long it takes water to find the pocket, which is
a property of the starting condition rather than of the design.

### Why tleap builds it and OpenMM runs it

Everything this needs is installed, and that is not a coincidence -- it is why the force field is
what it is (`params.PROTEIN_FORCE_FIELD`). `tleap` assigns ff14SB to the protein, reads the
ligand's GAFF2 `mol2`/`frcmod` from K1's committed artifact, solvates in TIP3P, adds neutralising
ions, and writes `prmtop`/`inpcrd`. **OpenMM reads an Amber prmtop natively**, so there is no
ParmEd in the path and no second topology format to keep in step.

The alternative -- assembling the system in OpenMM from XML force fields -- needs
`openmmforcefields` to turn GAFF2 parameters into residue templates, and then the ligand's
parameters exist in two places in two formats. One builder, one topology.

### The numbers, and which of them are declared rather than measured

PME with a **1.2 nm cutoff and a force switch from 1.0 nm** is the CHARMM-standard pairing and is
kept even on an Amber force field, because the switch is about the *integrator* seeing a
continuous force rather than about the parameters: a hard cutoff puts a step in the force at 1.2
nm, and the energy drift that follows is exactly what `energy_drift_kcal_per_ns` would then
report as a broken instrument.

Hydrogen mass repartitioning is **off by default**. It buys a 4 fs timestep, and it does it by
moving mass from heavy atoms onto hydrogens -- which changes the dynamics of every rotatable
bond, and `rotamer_entropy` is an entropy over exactly those. A protocol that measured sidechain
entropy under HMR without saying so would report a number about a modified molecule.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .params import LigandParameters, ParameterisationFailed

#: The two legs, by name. `holo` first because the apo structure is derived from it.
LEGS = ("holo", "apo")

#: Solvent padding, nanometres. 1.0 nm is the smallest that keeps a periodic image further than
#: the 1.2 nm cutoff from the solute's own atoms in the dimension it is thinnest; below it the
#: protein sees itself.
SOLVENT_PADDING_NM = 1.0

#: Non-bonded cutoff and the radius the force switch starts at, nanometres.
CUTOFF_NM = 1.2
SWITCH_NM = 1.0

#: Production temperature and the timestep at it. 2 fs without hydrogen mass repartitioning; see
#: the module docstring for why HMR is not the default.
TEMPERATURE_K = 300.0
TIMESTEP_FS = 2.0
HMR_TIMESTEP_FS = 4.0

#: Langevin friction, per picosecond. 1/ps is the conventional value for a production thermostat:
#: high enough to equilibrate temperature, low enough not to damp the dynamics being measured.
FRICTION_PER_PS = 1.0

#: Equilibration pressure, bar, and how often the barostat attempts a volume move.
PRESSURE_BAR = 1.0
BAROSTAT_INTERVAL = 25

#: Heating and equilibration lengths in picoseconds. Short, and short on purpose: the production
#: run is 15 ns per leg and these are the part that is not measured.
#: Whether a measurement runs at 4 fs with hydrogen-mass repartitioning. **True, and measured:**
#: the same 20 ps of the ALR holo system took 283 s at 2 fs and 154 s at 4 fs + HMR on eight CPU
#: threads (2026-11-24), so 1.83x against a theoretical 2x.
#:
#: It is free for `md_label`'s three labels specifically. HMR moves mass between a heavy atom and
#: its hydrogens and does not touch the potential, so the Boltzmann distribution is unchanged and
#: only kinetics shift -- and `preorg_rmsd`, `ligand_rmsf` and `rotamer_entropy` are all
#: configurational averages. A label that was a *rate* would have to turn it off; none is.
#:
#: The one default. `md_label`'s spec mirrors it and a test asserts the two agree.
DEFAULT_HMR = True

HEAT_PS = 20.0
NPT_PS = 100.0

#: Where a built leg keeps its files.
PRMTOP_NAME = "system.prmtop"
INPCRD_NAME = "system.inpcrd"
EQUILIBRATED_NAME = "equilibrated.pdb"
STATE_NAME = "equilibrated.xml"


class SystemBuildFailed(RuntimeError):
    """A system this module will not hand to a production run, with the reason named."""


@dataclass
class LegPaths:
    """One leg's files and what building it cost."""

    leg: str
    directory: str
    prmtop: str
    inpcrd: str
    n_atoms: int = 0
    n_waters: int = 0
    n_ions: Dict[str, int] = field(default_factory=dict)
    box_nm: List[float] = field(default_factory=list)
    equilibrated_pdb: str = ""
    state_xml: str = ""
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -- building ----------------------------------------------------------------------------


def build_leg(
    *,
    leg: str,
    complex_pdb: str,
    params_dir: str,
    out_dir: str,
    amberhome: str = "",
    padding_nm: float = SOLVENT_PADDING_NM,
) -> LegPaths:
    """Solvate, neutralise and parameterise one leg. **`apo` deletes the ligand first.**

    `complex_pdb` is the design's relaxed complex for both legs; which leg this is decides
    whether the ligand's HETATM records survive into what tleap reads.
    """
    if leg not in LEGS:
        raise SystemBuildFailed(f"unknown leg {leg!r}; the two are {list(LEGS)}")
    artifact = LigandParameters.load(params_dir)
    artifact.verify(params_dir)
    os.makedirs(out_dir, exist_ok=True)

    protein_pdb, ligand_present = _split_complex(
        complex_pdb, out_dir, artifact.pdb_resname or artifact.resname, leg)
    if leg == "holo" and not ligand_present:
        raise SystemBuildFailed(
            f"{complex_pdb} carries no {artifact.pdb_resname or artifact.resname!r} residue, "
            "so there is no holo leg "
            "to build. Pre-organisation is the difference between the pocket with the ligand "
            "and without it; one leg is not a measurement"
        )

    script = _tleap_script(
        leg=leg, protein_pdb=protein_pdb, params_dir=params_dir, artifact=artifact,
        out_dir=out_dir, padding_nm=padding_nm,
    )
    script_path = os.path.join(out_dir, "build.leap")
    with open(script_path, "w") as handle:
        handle.write(script)
    _run_tleap(script_path, out_dir=out_dir, amberhome=amberhome)

    prmtop = os.path.join(out_dir, PRMTOP_NAME)
    inpcrd = os.path.join(out_dir, INPCRD_NAME)
    for path in (prmtop, inpcrd):
        if not os.path.exists(path):
            raise SystemBuildFailed(
                f"tleap returned 0 and wrote no {os.path.basename(path)}. Its log is "
                f"{os.path.join(out_dir, 'leap.log')}; the usual cause is a residue the force "
                "field has no template for, which tleap reports and then continues past"
            )
    counts = _census(prmtop, inpcrd)
    return LegPaths(leg=leg, directory=out_dir, prmtop=prmtop, inpcrd=inpcrd, **counts)


def _split_complex(complex_pdb: str, out_dir: str, resname: str, leg: str) -> tuple:
    """Write what tleap should read for this leg, and say whether the ligand was there.

    The ligand's own coordinates come from K1's committed `mol2`, not from here -- tleap loads
    the parameterised unit and superimposes nothing -- so the holo leg keeps the HETATM records
    only to place it. **The resname is matched exactly**: `A:R` is chosen upstream to defeat CCD
    lookup, and stripping the colon is how a selection stops matching.
    """
    protein: List[str] = []
    ligand: List[str] = []
    for line in open(complex_pdb):
        if line.startswith(("ATOM  ", "HETATM")):
            if line[17:20].strip() == resname[:3] or line[17:21].strip() == resname:
                ligand.append(line)
                continue
            if line[17:20].strip() in _SOLVENT_RESNAMES:
                continue
            protein.append(line)
    protein_path = os.path.join(out_dir, "protein.pdb")
    with open(protein_path, "w") as handle:
        handle.writelines(protein + ["TER\nEND\n"])
    if leg == "holo" and ligand:
        with open(os.path.join(out_dir, "ligand_pose.pdb"), "w") as handle:
            handle.writelines(ligand + ["END\n"])
    return protein_path, bool(ligand)


_SOLVENT_RESNAMES = frozenset({"HOH", "WAT", "DOD", "SOL", "NA", "CL", "K", "MG"})


def _tleap_script(*, leg: str, protein_pdb: str, params_dir: str,
                  artifact: LigandParameters, out_dir: str, padding_nm: float) -> str:
    """The build, as tleap reads it. One script per leg, written out so it is reviewable.

    `addIonsRand` and not `addIons`: the second places ions at the most favourable electrostatic
    sites, which for a **-2 ligand** means putting both sodiums in the pocket. That is a
    starting condition that biases exactly the quantity being measured, and the randomised
    placement is what avoids it.
    """
    # **Absolute, every one of them.** tleap runs with `cwd=out_dir` so that its own scratch
    # lands there, which makes every relative path in the script resolve against the wrong
    # directory -- and tleap's answer to a file it cannot open is `Fatal Error` followed by
    # carrying on to `saveamberparm`, which then writes nothing and exits 0.
    mol2 = os.path.abspath(os.path.join(params_dir, artifact.files["mol2"]))
    frcmod = os.path.abspath(os.path.join(params_dir, artifact.files["frcmod"]))
    protein_pdb = os.path.abspath(protein_pdb)
    out_dir = os.path.abspath(out_dir)
    lines = [
        "source leaprc.protein.ff14SB",
        "source leaprc.gaff2",
        "source leaprc.water.tip3p",
        f"loadamberparams {frcmod}",
    ]
    if leg == "holo":
        lines += [
            f"LIG = loadmol2 {mol2}",
            f"PROT = loadpdb {protein_pdb}",
            "system = combine {PROT LIG}",
        ]
    else:
        # The apo leg: the same protein, and the ligand simply absent. Not a mutation and not a
        # different structure -- the same coordinates, re-solvated into the cavity the ligand
        # left, which is what pre-organisation is measured against.
        lines += [f"system = loadpdb {protein_pdb}"]
    padding_angstrom = padding_nm * 10.0
    lines += [
        f"solvatebox system TIP3PBOX {padding_angstrom:.1f}",
        # Neutralise whatever is left: the protein's own charge plus, in the holo leg, the
        # ligand's -2. Randomised placement; see this function's docstring.
        "addIonsRand system Na+ 0",
        "addIonsRand system Cl- 0",
        f"saveamberparm system {os.path.join(out_dir, PRMTOP_NAME)} "
        f"{os.path.join(out_dir, INPCRD_NAME)}",
        "quit",
        "",
    ]
    return "\n".join(lines)


def _run_tleap(script_path: str, *, out_dir: str, amberhome: str) -> None:
    amberhome = amberhome or os.environ.get("AMBERHOME", "")
    binary = os.path.join(amberhome, "bin", "tleap") if amberhome else ""
    if not (binary and os.path.exists(binary)):
        binary = shutil.which("tleap") or ""
    if not binary:
        raise SystemBuildFailed(
            "tleap is not on PATH and AMBERHOME does not hold it. AmberTools builds both legs "
            "(K2); there is no second path, deliberately -- a system assembled two ways is a "
            "ligand whose parameters exist in two formats"
        )
    env = dict(os.environ)
    if amberhome:
        env["AMBERHOME"] = amberhome
    out = subprocess.run([binary, "-f", os.path.basename(script_path)],
                         cwd=out_dir, env=env, capture_output=True, text=True)
    with open(os.path.join(out_dir, "tleap.log"), "w") as handle:
        handle.write(out.stdout + "\n--- stderr ---\n" + out.stderr)
    # **tleap exits 0 on a fatal error**, which is why the caller checks for the files and why
    # this scans the output: a missing parameter is reported as "FATAL" and then the script
    # continues to `saveamberparm`, which writes nothing.
    if "FATAL" in out.stdout or out.returncode != 0:
        fatal = [line for line in out.stdout.splitlines() if "FATAL" in line or "Error" in line]
        raise SystemBuildFailed(
            f"tleap reported a fatal error (exit {out.returncode}): "
            f"{' | '.join(fatal[:4]) or out.stdout.strip()[-600:]}"
        )


def _census(prmtop: str, inpcrd: str) -> Dict[str, Any]:
    """Atom, water and ion counts, read from the topology OpenMM will read.

    From the prmtop rather than from tleap's log, because the log says what tleap intended and
    the prmtop is what a run will actually integrate.
    """
    from openmm import app  # noqa: PLC0415

    topology = app.AmberPrmtopFile(prmtop).topology
    waters = sum(1 for r in topology.residues() if r.name in ("WAT", "HOH"))
    ions: Dict[str, int] = {}
    for residue in topology.residues():
        if residue.name.strip() in ("Na+", "Cl-", "NA", "CL"):
            ions[residue.name.strip()] = ions.get(residue.name.strip(), 0) + 1
    box = app.AmberInpcrdFile(inpcrd).boxVectors
    box_nm = ([round(box[i][i].value_in_unit_system(_md_unit()), 4) for i in range(3)]
              if box is not None else [])
    return {"n_atoms": topology.getNumAtoms(), "n_waters": waters, "n_ions": ions,
            "box_nm": box_nm}


def _md_unit():
    from openmm import unit  # noqa: PLC0415

    return unit.md_unit_system


# -- equilibrating -----------------------------------------------------------------------


def equilibrate(
    leg: LegPaths,
    *,
    platform: str = "CPU",
    heat_ps: float = HEAT_PS,
    npt_ps: float = NPT_PS,
    hmr: bool = False,
    seed: int = 0,
) -> LegPaths:
    """Minimise, heat, and equilibrate at constant pressure. **The barostat stops here.**

    Production is NVT (K3), and the barostat is the reason: a Monte Carlo barostat changes the
    box volume by rejecting and accepting trial moves, which makes the trajectory
    non-deterministic in a way that has nothing to do with the replicate seed -- and the
    replicate spread is the label's sigma. So the volume is settled under NPT and then held.

    `seed` seeds the initial velocities, which is what makes equilibration itself reproducible;
    K3 reseeds per replica, which is what makes the replicas independent.
    """
    import openmm  # noqa: PLC0415
    from openmm import app, unit  # noqa: PLC0415

    prmtop = app.AmberPrmtopFile(leg.prmtop)
    inpcrd = app.AmberInpcrdFile(leg.inpcrd)
    system = prmtop.createSystem(
        nonbondedMethod=app.PME,
        nonbondedCutoff=CUTOFF_NM * unit.nanometer,
        switchDistance=SWITCH_NM * unit.nanometer,
        constraints=app.HBonds,
        rigidWater=True,
        hydrogenMass=(3.0 * unit.amu if hmr else None),
    )
    timestep = (HMR_TIMESTEP_FS if hmr else TIMESTEP_FS) * unit.femtosecond
    integrator = openmm.LangevinMiddleIntegrator(
        TEMPERATURE_K * unit.kelvin, FRICTION_PER_PS / unit.picosecond, timestep)
    integrator.setRandomNumberSeed(int(seed))
    barostat = openmm.MonteCarloBarostat(
        PRESSURE_BAR * unit.bar, TEMPERATURE_K * unit.kelvin, BAROSTAT_INTERVAL)
    barostat_index = system.addForce(barostat)

    simulation = app.Simulation(
        prmtop.topology, system, integrator,
        openmm.Platform.getPlatformByName(platform))
    simulation.context.setPositions(inpcrd.positions)
    if inpcrd.boxVectors is not None:
        simulation.context.setPeriodicBoxVectors(*inpcrd.boxVectors)

    simulation.minimizeEnergy()
    simulation.context.setVelocitiesToTemperature(TEMPERATURE_K * unit.kelvin, int(seed))
    simulation.step(max(1, int(heat_ps * 1000.0 / (timestep / unit.femtosecond))))
    simulation.step(max(1, int(npt_ps * 1000.0 / (timestep / unit.femtosecond))))

    # The volume is settled; from here it is held. Removed rather than disabled, so a
    # production run cannot re-enable it by setting a parameter.
    system.removeForce(barostat_index)

    state = simulation.context.getState(getPositions=True, getVelocities=True)
    pdb_path = os.path.join(leg.directory, EQUILIBRATED_NAME)
    with open(pdb_path, "w") as handle:
        app.PDBFile.writeFile(simulation.topology, state.getPositions(), handle)
    xml_path = os.path.join(leg.directory, STATE_NAME)
    with open(xml_path, "w") as handle:
        handle.write(openmm.XmlSerializer.serialize(state))

    box = state.getPeriodicBoxVectors()
    leg.equilibrated_pdb = pdb_path
    leg.state_xml = xml_path
    leg.box_nm = [round(box[i][i].value_in_unit(unit.nanometer), 4) for i in range(3)]
    return leg


def build_both_legs(
    *,
    complex_pdb: str,
    params_dir: str,
    out_dir: str,
    amberhome: str = "",
    padding_nm: float = SOLVENT_PADDING_NM,
    platform: str = "CPU",
    heat_ps: float = HEAT_PS,
    npt_ps: float = NPT_PS,
    hmr: bool = False,
    seed: int = 0,
) -> Dict[str, LegPaths]:
    """Both legs, built and equilibrated. `holo`'s equilibrated frame is what ABFE starts from.

    That frame is the second output `md_label`'s ToolSpec declares -- `structure: Complex` --
    and `ABFELabelAgent` refuses for want of *an equilibrated holo frame from md_label*. So it
    is a deliverable rather than an intermediate, and it is why the holo leg is built first.
    """
    out: Dict[str, LegPaths] = {}
    for leg in LEGS:
        built = build_leg(leg=leg, complex_pdb=complex_pdb, params_dir=params_dir,
                          out_dir=os.path.join(out_dir, leg), amberhome=amberhome,
                          padding_nm=padding_nm)
        out[leg] = equilibrate(built, platform=platform, heat_ps=heat_ps, npt_ps=npt_ps,
                               hmr=hmr, seed=seed)
    return out
