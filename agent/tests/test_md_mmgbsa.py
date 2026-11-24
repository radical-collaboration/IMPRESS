"""K5: the endpoint free energy, its naming, and the two silent failures it can have.

Everything here runs without MD except the last test. The two failures worth testing are not
arithmetic: a dry build that is not a strip of the solvated system, and a ligand that arrives a
lattice vector away from its receptor. Both give finite, wrong numbers.
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")
np = pytest.importorskip("numpy")

from impress_a.md import freeenergy as fe  # noqa: E402
from impress_a.md.params import LigandParameters  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ALR = REPO / "campaigns" / "data" / "alr"
PARAMS = ALR / "md"
COMPLEX = ALR / "input_pdbs" / "scaffold-with-ALR.pdb"
SPEC = REPO / "toolkits" / "asteer_labels" / "tools" / "md_label" / "spec.yaml"

needs_amber = pytest.mark.skipif(
    shutil.which("tleap") is None and not os.path.exists(
        os.path.join(os.environ.get("AMBERHOME", ""), "bin", "tleap")),
    reason="tleap builds the three dry topologies and is not here",
)
needs_openmm = pytest.mark.skipif(
    __import__("importlib").util.find_spec("openmm") is None,
    reason="OpenMM is not installed here (backlog item 77)",
)


def _prmtop(path, names):
    """A prmtop with only the two blocks this module's checks read."""
    rows = ["%VERSION  VERSION_STAMP = V0001.000", "%FLAG POINTERS", "%FORMAT(10I8)",
            f"{len(names):8d}" + f"{0:8d}" * 9, "%FLAG ATOM_NAME", "%FORMAT(20a4)"]
    for i in range(0, len(names), 20):
        rows.append("".join(f"{n:<4}" for n in names[i:i + 20]))
    path.write_text("\n".join(rows) + "\n")
    return str(path)


# -- the naming, which is the whole reason this metric is separate ------------------------


def test_the_metric_has_its_own_name_and_is_not_the_abfe_one():
    assert fe.METRIC == "dg_mmgbsa"
    assert fe.METRIC != "dg_abfe" and fe.METRIC != "dg_corrected"


def test_the_bridge_refuses_this_metric_by_name_and_that_refusal_is_correct():
    """**The important negative test in this file.**

    `PROPERTY_FOR_METRIC` is what `MeasurementBridge.ingest` resolves a metric through, and the
    property it resolves to is what supersession matches on. An MM/GBSA number reachable through
    that map would supersede Model C's prediction with something that is not the measurement it
    claims to be -- so the absence is the design, and a later edit that "fixes" it by adding a
    row should fail here and read why.
    """
    pytest.importorskip("asteer", reason="the bridge lives in asteer")
    from asteer.labels_workflow import PROPERTY_FOR_METRIC

    assert fe.METRIC not in PROPERTY_FOR_METRIC, (
        "dg_mmgbsa must not be ingestable: it is a cheap score and a candidate prior for Model "
        "C's residual (J14), not a measurement that supersedes a prediction. It travels in the "
        "task's metrics and in K5's artifact, and J14 reads it from there"
    )
    assert PROPERTY_FOR_METRIC["dg_abfe"][0] == "dg_corrected", (
        "the row this metric must not be confused with"
    )


def test_the_spec_declares_the_metric_with_its_unit_and_keeps_it_out_of_the_reported_gate():
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(SPEC.read_text())
    assert fe.METRIC in spec["metrics"]
    assert set(spec["metric_units"]) == set(spec["metrics"]), (
        "J13's rule: a metric without a unit is a corpus column a reader will guess at"
    )
    unit = spec["metric_units"][fe.METRIC]
    assert "kcal/mol" in unit and "NOT dg_abfe" in unit and "NO entropy" in unit
    reported = [g for g in spec["qc_gates"] if g["id"] == "metrics_reported"][0]
    assert fe.METRIC not in reported["params"]["metrics"], (
        "a dry-build failure costs the free-energy sample and has not stopped the instrument "
        "from working; demanding it unconditionally would file a successful 30 ns measurement "
        "as an integrity failure"
    )


