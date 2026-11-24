"""K4: the three metrics, the convergence telemetry, and **the sigma that is the point**.

`md_label` measures three quantities and reports two more. The three are the labels Model B
regresses on; the two are how anyone knows whether the instrument worked.

| Metric | What it is |
|---|---|
| `preorg_rmsd` | pocket Ca RMSD, the **apo** ensemble against the **holo** one |
| `rotamer_entropy` | Shannon entropy over rotamer-bin occupancy of the pocket's sidechain chi dihedrals |
| `ligand_rmsf` | per-atom fluctuation of the ligand after aligning on the pocket |
| `rmsd_plateau_frac` | telemetry: the fraction of the run after the RMSD stopped rising |
| `energy_drift_kcal_per_ns` | telemetry: see `ensemble.energy_drift_kcal_per_ns` |

**The two telemetry numbers say whether the instrument worked, not what it found**, which is why
they are reported separately and why `metric_in_range(rmsd_plateau_frac, min 0.5)` is an
*integrity* gate: a run that never plateaued has measured the approach to equilibrium, and
reporting that as a design's pre-organisation would make a slow equilibration look like a bad
pocket.

### The pocket is resolved on the design complex, by Model B's own rule, and both halves matter

`asteer.features_impl.pocket_geom.resolve_pocket` is imported here rather than re-implemented.
Model B *predicts* `preorg_rmsd` from nine columns computed over a pocket, and this *measures*
`preorg_rmsd` over a pocket; if the two are different residue sets then the label and the
prediction are about different things, which is item 54's failure with physics on top of it.

**And it is resolved on the design complex -- the structure Model B scored -- not on the
equilibrated frame.** That distinction was measured rather than assumed, and the numbers say it
matters: on the ALR complex the design pocket is **18 residues** and the same rule applied to the
equilibrated holo frame gives **20**, differing by six labels in both directions. Nothing is
wrong with either; the structure moved during minimisation and equilibration, so residues sitting
near the 5.0 A boundary crossed it. But only one of those two sets is the one Model B's featuriser
saw, so only one of them makes the label and the prediction commensurable.

What has to be true for that to work is that **the protein numbering survives the build**, and it
does: tleap keeps chain A residues 1-147 exactly as the design complex had them, and only the
ligand is renumbered (`B 386 A:R` becomes `A 148 ALR`). A test asserts it, because if tleap ever
renumbered the protein the residue labels would still *look* fine and would select different
atoms.

**One pocket for both legs.** The apo leg has no ligand, so its own contact shell is empty; and
even if it were not, a pocket defined per leg would make `preorg_rmsd` an RMSD between two
different residue selections.

### Why the apo-against-holo RMSD is a mean over pairs

Pre-organisation is *how far the unbound pocket sits from the bound one*, so the quantity is a
distance between two ensembles rather than a fluctuation within one. Every apo frame is compared
to the holo ensemble's mean pocket, after a rigid-body fit on that same pocket -- so what is
left is the shape difference, not the fact that two trajectories drifted to different corners of
the box.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

#: Rotamer bins, degrees. Three for chi1 and chi2 -- gauche+, trans, gauche- -- which is the
#: conventional coarse-graining and the one a 15 ns run can actually populate. A finer binning
#: would report an entropy that mostly measures how few frames landed in each bin.
ROTAMER_BINS = ((0.0, 120.0), (120.0, 240.0), (240.0, 360.0))

#: Which sidechain dihedrals are counted. chi1 and chi2 only: chi3 and beyond are poorly
#: sampled in 15 ns and their entropy is mostly noise.
CHI_ANGLES = ("chi1", "chi2")

#: The fraction of a trajectory treated as approach-to-equilibrium when looking for a plateau.
#: The plateau test compares the second half's mean to the last quarter's.
PLATEAU_TAIL = 0.25


class AnalysisFailed(RuntimeError):
    """A trajectory this module will not turn into a metric, with the reason named."""


@dataclass
class Measurement:
    """One metric over an ensemble: its value, its sigma, and what it came from."""

    name: str
    value: Optional[float] = None
    sigma: Optional[float] = None
    unit: str = ""
    n_replicates: int = 0
    per_replicate: List[Optional[float]] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_pocket_residues(topology_pdb: str, ligand_resname: str) -> List[str]:
    """The pocket, **by Model B's own rule**. Returns residue labels like `A64`.

    The ligand is named explicitly rather than inferred from the HETATM flag, because a
    solvated system carries sodium and chloride too and an ion is not a ligand.

    **The name to pass is the one in the structure being read**, and after a tleap build that
    is the parameter unit's name (`ALR`) rather than the design complex's (`A:R`) -- mol2 and
    tleap cannot carry a colon. The two names are both on K1's artifact for exactly this
    reason, and `resolve_pocket` gained an explicit `ligand_resname` because its colon
    inference could not express the second one at all.

    What has to be true for the label and the prediction to be about the same residues is that
    **the protein numbering survives the build**, and it does: tleap keeps chain A residues
    1-147 as they were, and a test asserts the two pockets are the same set.
    """
    import numpy as np  # noqa: PLC0415
    from asteer.features_impl import pocket_geom, structure_io  # noqa: PLC0415

    parsed = structure_io.read_structure(topology_pdb)
    atoms = parsed.atoms
    if not atoms:
        raise AnalysisFailed(f"{topology_pdb} parsed to no heavy atom")
    topology = pocket_geom.Topology(
        atom_names=tuple(a.name for a in atoms),
        resnames=tuple(a.resname for a in atoms),
        chains=tuple(a.chain for a in atoms),
        resnums=tuple(a.resnum for a in atoms),
        elements=tuple(a.element for a in atoms),
        icodes=tuple(a.icode for a in atoms),
        het=tuple(a.het for a in atoms),
    )
    coords = np.array([(a.x, a.y, a.z) for a in atoms], dtype=float)
    pocket = pocket_geom.resolve_pocket("", topology, coords, ligand_resname=ligand_resname)
    if len(pocket.residues) < 3:
        raise AnalysisFailed(
            f"{topology_pdb} resolves to {len(pocket.residues)} pocket residues around "
            f"{ligand_resname!r}. An RMSD over two residues is a distance, not a shape"
        )
    return list(pocket.residues)


def _select_pocket_ca(traj: Any, residues: Sequence[str]) -> List[int]:
    """Indices of the pocket residues' alpha carbons in an MDTraj topology.

    Matched on `chain-id + resSeq`, which is what `resolve_pocket` returns, rather than on
    MDTraj's own residue index -- the solvated topology has thousands of waters after the
    protein and its indices are nothing like the input PDB's.
    """
    wanted = set(residues)
    out: List[int] = []
    for atom in traj.topology.atoms:
        if atom.name != "CA":
            continue
        chain = chr(ord("A") + atom.residue.chain.index)
        if f"{chain}{atom.residue.resSeq}" in wanted:
            out.append(atom.index)
    return out


def _load(trajectory: str, topology_pdb: str) -> Any:
    import mdtraj  # noqa: PLC0415

    if not os.path.exists(trajectory):
        raise AnalysisFailed(f"no trajectory at {trajectory}")
    traj = mdtraj.load(trajectory, top=topology_pdb)
    if traj.n_frames < 2:
        raise AnalysisFailed(
            f"{trajectory} holds {traj.n_frames} frame(s). Every metric here is a statistic "
            "over frames, and one frame makes all of them zero"
        )
    return traj


# -- the three metrics -------------------------------------------------------------------


def preorg_rmsd(
    *, apo: Sequence[tuple], holo: Sequence[tuple], residues: Sequence[str],
) -> Measurement:
    """Pocket Ca RMSD of the apo ensemble against the holo ensemble's mean pocket.

    **One value per apo replica**, so the spread across them is the sigma. The holo reference is
    the mean over every holo frame of every holo replica: the bound pocket is one shape, and
    using a single holo replica would put that replica's own noise into the label.
    """
    import numpy as np  # noqa: PLC0415

    reference = _mean_pocket(holo, residues)
    per: List[Optional[float]] = []
    for path, topology_pdb in apo:
        traj = _load(path, topology_pdb)
        idx = _select_pocket_ca(traj, residues)
        if len(idx) < 3:
            per.append(None)
            continue
        frames = traj.xyz[:, idx, :] * 10.0  # nm -> angstrom
        per.append(float(np.mean([_fitted_rmsd(f, reference) for f in frames])))
    return _measure("preorg_rmsd", per, "angstrom")


def _mean_pocket(runs: Sequence[tuple], residues: Sequence[str]) -> Any:
    import numpy as np  # noqa: PLC0415

    stack = []
    for path, topology_pdb in runs:
        traj = _load(path, topology_pdb)
        idx = _select_pocket_ca(traj, residues)
        if len(idx) < 3:
            continue
        stack.append(traj.xyz[:, idx, :] * 10.0)
    if not stack:
        raise AnalysisFailed(
            "no holo replica yielded a pocket, so there is nothing to measure the apo "
            "ensemble against"
        )
    frames = np.concatenate(stack, axis=0)
    # Superpose every frame on the first before averaging: a mean over frames in different
    # orientations is a blur rather than a shape.
    first = frames[0]
    fitted = np.stack([_superpose(f, first) for f in frames], axis=0)
    return fitted.mean(axis=0)


def _superpose(mobile: Any, reference: Any) -> Any:
    """Kabsch: the rigid-body fit, so what is left is shape rather than placement."""
    import numpy as np  # noqa: PLC0415

    m = mobile - mobile.mean(axis=0)
    r = reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(m.T @ r)
    d = np.sign(np.linalg.det(u @ vt))
    rotation = u @ np.diag([1.0, 1.0, d]) @ vt
    return (m @ rotation) + reference.mean(axis=0)


def _fitted_rmsd(mobile: Any, reference: Any) -> float:
    import numpy as np  # noqa: PLC0415

    fitted = _superpose(mobile, reference)
    diff = fitted - reference
    return float(np.sqrt((diff * diff).sum(axis=1).mean()))


def rotamer_entropy(*, runs: Sequence[tuple], residues: Sequence[str]) -> Measurement:
    """Shannon entropy over rotamer-bin occupancy, averaged over the pocket's sidechains.

    In **nats**, and per residue: the sum over a pocket would make a bigger pocket look more
    flexible, which is a property of the selection rather than of the design. The maximum is
    `ln 3` per chi angle, reached when a sidechain visits all three bins equally.
    """
    import mdtraj  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    per: List[Optional[float]] = []
    wanted = set(residues)
    for path, topology_pdb in runs:
        traj = _load(path, topology_pdb)
        entropies: List[float] = []
        for chi in CHI_ANGLES:
            compute = getattr(mdtraj, f"compute_{chi}", None)
            if compute is None:  # pragma: no cover -- mdtraj always has chi1 and chi2
                continue
            indices, angles = compute(traj)
            if angles.size == 0:
                continue
            degrees = np.degrees(angles) % 360.0
            for column, atoms in enumerate(indices):
                residue = traj.topology.atom(int(atoms[0])).residue
                chain = chr(ord("A") + residue.chain.index)
                if f"{chain}{residue.resSeq}" not in wanted:
                    continue
                counts = [
                    int(np.sum((degrees[:, column] >= lo) & (degrees[:, column] < hi)))
                    for lo, hi in ROTAMER_BINS
                ]
                total = sum(counts)
                if total == 0:
                    continue
                entropies.append(-sum((c / total) * math.log(c / total)
                                      for c in counts if c))
        per.append(float(np.mean(entropies)) if entropies else None)
    return _measure("rotamer_entropy", per, "nat")


def ligand_rmsf(
    *, runs: Sequence[tuple], residues: Sequence[str], ligand_resname: str,
) -> Measurement:
    """Per-atom fluctuation of the ligand, **after aligning on the pocket**.

    On the pocket and not on the ligand: aligning on the ligand measures its internal
    flexibility and throws away how much it moves inside the site, which is the part that says
    whether it is held. Aligning on nothing measures the box.
    """
    import numpy as np  # noqa: PLC0415

    per: List[Optional[float]] = []
    for path, topology_pdb in runs:
        traj = _load(path, topology_pdb)
        pocket_idx = _select_pocket_ca(traj, residues)
        ligand_idx = [a.index for a in traj.topology.atoms
                      if a.residue.name.strip() in (ligand_resname, ligand_resname[:3])
                      and a.element.symbol != "H"]
        if len(pocket_idx) < 3 or not ligand_idx:
            per.append(None)
            continue
        pocket = traj.xyz[:, pocket_idx, :] * 10.0
        ligand = traj.xyz[:, ligand_idx, :] * 10.0
        reference = pocket[0]
        aligned = []
        for frame in range(traj.n_frames):
            shifted = _align_other(pocket[frame], reference, ligand[frame])
            aligned.append(shifted)
        stacked = np.stack(aligned, axis=0)
        mean = stacked.mean(axis=0)
        fluct = np.sqrt(((stacked - mean) ** 2).sum(axis=2).mean(axis=0))
        per.append(float(fluct.mean()))
    return _measure("ligand_rmsf", per, "angstrom")


def _align_other(mobile: Any, reference: Any, carried: Any) -> Any:
    """Fit `mobile` onto `reference` and apply the same transform to `carried`."""
    import numpy as np  # noqa: PLC0415

    centre = mobile.mean(axis=0)
    m = mobile - centre
    r = reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(m.T @ r)
    d = np.sign(np.linalg.det(u @ vt))
    rotation = u @ np.diag([1.0, 1.0, d]) @ vt
    return ((carried - centre) @ rotation) + reference.mean(axis=0)


# -- telemetry ---------------------------------------------------------------------------


def rmsd_plateau_frac(*, runs: Sequence[tuple], residues: Sequence[str]) -> Measurement:
    """The fraction of the run after the pocket RMSD stopped rising. **Integrity, not quality.**

    Computed against the run's own first frame, walking forward to the first frame after which
    the RMSD never again exceeds the tail's mean by more than the tail's own spread. A run that
    never settles returns a small fraction, and `md_label`'s gate refuses it at 0.5 -- because
    *an MD run that did not equilibrate is a BROKEN INSTRUMENT, not a weak design*.
    """
    import numpy as np  # noqa: PLC0415

    per: List[Optional[float]] = []
    for path, topology_pdb in runs:
        traj = _load(path, topology_pdb)
        idx = _select_pocket_ca(traj, residues)
        if len(idx) < 3:
            per.append(None)
            continue
        frames = traj.xyz[:, idx, :] * 10.0
        series = np.array([_fitted_rmsd(f, frames[0]) for f in frames])
        tail_start = max(1, int(len(series) * (1.0 - PLATEAU_TAIL)))
        tail = series[tail_start:]
        ceiling = float(tail.mean() + (tail.std() or 1e-9))
        # The last index that exceeded the ceiling; everything after it is the plateau.
        above = np.flatnonzero(series > ceiling)
        last = int(above[-1]) if above.size else -1
        per.append(float((len(series) - 1 - last) / len(series)))
    return _measure("rmsd_plateau_frac", per, "fraction")


def _measure(name: str, per: List[Optional[float]], unit: str) -> Measurement:
    from .ensemble import spread  # noqa: PLC0415

    stats = spread([v for v in per if v is not None])
    reason = ""
    if stats["n"] == 0:
        reason = "no replica yielded a value"
    elif stats["sigma"] is None:
        reason = (f"{stats['n']} replica: a spread needs two, and a label with no sigma is "
                  "what `acquisition.rank` refuses a candidate for")
    return Measurement(name=name, value=stats["value"], sigma=stats["sigma"], unit=unit,
                       n_replicates=len([v for v in per if v is not None]),
                       per_replicate=list(per), reason=reason)


def measure_all(
    *,
    legs: Dict[str, Any],
    replicates: Dict[str, List[Any]],
    complex_pdb: str,
    design_ligand_resname: str,
    ligand_resname: str,
) -> Dict[str, Measurement]:
    """Every metric `md_label` reports, over one measurement's ensemble.

    The pocket is resolved **once**, on the holo leg's equilibrated frame, and reused for both
    legs -- see the module docstring. A pocket resolved per leg would make `preorg_rmsd` an RMSD
    between two different residue selections, and the apo leg has no ligand to resolve one
    around anyway.
    """
    holo, apo = legs["holo"], legs["apo"]
    # **On the design complex, with the design's own ligand name.** See the module docstring:
    # the same rule on the equilibrated frame gives a different residue set, and only this one
    # is the set Model B's featuriser scored.
    residues = resolve_pocket_residues(complex_pdb, design_ligand_resname)
    # **(trajectory, topology) pairs, per leg.** The two legs have different atom counts --
    # the apo one is the holo one minus the ligand plus the water that filled the cavity -- so
    # a shared topology is not merely untidy: MDTraj refuses it, and a topology that happened
    # to have the right count would silently select the wrong atoms.
    holo_runs = [(r.trajectory, holo.equilibrated_pdb) for r in replicates["holo"]]
    apo_runs = [(r.trajectory, apo.equilibrated_pdb) for r in replicates["apo"]]

    from .ensemble import energy_drift_kcal_per_ns  # noqa: PLC0415

    drifts = [energy_drift_kcal_per_ns(r.scalars)
              for r in replicates["holo"] + replicates["apo"]]
    out = {
        "preorg_rmsd": preorg_rmsd(apo=apo_runs, holo=holo_runs, residues=residues),
        # Measured on the HOLO leg: the entropy that matters is the bound pocket's, because
        # that is the state the design is for. The apo leg's is a different quantity and is not
        # one of `md_label`'s metrics.
        "rotamer_entropy": rotamer_entropy(runs=holo_runs, residues=residues),
        "ligand_rmsf": ligand_rmsf(runs=holo_runs, residues=residues,
                                   ligand_resname=ligand_resname),
        "rmsd_plateau_frac": rmsd_plateau_frac(runs=holo_runs + apo_runs, residues=residues),
        "energy_drift_kcal_per_ns": _measure(
            "energy_drift_kcal_per_ns", list(drifts), "kcal/mol/ns"),
    }
    out["pocket_residues"] = Measurement(
        name="pocket_residues", value=float(len(residues)), unit="count",
        n_replicates=0,
        reason=("resolved on the design complex by Model B's own rule, so the label and the "
                "prediction are about the same residues"))
    return out
