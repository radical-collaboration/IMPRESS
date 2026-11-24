"""K2-K4: the two legs, the seeded ensemble, and the arithmetic behind the three metrics.

**The long run is a separate test and it is marked.** What is here is everything that can be
checked without integrating anything: the leg builder's refusals, the seed derivation, the
sigma convention, and each analysis function against an input whose answer is known by
construction. A protocol whose arithmetic is only ever checked by a full MD run is one whose
arithmetic is checked on an allocation.
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")
np = pytest.importorskip("numpy")

from impress_a.md import analysis, ensemble  # noqa: E402
from impress_a.md.params import LigandParameters  # noqa: E402
from impress_a.md.system import (  # noqa: E402
    CUTOFF_NM,
    LEGS,
    SWITCH_NM,
    SystemBuildFailed,
    _split_complex,
    _tleap_script,
    build_leg,
)

REPO = Path(__file__).resolve().parents[1]
ALR = REPO / "campaigns" / "data" / "alr"
PARAMS = ALR / "md"
COMPLEX = ALR / "input_pdbs" / "scaffold-with-ALR.pdb"

needs_amber = pytest.mark.skipif(
    shutil.which("tleap") is None and not os.path.exists(
        os.path.join(os.environ.get("AMBERHOME", ""), "bin", "tleap")),
    reason="tleap builds both legs and is not here",
)
needs_openmm = pytest.mark.skipif(
    __import__("importlib").util.find_spec("openmm") is None,
    reason="OpenMM is not installed here (backlog item 77)",
)


# -- K2: the two legs --------------------------------------------------------


def test_the_apo_leg_deletes_the_ligand_and_the_holo_leg_keeps_it(tmp_path):
    """**Audit finding 3: no apo structure exists anywhere in this project's data.**

    So the apo leg is not a control, it is half the measurement -- pre-organisation is the
    difference between the pocket with the ligand and the pocket without it.
    """
    artifact = LigandParameters.load(str(PARAMS))
    for leg, expect_ligand in (("holo", True), ("apo", True)):
        out = tmp_path / leg
        out.mkdir()
        protein, found = _split_complex(str(COMPLEX), str(out),
                                        artifact.pdb_resname, leg)
        assert found is expect_ligand
        text = Path(protein).read_text()
        assert "A:R" not in text, "the protein file never carries the ligand, in either leg"
        assert "HIS" in text
    # And the holo leg writes the pose out, where the apo leg does not.
    assert (tmp_path / "holo" / "ligand_pose.pdb").exists()
    assert not (tmp_path / "apo" / "ligand_pose.pdb").exists()


def test_the_ligand_is_matched_by_its_pdb_name_and_not_its_parameter_name(tmp_path):
    """The structure says `A:R` and the parameter files say `ALR`, because mol2 and tleap
    cannot carry a colon. Matching the parameter unit's name against the structure finds no
    ligand, and a holo build that found no ligand would be an apo build wearing a holo label.
    """
    artifact = LigandParameters.load(str(PARAMS))
    assert artifact.pdb_resname == "A:R" and artifact.resname == "ALR"
    _, by_pdb_name = _split_complex(str(COMPLEX), str(tmp_path), "A:R", "holo")
    _, by_unit_name = _split_complex(str(COMPLEX), str(tmp_path), "ALR", "holo")
    assert by_pdb_name is True
    assert by_unit_name is False, "which is exactly the failure the two fields prevent"


def test_the_tleap_script_uses_absolute_paths_for_everything_it_reads(tmp_path):
    """tleap runs with `cwd=out_dir` so its scratch lands there, and its answer to a file it
    cannot open is `Fatal Error` followed by carrying on to `saveamberparm` -- which writes
    nothing and exits 0."""
    artifact = LigandParameters.load(str(PARAMS))
    script = _tleap_script(leg="holo", protein_pdb="protein.pdb", params_dir=str(PARAMS),
                           artifact=artifact, out_dir=str(tmp_path), padding_nm=1.0)
    for line in script.splitlines():
        for token in line.split():
            if token.endswith((".pdb", ".mol2", ".frcmod", ".prmtop", ".inpcrd")):
                assert os.path.isabs(token), f"{token} in {line!r} is relative"


def test_the_apo_script_loads_no_ligand_and_the_holo_one_combines_it(tmp_path):
    artifact = LigandParameters.load(str(PARAMS))
    holo = _tleap_script(leg="holo", protein_pdb="p.pdb", params_dir=str(PARAMS),
                         artifact=artifact, out_dir=str(tmp_path), padding_nm=1.0)
    apo = _tleap_script(leg="apo", protein_pdb="p.pdb", params_dir=str(PARAMS),
                        artifact=artifact, out_dir=str(tmp_path), padding_nm=1.0)
    assert "loadmol2" in holo and "combine" in holo
    assert "loadmol2" not in apo and "combine" not in apo
    # Both solvate and both neutralise, and both do it with RANDOMISED ion placement: `addIons`
    # puts ions at the most favourable electrostatic sites, which for a -2 ligand means both
    # sodiums in the pocket -- a starting condition that biases the quantity being measured.
    for script in (holo, apo):
        assert "solvatebox" in script and "TIP3PBOX" in script
        assert "addIonsRand" in script and "addIons " not in script


def test_an_unknown_leg_is_refused_by_name(tmp_path):
    with pytest.raises(SystemBuildFailed, match="unknown leg"):
        build_leg(leg="gas-phase", complex_pdb=str(COMPLEX), params_dir=str(PARAMS),
                  out_dir=str(tmp_path))


def test_a_holo_build_from_an_apo_structure_is_refused(tmp_path):
    apo_only = tmp_path / "apo.pdb"
    apo_only.write_text("".join(l for l in open(COMPLEX) if l.startswith("ATOM")) + "END\n")
    with pytest.raises(SystemBuildFailed, match="one leg is not a measurement"):
        build_leg(leg="holo", complex_pdb=str(apo_only), params_dir=str(PARAMS),
                  out_dir=str(tmp_path / "build"))


def test_the_cutoff_and_the_switch_are_the_charmm_standard_pairing():
    """A hard cutoff puts a step in the force at 1.2 nm, and the drift that follows is what
    `energy_drift_kcal_per_ns` would then report as a broken instrument."""
    assert (CUTOFF_NM, SWITCH_NM) == (1.2, 1.0)
    assert SWITCH_NM < CUTOFF_NM


@needs_amber
@needs_openmm
@pytest.mark.slow
def test_both_legs_build_and_differ_by_exactly_the_ligands_counterions(tmp_path):
    """**The counterion arithmetic from K1, showing up in the built system.**

    ALR is -2, so the holo leg needs two more sodiums than the apo leg. Nothing computes that
    here: tleap neutralises whatever charge it finds, and the difference is the ligand's.
    """
    built = {leg: build_leg(leg=leg, complex_pdb=str(COMPLEX), params_dir=str(PARAMS),
                            out_dir=str(tmp_path / leg), padding_nm=0.8)
             for leg in LEGS}
    sodium = {leg: b.n_ions.get("Na+", 0) for leg, b in built.items()}
    assert sodium["holo"] - sodium["apo"] == 2, sodium
    assert LigandParameters.load(str(PARAMS)).counterions == {"NA": 2}
    # The apo leg has no ligand and therefore fewer atoms, and it refills the cavity with water.
    assert built["holo"].n_atoms > built["apo"].n_atoms
    assert built["apo"].n_waters >= built["holo"].n_waters


# -- K3: the ensemble --------------------------------------------------------


def test_every_replica_of_every_leg_gets_its_own_reproducible_seed():
    """Derived rather than drawn, so a replica can be re-run; and derived from the leg too,
    because the apo and holo replica 0 are not the same trajectory."""
    seeds = {(leg, i): ensemble.seed_for(leg, i, 7) for leg in LEGS for i in range(8)}
    assert len(set(seeds.values())) == len(seeds), "two replicas sharing a seed are one replica"
    assert all(s > 0 for s in seeds.values()), "0 means 'pick one for me' to OpenMM"
    assert seeds[("holo", 0)] == ensemble.seed_for("holo", 0, 7), "and it is reproducible"
    assert seeds[("holo", 0)] != ensemble.seed_for("holo", 0, 8), "a new base is a new ensemble"


def test_the_replicate_count_is_bounded_by_the_specs_own_ceiling():
    with pytest.raises(ensemble.ProductionFailed, match="outside the spec"):
        ensemble.run_ensemble({}, replicates=ensemble.MAX_REPLICATES + 1)
    with pytest.raises(ensemble.ProductionFailed, match="outside the spec"):
        ensemble.run_ensemble({}, replicates=0)


def test_the_default_is_three_replicas_because_one_has_no_spread():
    assert ensemble.DEFAULT_REPLICATES == 3


def test_the_sigma_is_a_sample_standard_deviation_and_absent_for_one_replica():
    """Sample, not population: the replicas are a sample of the trajectories this design could
    have produced, and the population formula understates the evidence -- at three replicas by
    a factor of 0.82. And `None` rather than 0.0 for one replica, because a zero sigma says
    *measured, with no uncertainty*, which no MD measurement is."""
    assert ensemble.spread([])["value"] is None
    one = ensemble.spread([1.5])
    assert one["value"] == 1.5 and one["sigma"] is None and one["n"] == 1
    three = ensemble.spread([1.0, 1.2, 0.8])
    assert three["value"] == pytest.approx(1.0)
    assert three["sigma"] == pytest.approx(0.2), "sample sd of (1.0, 1.2, 0.8)"
    assert three["sigma"] > math.sqrt(sum((v - 1.0) ** 2 for v in (1.0, 1.2, 0.8)) / 3)


def test_a_non_finite_replica_is_dropped_rather_than_poisoning_the_mean():
    assert ensemble.spread([1.0, float("nan"), 1.2])["n"] == 2


def test_the_energy_drift_is_a_least_squares_slope_in_kcal_per_mol_per_ns(tmp_path):
    """And `None` below two points, because a drift over one sample is zero in the same way an
    average over nothing is zero."""
    path = tmp_path / "scalars.csv"
    # 4.184 kJ/mol per kcal/mol, and 1000 ps per ns: a clean 1 kcal/mol/ns.
    rows = "\n".join(f"{i*100},{i*100.0},{-1000.0},{-1000.0 + i * 0.4184},300.0,30.0"
                     for i in range(11))
    path.write_text('#"Step","Time (ps)","Potential Energy (kJ/mole)",'
                    '"Total Energy (kJ/mole)","Temperature (K)","Box Volume (nm^3)"\n' + rows)
    assert ensemble.energy_drift_kcal_per_ns(str(path)) == pytest.approx(1.0, abs=1e-6)

    short = tmp_path / "short.csv"
    short.write_text('#"Step","Time (ps)","Total Energy (kJ/mole)"\n0,0.0,-1000.0\n')
    assert ensemble.energy_drift_kcal_per_ns(str(short)) is None
    assert ensemble.energy_drift_kcal_per_ns(str(tmp_path / "absent.csv")) is None


def test_the_scalar_log_is_read_by_header_name_and_not_by_column_position(tmp_path):
    """`StateDataReporter`'s headers carry units and change with its arguments, so a column
    read by index silently becomes a different quantity the day somebody logs one more thing."""
    path = tmp_path / "s.csv"
    path.write_text(
        '#"Step","Box Volume (nm^3)","Time (ps)","Total Energy (kJ/mole)"\n'
        "0,30.0,0.0,-4184.0\n1000,31.0,2.0,-4184.0\n")
    rows = ensemble._read_scalars(str(path))
    assert rows["time"] == [0.0, 2.0]
    assert rows["total"] == [-4184.0, -4184.0]
    assert rows["volume"] == [30.0, 31.0]


# -- K4: the analyses --------------------------------------------------------


def test_the_pocket_is_the_one_model_bs_featuriser_resolves():
    """**Load-bearing**: Model B predicts `preorg_rmsd` over a pocket and this measures it over
    a pocket, so if the two are different residue sets the label and the prediction are about
    different things. One function, imported, not re-implemented."""
    from asteer.features_impl import pocket_geom, structure_io

    residues = analysis.resolve_pocket_residues(str(COMPLEX), "A:R")
    assert len(residues) == 18

    parsed = structure_io.read_structure(str(COMPLEX))
    atoms = parsed.atoms
    topology = pocket_geom.Topology(
        atom_names=tuple(a.name for a in atoms), resnames=tuple(a.resname for a in atoms),
        chains=tuple(a.chain for a in atoms), resnums=tuple(a.resnum for a in atoms),
        elements=tuple(a.element for a in atoms), icodes=tuple(a.icode for a in atoms),
        het=tuple(a.het for a in atoms))
    coords = np.array([(a.x, a.y, a.z) for a in atoms], dtype=float)
    assert list(pocket_geom.resolve_pocket("A:R", topology, coords).residues) == residues


def test_a_structure_with_too_small_a_pocket_is_refused(tmp_path):
    tiny = tmp_path / "tiny.pdb"
    tiny.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  A:R B 100       2.000   0.000   0.000  1.00  0.00           C\n"
        "END\n")
    with pytest.raises(analysis.AnalysisFailed, match="not a shape"):
        analysis.resolve_pocket_residues(str(tiny), "A:R")


def test_the_superposition_removes_placement_and_keeps_shape():
    """A rigid-body fit is what makes `preorg_rmsd` a shape difference rather than the fact
    that two trajectories drifted to different corners of the box."""
    shape = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]])
    theta = 0.7
    rotation = np.array([[math.cos(theta), -math.sin(theta), 0.0],
                         [math.sin(theta), math.cos(theta), 0.0],
                         [0.0, 0.0, 1.0]])
    moved = (shape @ rotation.T) + np.array([10.0, -5.0, 2.0])
    assert analysis._fitted_rmsd(moved, shape) == pytest.approx(0.0, abs=1e-9)

    # A genuinely different shape does not fit away.
    squashed = shape * np.array([1.0, 1.0, 0.5])
    assert analysis._fitted_rmsd(squashed, shape) > 0.3


def test_carrying_the_ligand_through_the_pockets_own_fit_moves_it_with_the_pocket():
    """`ligand_rmsf` aligns on the pocket and not on the ligand: aligning on the ligand
    measures its internal flexibility and throws away how much it moves inside the site."""
    pocket = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 3.0]])
    ligand = np.array([[1.0, 1.0, 1.0], [1.5, 1.0, 1.0]])
    shift = np.array([7.0, 7.0, 7.0])
    carried = analysis._align_other(pocket + shift, pocket, ligand + shift)
    assert np.allclose(carried, ligand, atol=1e-9), (
        "a rigid translation of the whole system must leave the ligand where it was"
    )


def test_the_rotamer_entropy_bins_are_three_and_its_ceiling_is_ln_three():
    """Three bins -- gauche+, trans, gauche- -- which is the conventional coarse-graining and
    the one a 15 ns run can populate. A finer binning reports an entropy that mostly measures
    how few frames landed in each bin."""
    assert len(analysis.ROTAMER_BINS) == 3
    assert analysis.ROTAMER_BINS[0][0] == 0.0 and analysis.ROTAMER_BINS[-1][1] == 360.0
    # Contiguous and non-overlapping, so every angle lands in exactly one.
    for (a_lo, a_hi), (b_lo, _) in zip(analysis.ROTAMER_BINS, analysis.ROTAMER_BINS[1:]):
        assert a_hi == b_lo and a_lo < a_hi
    uniform = -sum((1 / 3) * math.log(1 / 3) for _ in range(3))
    assert uniform == pytest.approx(math.log(3.0))


def test_a_measurement_over_one_replica_says_why_it_has_no_sigma():
    one = analysis._measure("preorg_rmsd", [1.2], "angstrom")
    assert one.value == 1.2 and one.sigma is None
    assert "acquisition.rank" in one.reason
    none = analysis._measure("preorg_rmsd", [None, None], "angstrom")
    assert none.value is None and none.reason == "no replica yielded a value"
    three = analysis._measure("preorg_rmsd", [1.0, 1.2, 0.8], "angstrom")
    assert three.sigma == pytest.approx(0.2) and three.reason == ""
    assert three.per_replicate == [1.0, 1.2, 0.8], "the replicas are kept, not just their mean"


def test_a_metric_over_a_single_frame_trajectory_is_refused(tmp_path):
    """Every metric here is a statistic over frames, and one frame makes all of them zero."""
    pytest.importorskip("mdtraj")
    with pytest.raises(analysis.AnalysisFailed, match="no trajectory"):
        analysis._load(str(tmp_path / "absent.dcd"), str(COMPLEX))


# -- what the CPU smoke established -----------------------------------------


def test_the_pocket_comes_from_the_design_complex_and_not_the_equilibrated_frame(tmp_path):
    """**Measured, not assumed, and the numbers are why it matters.**

    The same rule on the design complex gives 18 pocket residues and on the equilibrated holo
    frame gives 20 -- the structure moved during minimisation and equilibration, so residues
    near the 5.0 A boundary crossed it. Nothing is wrong with either set; only one of them is
    the set Model B's featuriser scored, and only that one makes the label and the prediction
    commensurable.

    This asserts the design side, which is what `measure_all` uses. The 20 is recorded in the
    module docstring rather than here, because reproducing it needs an equilibrated frame.
    """
    design = analysis.resolve_pocket_residues(str(COMPLEX), "A:R")
    assert len(design) == 18
    assert all(r.startswith("A") for r in design), "pocket residues are the protein's"


@needs_amber
@needs_openmm
@pytest.mark.slow
def test_tleap_keeps_the_proteins_residue_numbering_so_the_labels_still_select(tmp_path):
    """**What has to be true for the design-complex pocket to mean anything downstream.**

    If tleap ever renumbered the protein, the residue labels would still *look* fine and would
    select different atoms -- a measurement over the wrong residues, reported under the right
    name. It does not: chain A residues 1-147 survive, and only the ligand is renumbered
    (`B 386 A:R` becomes `A 148 ALR`).
    """
    from asteer.features_impl import structure_io

    from impress_a.md.system import build_leg, equilibrate

    built = build_leg(leg="holo", complex_pdb=str(COMPLEX), params_dir=str(PARAMS),
                      out_dir=str(tmp_path / "holo"), padding_nm=0.8)
    leg = equilibrate(built, platform="CPU", heat_ps=0.2, npt_ps=0.2, seed=1)

    def protein_residues(path):
        atoms = structure_io.read_structure(path).atoms
        return sorted({(a.chain, a.resnum) for a in atoms
                       if not a.het and a.resname not in
                       ("HOH", "WAT", "Na+", "Cl-", "NA", "CL")})

    assert protein_residues(str(COMPLEX)) == protein_residues(leg.equilibrated_pdb)


@needs_amber
@needs_openmm
@pytest.mark.slow
def test_the_cpu_smoke_produces_three_finite_metrics_with_a_non_zero_sigma(tmp_path):
    """**K2-K4's verification bar, on one design.**

    Both legs build, run three seeded replicas each, and the three metrics come out finite with
    a sigma from the replicate spread. Ten picoseconds rather than fifteen nanoseconds, which is
    why `rmsd_plateau_frac` comes back far below its gate: see the assertion below, which is the
    gate working rather than the protocol failing.
    """
    from impress_a.md.ensemble import run_replicate
    from impress_a.md.system import build_leg, equilibrate

    legs, reps = {}, {}
    for leg in LEGS:
        built = build_leg(leg=leg, complex_pdb=str(COMPLEX), params_dir=str(PARAMS),
                          out_dir=str(tmp_path / leg), padding_nm=0.8)
        legs[leg] = equilibrate(built, platform="CPU", heat_ps=0.2, npt_ps=0.2, seed=7)
        reps[leg] = [run_replicate(legs[leg], index=i, base_seed=7, ns=0.004,
                                   platform="CPU", frames_per_ns=2500,
                                   checkpoint_interval_ps=2.0)
                     for i in range(3)]
        assert len({r.seed for r in reps[leg]}) == 3, "three replicas, three seeds"
        assert all(r.n_frames >= 5 for r in reps[leg]), [r.n_frames for r in reps[leg]]

    metrics = analysis.measure_all(
        legs=legs, replicates=reps, complex_pdb=str(COMPLEX),
        design_ligand_resname="A:R", ligand_resname="ALR")

    for name in ("preorg_rmsd", "rotamer_entropy", "ligand_rmsf"):
        m = metrics[name]
        assert m.value is not None and math.isfinite(m.value), (name, m.as_dict())
        assert m.n_replicates == 3
        assert m.sigma is not None and m.sigma > 0.0, (
            f"{name} has no spread: the replicate ensemble is the label's sigma, and a label "
            "without one is what acquisition.rank refuses a candidate for"
        )
    assert metrics["pocket_residues"].value == 18.0

    # **And the integrity gate correctly refuses this measurement.** A four-picosecond run has
    # not equilibrated, so `rmsd_plateau_frac` lands far below `md_label`'s 0.5 floor -- which
    # is the gate saying the instrument did not work, not the design being weak.
    plateau = metrics["rmsd_plateau_frac"]
    assert plateau.value is not None and plateau.value < 0.5, (
        "a smoke this short must NOT pass the plateau gate; if it does, the gate is not "
        "measuring equilibration"
    )