def test_the_twin_reports_the_same_metric_under_the_same_words():
    yaml = pytest.importorskip("yaml")
    real = yaml.safe_load(SPEC.read_text())
    mock = yaml.safe_load(
        (REPO / "toolkits" / "mock" / "tools" / "mock_md_label" / "spec.yaml").read_text())
    assert fe.METRIC in mock["metrics"]
    assert mock["metric_units"][fe.METRIC] == real["metric_units"][fe.METRIC], (
        "a twin that described its numbers differently would let a corpus built against it mean "
        "something else"
    )
    assert "mmgbsa" in mock["parameters"] and "mmgbsa" in real["parameters"]


# -- the arithmetic ----------------------------------------------------------------------


def test_the_total_is_the_sum_of_the_two_halves_it_reports():
    """The split is what makes the total checkable: the halves are large and opposite."""
    e = {"complex_gas": -120.0, "receptor_gas": -40.0, "ligand_gas": -15.0,
         "complex_gb": -300.0, "receptor_gb": -150.0, "ligand_gb": -95.0}
    d = fe._deltas(e)
    assert d["de_mm"] == pytest.approx(-65.0)
    # solvation: complex -180, receptor -110, ligand -80  ->  -180 + 110 + 80
    assert d["dg_solv"] == pytest.approx(10.0)
    assert d["dg_total"] == pytest.approx(d["de_mm"] + d["dg_solv"])


def test_a_ligand_a_lattice_vector_away_is_brought_back_and_says_so():
    """The silent failure: `NoCutoff` does not know about the box, so the dG goes to zero."""
    box = np.array([5.0, 6.0, 7.0])
    receptor = np.array([[0.1, 0.1, 0.1], [0.3, 0.2, 0.1]])
    ligand = np.array([[0.2, 0.15, 0.12]]) + box  # one image away on every axis
    moved, did = fe._reimage(np.vstack([receptor, ligand]), 2, box)
    assert did is True
    assert np.allclose(moved[2], [0.2, 0.15, 0.12]), moved[2]
    assert np.allclose(moved[:2], receptor), "the receptor is never moved"


def test_a_ligand_already_beside_its_receptor_is_left_alone():
    box = np.array([5.0, 6.0, 7.0])
    xyz = np.array([[0.1, 0.1, 0.1], [0.3, 0.2, 0.1], [0.2, 0.15, 0.12]])
    moved, did = fe._reimage(xyz, 2, box)
    assert did is False and np.allclose(moved, xyz)


# -- the dry build, and the check that makes slicing safe --------------------------------


def test_the_dry_script_sets_the_radii_the_gb_model_expects_and_solvates_nothing():
    artifact = LigandParameters.load(str(PARAMS))
    script = fe._dry_tleap_script(protein_pdb="/x/protein.pdb", params_dir=str(PARAMS),
                                  artifact=artifact, out_dir="/y")
    assert f"set default PBRadii {fe.PB_RADII}" in script
    radii_at = script.index("set default PBRadii")
    assert radii_at > script.index("source leaprc.water.tip3p"), (
        "each `source` can set PBRadii, so setting it first is setting it and then losing it"
    )
    assert "solvatebox" not in script and "addIons" not in script, (
        "these are endpoint energies in implicit solvent; a water in the prmtop would be "
        "counted as part of the receptor"
    )
    for name in fe.SPECIES:
        assert f"/y/{name}.prmtop" in script
    assert script.count("saveamberparm") == 3


def test_a_dry_complex_that_is_not_the_solvated_systems_prefix_is_refused_by_position(tmp_path):
    dry = _prmtop(tmp_path / "dry.prmtop", ["N", "CA", "C", "O"])
    wet = _prmtop(tmp_path / "wet.prmtop", ["N", "CA", "CB", "O", "OW", "HW"])
    top = fe.DryTopologies(directory=str(tmp_path), prmtops={"complex": dry},
                           n_atoms={"complex": 4})
    with pytest.raises(fe.FreeEnergyFailed) as exc:
        top.verify_against(wet)
    assert "index 2" in str(exc.value) and "'CB'" in str(exc.value)


def test_a_dry_complex_bigger_than_the_solvated_system_is_refused(tmp_path):
    dry = _prmtop(tmp_path / "dry.prmtop", ["N", "CA", "C", "O"])
    wet = _prmtop(tmp_path / "wet.prmtop", ["N", "CA"])
    top = fe.DryTopologies(directory=str(tmp_path), prmtops={"complex": dry},
                           n_atoms={"complex": 4})
    with pytest.raises(fe.FreeEnergyFailed, match="not a strip"):
        top.verify_against(wet)


