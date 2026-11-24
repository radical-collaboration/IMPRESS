"""K3: the randomly initialised ensemble. **`setVelocitiesToTemperature(T, seed)` is it.**

`md_label`'s ToolSpec already declares the ensemble -- `md_replicates`, 1 to 8, documented as
*"the number of MD seeds for one measurement"*, warned apart from the campaign's `replicas`, with
`seed` noted as *"two replicates are only independent if this is honoured"*. It defaults to 1.
This module is what makes a value above 1 mean something, and the mechanism is one call: each
replica draws its initial velocities from the Maxwell-Boltzmann distribution at 300 K with its
own seed, from the same equilibrated positions.

**That is the whole of "randomly initialised", and it is worth being precise about what it buys.**
The replicas share a topology, a box, a force field and a starting structure; they differ only in
the momenta they start with. So the spread between them measures how much of a reported metric is
the trajectory's own chaos rather than the design's property -- which is exactly what
`LabelRecord.sigma` is for, what Model B's heteroscedastic NLL consumes, what Model C's GP takes
as `train_Yvar`, and what replaces `affdelta.py`'s `default_sigma = 0.5` guess.

### Production is NVT, and the barostat is why

A Monte Carlo barostat changes the box by accepting and rejecting trial moves, so it injects
randomness that has nothing to do with the replicate seed. The volume is settled under NPT in K2
and **held** here: the system is rebuilt from the prmtop with no barostat at all, rather than
built with one and disabled, so a production run cannot re-enable it by setting a parameter.

### Checkpoint and resume, because 32400 s is a declared ceiling

`md_label` declares 1 GPU / 16 cores / 32400 s. A run that dies at eight hours with no checkpoint
has spent the budget and bought nothing, so each replica writes one on a fixed interval and
`run_replicate` resumes from it when it finds one. **Resuming restores velocities as well as
positions**, which is what keeps a resumed trajectory the same trajectory rather than a new
replica with the old one's coordinates.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .system import (
    CUTOFF_NM,
    apply_dispersion_correction,
    nonbonded_for,
    FRICTION_PER_PS,
    HMR_TIMESTEP_FS,
    LegPaths,
    SWITCH_NM,
    TEMPERATURE_K,
    TIMESTEP_FS,
)

#: How many replicas a measurement uses when nothing says otherwise. **Three, not one.** One
#: replica reports a number with no uncertainty, and a label with no sigma is the one thing
#: `acquisition.rank` refuses a candidate for; three is the smallest ensemble whose spread is a
#: standard deviation rather than a difference.
DEFAULT_REPLICATES = 3

#: The spec's own ceiling. Above it the cost model stops being the one that was declared.
MAX_REPLICATES = 8

#: Frames per nanosecond written to the trajectory. 100 is 10 ps between frames: fine enough for
#: a sidechain rotamer to be counted in the bin it occupied, coarse enough that 15 ns of a 18k
#: atom system is a file somebody can copy.
FRAMES_PER_NS = 100

#: How often the energy is logged, and how often a checkpoint is written, in picoseconds.
LOG_INTERVAL_PS = 10.0
CHECKPOINT_INTERVAL_PS = 100.0

TRAJECTORY_NAME = "trajectory.dcd"
SCALARS_NAME = "scalars.csv"
CHECKPOINT_NAME = "checkpoint.chk"


class ProductionFailed(RuntimeError):
    """A replica this module will not report, with the reason named."""


@dataclass
class Replicate:
    """One replica's output and what it cost. `seed` is the replica's identity."""

    leg: str
    index: int
    seed: int
    directory: str
    trajectory: str
    scalars: str
    n_frames: int = 0
    ns: float = 0.0
    resumed_from_ps: float = 0.0
    platform: str = ""
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def seed_for(leg: str, index: int, base_seed: int) -> int:
    """A replica's seed: reproducible, and different for every (leg, index, base).

    Derived rather than drawn, for the reason `_replica_seed` gives on the design side: a
    campaign that gave every chain the same seed would collapse N replicas into one. Derived
    *from the leg too*, because the apo and holo replica 0 of one measurement are not the same
    trajectory and must not start from the same momenta.
    """
    mixed = (base_seed * 1_000_003 + index * 10_007 + sum(ord(c) for c in leg) * 101)
    # OpenMM takes a positive 32-bit seed; 0 means "pick one for me", which is the one value
    # that would make a replica unreproducible.
    return (mixed % (2**31 - 2)) + 1


def run_replicate(
    leg: LegPaths,
    *,
    index: int,
    base_seed: int = 0,
    ns: float = 15.0,
    out_dir: str = "",
    platform: str = "CPU",
    hmr: bool = False,
    frames_per_ns: int = FRAMES_PER_NS,
    checkpoint_interval_ps: float = CHECKPOINT_INTERVAL_PS,
) -> Replicate:
    """One replica of one leg, from the equilibrated state, with its own velocities."""
    import openmm  # noqa: PLC0415
    from openmm import app, unit  # noqa: PLC0415

    if not leg.state_xml or not os.path.exists(leg.state_xml):
        raise ProductionFailed(
            f"{leg.leg} has no equilibrated state. Production starts from K2's NPT state, not "
            "from the built coordinates: a replica started from the inpcrd would spend its "
            "first nanosecond equilibrating and report the result as production"
        )
    directory = out_dir or os.path.join(leg.directory, f"rep{index}")
    os.makedirs(directory, exist_ok=True)
    seed = seed_for(leg.leg, index, base_seed)

    # The convention this leg was built under. See `system.NONBONDED`: a production run that
    # used different cutoffs from its own equilibration would be measuring a third system.
    nonbonded = leg.nonbonded or nonbonded_for(
        leg.force_fields.get("protein", "ff14sb"), leg.force_fields.get("ligand", "gaff2"))
    prmtop = app.AmberPrmtopFile(leg.prmtop)
    # **No barostat.** See the module docstring: not added and disabled, not added at all.
    system = prmtop.createSystem(
        nonbondedMethod=app.PME,
        nonbondedCutoff=nonbonded["cutoff_nm"] * unit.nanometer,
        switchDistance=nonbonded["switch_nm"] * unit.nanometer,
        constraints=app.HBonds,
        rigidWater=True,
        hydrogenMass=(3.0 * unit.amu if hmr else None),
    )
    apply_dispersion_correction(system, nonbonded)
    femtoseconds = HMR_TIMESTEP_FS if hmr else TIMESTEP_FS
    integrator = openmm.LangevinMiddleIntegrator(
        TEMPERATURE_K * unit.kelvin, FRICTION_PER_PS / unit.picosecond,
        femtoseconds * unit.femtosecond)
    integrator.setRandomNumberSeed(seed)
    simulation = app.Simulation(prmtop.topology, system, integrator,
                                openmm.Platform.getPlatformByName(platform))

    total_steps = max(1, int(round(ns * 1e6 / femtoseconds)))
    frame_every = max(1, int(round(1e6 / femtoseconds / max(1, frames_per_ns))))
    log_every = max(1, int(round(LOG_INTERVAL_PS * 1000.0 / femtoseconds)))
    check_every = max(1, int(round(checkpoint_interval_ps * 1000.0 / femtoseconds)))

    trajectory = os.path.join(directory, TRAJECTORY_NAME)
    scalars = os.path.join(directory, SCALARS_NAME)
    checkpoint = os.path.join(directory, CHECKPOINT_NAME)

    resumed_ps = 0.0
    if os.path.exists(checkpoint):
        # Positions AND velocities AND the box, which is what makes a resumed trajectory the
        # same trajectory. Restoring positions alone would start a new replica from the old
        # one's coordinates and report it under the old one's seed.
        with open(checkpoint, "rb") as handle:
            simulation.context.loadCheckpoint(handle.read())
        done = simulation.context.getState().getStepCount()
        resumed_ps = done * femtoseconds / 1000.0
        total_steps = max(0, total_steps - done)
    else:
        with open(leg.state_xml) as handle:
            simulation.context.setState(openmm.XmlSerializer.deserialize(handle.read()))
        # **The mechanism.** Same positions for every replica, different momenta, seeded so the
        # replica can be re-run and so two replicas are genuinely independent.
        simulation.context.setVelocitiesToTemperature(TEMPERATURE_K * unit.kelvin, seed)
        simulation.context.setStepCount(0)

    append = resumed_ps > 0.0
    simulation.reporters.append(app.DCDReporter(trajectory, frame_every, append=append))
    simulation.reporters.append(app.StateDataReporter(
        scalars, log_every, step=True, time=True, potentialEnergy=True,
        totalEnergy=True, temperature=True, volume=True, append=append))
    simulation.reporters.append(app.CheckpointReporter(checkpoint, check_every))

    if total_steps:
        simulation.step(total_steps)
    # One last checkpoint, so a run that finished between intervals can still be resumed into
    # an analysis rather than re-run.
    with open(checkpoint, "wb") as handle:
        handle.write(simulation.context.createCheckpoint())

    return Replicate(
        leg=leg.leg, index=index, seed=seed, directory=directory,
        trajectory=trajectory, scalars=scalars,
        n_frames=_frame_count(trajectory), ns=ns, resumed_from_ps=resumed_ps,
        platform=platform,
        notes=("hmr" if hmr else "no-hmr"),
    )


def run_ensemble(
    legs: Dict[str, LegPaths],
    *,
    replicates: int = DEFAULT_REPLICATES,
    base_seed: int = 0,
    ns: float = 15.0,
    platform: str = "CPU",
    hmr: bool = False,
    frames_per_ns: int = FRAMES_PER_NS,
    checkpoint_interval_ps: float = CHECKPOINT_INTERVAL_PS,
) -> Dict[str, List[Replicate]]:
    """`replicates` independent replicas of every leg. **The product is the spread.**"""
    if not 1 <= replicates <= MAX_REPLICATES:
        raise ProductionFailed(
            f"md_replicates={replicates} is outside the spec's 1 to {MAX_REPLICATES}. Above "
            "the ceiling the declared cost model is not the one being spent"
        )
    if replicates < 2:
        # Allowed, because the spec allows it and a smoke test wants it -- and said out loud,
        # because a one-replica measurement has no sigma and `acquisition.rank` refuses a
        # candidate without one.
        pass
    out: Dict[str, List[Replicate]] = {}
    for name, leg in legs.items():
        out[name] = [
            run_replicate(leg, index=i, base_seed=base_seed, ns=ns, platform=platform,
                          hmr=hmr, frames_per_ns=frames_per_ns,
                          checkpoint_interval_ps=checkpoint_interval_ps)
            for i in range(replicates)
        ]
    return out


def _frame_count(trajectory: str) -> int:
    if not os.path.exists(trajectory):
        return 0
    try:
        import mdtraj  # noqa: PLC0415

        return int(len(mdtraj.open(trajectory)))
    except Exception:  # noqa: BLE001 -- a frame count is telemetry, not a result
        return 0


def energy_drift_kcal_per_ns(scalars_csv: str) -> Optional[float]:
    """Total-energy drift, least squares over the log. **Telemetry, not a finding.**

    `md_label`'s integrity gate exists because *an MD run that did not equilibrate is a BROKEN
    INSTRUMENT, not a weak design*, and this is half of what tells the two apart. A Langevin
    thermostat exchanges energy with its bath by construction, so a small drift is expected and
    only a large one means the integrator is losing the system -- which is why this is reported
    beside the metrics rather than gated here, where no measurement has been made yet.

    `None` when the log holds fewer than two points, because a drift over one sample is zero in
    the same way an average over nothing is zero.
    """
    rows = _read_scalars(scalars_csv)
    times = [r for r in rows.get("time", [])]
    energies = rows.get("total", [])
    if len(times) < 2 or len(energies) != len(times):
        return None
    # ps -> ns, kJ/mol -> kcal/mol.
    xs = [t / 1000.0 for t in times]
    ys = [e / 4.184 for e in energies]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0.0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return round(slope, 6)


def _read_scalars(path: str) -> Dict[str, List[float]]:
    """OpenMM's `StateDataReporter` CSV, by what its headers mean rather than by position.

    Its header names carry units and change with the reporter's arguments, so a column read by
    index is a column that silently becomes a different quantity the day somebody logs one more
    thing.
    """
    import csv

    out: Dict[str, List[float]] = {}
    if not os.path.exists(path):
        return out
    with open(path) as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            return out
        names = [h.strip().strip('"#') for h in header]
        wanted = {}
        for i, name in enumerate(names):
            lowered = name.lower()
            if lowered.startswith("time"):
                wanted[i] = "time"
            elif lowered.startswith("total energy"):
                wanted[i] = "total"
            elif lowered.startswith("potential energy"):
                wanted[i] = "potential"
            elif lowered.startswith("temperature"):
                wanted[i] = "temperature"
            elif lowered.startswith("box volume"):
                wanted[i] = "volume"
        for key in wanted.values():
            out.setdefault(key, [])
        for row in reader:
            for i, key in wanted.items():
                if i < len(row):
                    try:
                        out[key].append(float(row[i]))
                    except ValueError:
                        pass
    return out


def spread(values: List[float]) -> Dict[str, Optional[float]]:
    """Mean and **sample** standard deviation over the replicas. The label's value and sigma.

    Sample and not population: the replicas are a sample of the trajectories this design could
    have produced, and the population formula would report a sigma smaller than the evidence
    supports -- at three replicas, by a factor of 0.82.

    `sigma` is `None` for a single replica rather than 0.0. A zero sigma says *measured, with no
    uncertainty*, which no MD measurement ever is, and `acquisition.rank` would then rank on it.
    """
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return {"value": None, "sigma": None, "n": 0}
    mean = sum(clean) / len(clean)
    if len(clean) < 2:
        return {"value": mean, "sigma": None, "n": len(clean)}
    variance = sum((v - mean) ** 2 for v in clean) / (len(clean) - 1)
    return {"value": mean, "sigma": math.sqrt(variance), "n": len(clean)}