def test_a_genuine_prefix_passes(tmp_path):
    dry = _prmtop(tmp_path / "dry.prmtop", ["N", "CA", "C", "O"])
    wet = _prmtop(tmp_path / "wet.prmtop", ["N", "CA", "C", "O", "OW", "HW", "HW"])
    top = fe.DryTopologies(directory=str(tmp_path), prmtops={"complex": dry},
                           n_atoms={"complex": 4})
    top.verify_against(wet)  # no raise


def test_a_file_that_is_not_a_prmtop_is_refused_rather_than_read_as_empty(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("this is not a prmtop\n")
    with pytest.raises(fe.FreeEnergyFailed, match="not a prmtop"):
        fe._atom_names(str(path))
    with pytest.raises(fe.FreeEnergyFailed, match="not a prmtop"):
        fe._prmtop_atom_count(str(path))


def test_a_dry_build_without_k2s_protein_file_is_refused_by_name(tmp_path):
    with pytest.raises(fe.FreeEnergyFailed, match="protein.pdb"):
        fe.build_dry_topologies(holo_dir=str(tmp_path), params_dir=str(PARAMS))


# -- the provenance, because a force field is part of what the number means ---------------


def test_the_provenance_carries_the_force_field_and_says_what_the_number_is_not():
    artifact = LigandParameters.load(str(PARAMS))
    prov = fe.provenance(artifact=artifact, dry=None, stride=2, platform="CPU")
    assert prov["metric"] == fe.METRIC
    assert prov["ligand_force_field"] == artifact.force_field == "gaff2"
    assert prov["protein_force_field"] == artifact.protein_force_field == "ff14sb"
    assert prov["sampling_solvent"].startswith("TIP3P"), (
        "the frames come from explicit water and the energies from implicit water; that is the "
        "largest approximation here and it belongs in the record"
    )
    assert prov["energy_solvent"].startswith("OBC2")
    assert prov["pb_radii"] == "mbondi2"
    assert prov["entropy_term"].startswith("none") and "entropy" in prov["entropy_term"]
    assert "dg_abfe" in prov["not"] and "dg_corrected" in prov["not"]
    assert prov["stride"] == 2


def test_no_replica_at_all_is_refused_rather_than_averaged():
    with pytest.raises(fe.FreeEnergyFailed, match="no holo replica"):
        fe.mmgbsa(runs=[], dry=fe.DryTopologies(directory="", prmtops={}, n_atoms={}))


# -- the real thing ----------------------------------------------------------------------


@pytest.mark.slow
@needs_amber
@needs_openmm
def test_the_cpu_smoke_gives_a_distribution_with_both_spreads(tmp_path):
    """**K5's verification bar.** Three replicas, per-frame values, and two different sigmas.

    Four picoseconds of sampling, so the *value* means nothing about this design -- what is
    being verified is that the arithmetic runs on real frames and that the distribution comes
    out with a frame spread wider than the replicate spread, which is what makes reporting them
    separately necessary rather than tidy.
    """
    from impress_a.md.ensemble import run_replicate
    from impress_a.md.system import build_leg, equilibrate

    built = build_leg(leg="holo", complex_pdb=str(COMPLEX), params_dir=str(PARAMS),
                      out_dir=str(tmp_path / "holo"), padding_nm=0.8)
    leg = equilibrate(built, platform="CPU", heat_ps=0.2, npt_ps=0.2, seed=7)
    reps = [run_replicate(leg, index=i, base_seed=7, ns=0.004, platform="CPU",
                          frames_per_ns=2500, checkpoint_interval_ps=2.0)
            for i in range(3)]

    dry = fe.build_dry_topologies(holo_dir=leg.directory, params_dir=str(PARAMS))
    assert dry.n_atoms["receptor"] + dry.n_atoms["ligand"] == dry.n_atoms["complex"]
    dry.verify_against(leg.prmtop)

    samples = fe.mmgbsa(runs=[(r.trajectory, leg.equilibrated_pdb) for r in reps],
                        dry=dry, solvated_prmtop=leg.prmtop, params_dir=str(PARAMS),
                        platform="CPU")

    assert samples.value is not None and math.isfinite(samples.value), samples.as_dict()
    assert samples.n_replicates == 3 and samples.n_frames >= 15
    assert samples.sigma is not None and samples.sigma > 0.0, (
        "the replicate spread is the label's sigma, as it is for every other metric here"
    )
    # **Both spreads, reported separately, and neither is the other.** Measured on this smoke:
    # frame_sigma 4.37 kcal/mol against sigma 3.95. They are comparable here only because ten
    # frames over four picoseconds are correlated -- with real sampling the replicate means
    # converge as 1/sqrt(n) and the frame spread does not, so the gap widens. The assertion is
    # deliberately not the inequality: on a four-picosecond run that would be a coin toss.
    assert samples.frame_sigma is not None and samples.frame_sigma > 0.0, (
        "the per-frame distribution is the width the plan asked for, and it is NOT an "
        "uncertainty on the mean: an MM/GBSA frame distribution is kcal/mol-wide for a complex "
        "whose mean is well determined"
    )
    assert samples.components["dg_total"] == pytest.approx(
        samples.components["de_mm"] + samples.components["dg_solv"], abs=1e-6)
    # A charged ligand in a real pocket: tens of kcal/mol, negative, and nowhere near a dG_bind.
    assert -200.0 < samples.value < 0.0, samples.value
    assert samples.provenance["ligand_force_field"] == "gaff2"
    assert samples.frames_dropped == 0, "no frame should have a broken receptor"


# -- what reaches a subprocess (security review, 2026-11-24) -----------------------------


def test_an_artifact_whose_file_name_is_not_a_plain_name_is_refused(tmp_path):
    """**The names in K1's artifact are written into a tleap script and then executed.**

    So a name carrying a newline is a leap command of somebody else's choosing, and one
    carrying a separator reads a file from outside the artifact. The digests do not cover this:
    they live in the same JSON as the names, so they prove a file has not changed since the
    artifact was written, not that the artifact is one this project wrote.
    """
    import json
    import shutil as sh

    from impress_a.md.params import ARTIFACT_NAME, ParameterisationFailed

    for bad in ("../ligand.mol2", "ligand.mol2\nquit", "sub/ligand.mol2", "lig and.mol2"):
        directory = tmp_path / f"case{abs(hash(bad))}"
        directory.mkdir()
        for name in os.listdir(PARAMS):
            sh.copy(PARAMS / name, directory / name)
        payload = json.loads((directory / ARTIFACT_NAME).read_text())
        payload["files"]["mol2"] = bad
        (directory / ARTIFACT_NAME).write_text(json.dumps(payload))
        with pytest.raises(ParameterisationFailed, match="not a plain file name"):
            LigandParameters.load(str(directory))


def test_the_committed_artifact_passes_the_same_check():
    """The check has to admit the real one, or it is a check on nothing."""
    artifact = LigandParameters.load(str(PARAMS))
    assert set(artifact.files) >= {"mol2", "frcmod"}
    for name in list(artifact.files.values()) + list(artifact.digests):
        assert os.path.basename(name) == name


def test_no_proposable_parameter_of_md_label_is_a_path():
    """A reasoner's card for this tool is numbers and one bool. **No paths at all.**

    Four of them are `operator_only`: `amberhome` is joined to `bin/tleap` and EXECUTED, so an
    executable path chosen by a reasoner is arbitrary command execution; `md_params_dir`
    decides which force field the measurement is in; `design_dir` decides which molecule is
    measured, and a label supersedes a prediction on a specific node; `ligand_params_path` is
    a file the tool reads. `tools/view.py` is the one seam that enforces it, by reporting them
    under `frozen` so they never reach the card a reasoner proposes against.
    """
    pytest.importorskip("yaml")
    from impress_a.tools.registry import Registry
    from impress_a.tools.view import card_for

    registry = Registry().load()
    for tool in ("md_label", "mock_md_label"):
        card = card_for(registry.get(tool))
        assert {"amberhome", "md_params_dir", "design_dir", "ligand_params_path"} <= set(
            card.frozen), f"{tool} would let a reasoner propose a path"
        for name, param in card.parameters.items():
            assert param.type in ("int", "float", "bool"), (
                f"{tool} offers {name!r} ({param.type}) to a reasoner; every path parameter "
                "here is operator_only, and a new one must say why it is not"
            )
