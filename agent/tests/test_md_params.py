"""K1: the ligand typed once, and what the artifact has to be able to say.

The parameterisation itself needs AmberTools and RDKit and takes about a minute, so the test
that runs it is marked and skipped without them. **What is not skipped is the artifact's own
behaviour** -- the digest check, the charge ceiling, the penalty parsing and the counterion
arithmetic -- because those are what stop a committed parameter set from drifting away from
what every label in the corpus was measured with.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from impress_a.md.params import (  # noqa: E402
    ARTIFACT_NAME,
    FRCMOD_NAME,
    MAX_CHARGE_RESIDUAL,
    MOL2_NAME,
    LigandParameters,
    ParameterisationFailed,
    _max_penalty,
    _penalties,
    _read_mol2,
    _redistribute_charge,
    parameterise,
)

REPO = Path(__file__).resolve().parents[1]
ALR = REPO / "campaigns" / "data" / "alr"
COMMITTED = ALR / "md"

needs_amber = pytest.mark.skipif(
    shutil.which("antechamber") is None and not os.path.exists(
        os.path.join(os.environ.get("AMBERHOME", ""), "bin", "antechamber")),
    reason="AmberTools supplies the offline parameterisation route and is not here",
)


# -- the committed artifact --------------------------------------------------


def test_the_committed_alr_artifact_says_what_it_is():
    """Every field a reader needs before trusting a number measured with these parameters."""
    art = LigandParameters.load(str(COMMITTED))
    assert art.resname == "ALR"
    assert art.force_field == "gaff2", "not CGenFF, and the artifact says so"
    assert art.water_model == "tip3p"
    # The determination: one force-field family, not two. CHARMM36m was available -- OpenMM
    # ships charmm36.xml -- and is not used, because GAFF2 is Amber's small-molecule force
    # field and mixing families is a combination nobody validated.
    assert art.protein_force_field == "ff14sb"
    assert art.net_charge == -2, "two sulfonates"
    assert art.n_heavy_atoms == 30, "which is the HETATM count in the complex"
    assert art.n_atoms == 44
    assert art.counterions == {"NA": 2}, "one monovalent ion per unit of ligand charge"


def test_the_committed_artifact_matches_the_bytes_beside_it():
    """**The check that stops a parameter file being edited in place.**

    After such an edit every label in the corpus was measured with something other than what
    the artifact describes, and nothing else anywhere would disagree.
    """
    LigandParameters.load(str(COMMITTED)).verify(str(COMMITTED))


def test_a_changed_parameter_file_is_refused_by_name(tmp_path):
    for name in (ARTIFACT_NAME, MOL2_NAME, FRCMOD_NAME):
        shutil.copy(COMMITTED / name, tmp_path / name)
    with open(tmp_path / FRCMOD_NAME, "a") as handle:
        handle.write("\n# somebody tuned a dihedral\n")
    art = LigandParameters.load(str(tmp_path))
    with pytest.raises(ParameterisationFailed) as caught:
        art.verify(str(tmp_path))
    assert FRCMOD_NAME in str(caught.value)
    assert "measured with what was on disk" in str(caught.value)


def test_the_charges_sum_to_the_formal_charge_after_correction():
    """AM1-BCC does not, and a non-integer net charge makes PME add a uniform plasma."""
    charges, _ = _read_mol2(str(COMMITTED / MOL2_NAME))
    assert len(charges) == 44
    assert sum(charges) == pytest.approx(-2.0, abs=1e-5)


def test_the_residual_that_was_corrected_is_recorded_rather_than_hidden():
    art = LigandParameters.load(str(COMMITTED))
    assert art.charge_sum == pytest.approx(-2.004003, abs=1e-6), "as AM1-BCC produced it"
    assert art.charge_residual == pytest.approx(0.004003, abs=1e-6)
    assert abs(art.charge_residual) < MAX_CHARGE_RESIDUAL


def test_the_azo_group_was_typed_and_not_guessed():
    """The coverage the plan flagged as CGenFF's weak point, checked on GAFF2's side."""
    art = LigandParameters.load(str(COMMITTED))
    assert {"ne", "nf"} <= set(art.atom_types), (
        "the azo nitrogens have conjugated types rather than falling back to generic N"
    )
    text = (COMMITTED / FRCMOD_NAME).read_text()
    for section in ("BOND", "ANGLE", "DIHE"):
        body = text.split(section, 1)[1].split("\n\n", 1)[0].strip()
        assert not body, f"GAFF2 had every {section} parameter exactly; {body!r} says otherwise"


def test_every_guessed_parameter_is_recorded_verbatim_and_they_are_all_impropers():
    """Verbatim, because the summary a reader needs depends on what they are checking:
    `penalty score= 6.0` on an aromatic CH improper is routine and the same number on a bond
    is not, and a count would hide which."""
    art = LigandParameters.load(str(COMMITTED))
    assert len(art.penalties) == 7
    assert art.max_penalty == 6.0
    # Four fields of atom types means an improper or a proper dihedral; every one of these is
    # in the IMPROPER section, which the frcmod's empty DIHE section already established.
    for line in art.penalties:
        assert line.split()[0].count("-") == 3, line


def test_the_template_match_ambiguity_is_a_field_and_not_a_log_line():
    """ALR is nearly symmetric, so its pose matches its SMILES more than one way and RDKit
    picks one. Which mapping it picked decides every atom NAME, so two runs that picked
    differently produce the same energies under names that do not line up."""
    assert LigandParameters.load(str(COMMITTED)).template_match_ambiguous is True


def test_a_directory_with_no_artifact_is_refused_with_the_reason(tmp_path):
    with pytest.raises(ParameterisationFailed, match="typed once"):
        LigandParameters.load(str(tmp_path))


# -- the pieces, without AmberTools -----------------------------------------


def test_the_penalty_parser_reads_all_three_of_parmchk2s_phrasings(tmp_path):
    frcmod = tmp_path / "f.frcmod"
    frcmod.write_text(
        "Remark line goes here\nMASS\n\nBOND\n"
        "c3-ca   300.0   1.5   Using the default value\n"
        "ANGLE\n"
        "ca-ca-ne  60.0  120.0  ATTN, need revision\n"
        "DIHE\n"
        "X -ca-ca-X   3.6  180.0  2.0   penalty score=  3.0)\n"
        "IMPROPER\n"
        "ca-ca-ca-ha  1.1  180.0  2.0   Same as ca-ca-ca-ha\n"
    )
    found = _penalties(str(frcmod))
    assert len(found) == 3, found
    assert _max_penalty(found) == 3.0
    assert _max_penalty([]) is None


def test_redistributing_the_charge_leaves_the_mol2_otherwise_readable(tmp_path):
    path = tmp_path / MOL2_NAME
    shutil.copy(COMMITTED / MOL2_NAME, path)
    before, types = _read_mol2(str(path))
    _redistribute_charge(str(path), 0.3)
    after, types_after = _read_mol2(str(path))
    assert types_after == types, "atom types must survive a charge edit untouched"
    assert sum(after) == pytest.approx(sum(before) + 0.3, abs=1e-5)
    assert len(after) == len(before)


def test_a_zero_residual_changes_nothing_at_all(tmp_path):
    path = tmp_path / MOL2_NAME
    shutil.copy(COMMITTED / MOL2_NAME, path)
    original = path.read_bytes()
    _redistribute_charge(str(path), 0.0)
    assert path.read_bytes() == original


# -- the real run -----------------------------------------------------------


@needs_amber
@pytest.mark.slow
def test_parameterising_alr_reproduces_the_committed_artifact(tmp_path):
    """The whole pipeline, against what is committed. ~1 minute: sqm does an AM1 calculation.

    **What must reproduce is the chemistry, not the bytes.** The charges come from a
    semi-empirical optimisation and the last digit moves between builds, so this asserts the
    atom count, the types, the penalties and the charge sum -- the things a label's meaning
    depends on.
    """
    pytest.importorskip("rdkit", reason="the bond-order template needs RDKit")
    smiles = (ALR / "ALR.smiles").read_text().split()[0]
    fresh = parameterise(
        smiles=smiles,
        pose_pdb=str(ALR / "input_pdbs" / "scaffold-with-ALR.pdb"),
        out_dir=str(tmp_path / "md"),
        resname="ALR",
        net_charge=-2,
    )
    committed = LigandParameters.load(str(COMMITTED))
    assert fresh.n_atoms == committed.n_atoms
    assert fresh.n_heavy_atoms == committed.n_heavy_atoms
    assert sorted(fresh.atom_types) == sorted(committed.atom_types)
    assert len(fresh.penalties) == len(committed.penalties)
    assert fresh.max_penalty == committed.max_penalty
    assert fresh.charge_sum == pytest.approx(committed.charge_sum, abs=5e-3)
    assert fresh.counterions == committed.counterions
    fresh.verify(str(tmp_path / "md"))


@needs_amber
def test_a_smiles_whose_charge_disagrees_with_the_declared_one_is_refused(tmp_path):
    """A disagreement here is two different molecules, and the declared charge decides both
    the counterions and the AM1-BCC calculation."""
    pytest.importorskip("rdkit", reason="the bond-order template needs RDKit")
    smiles = (ALR / "ALR.smiles").read_text().split()[0]
    with pytest.raises(ParameterisationFailed, match="formal charge"):
        parameterise(smiles=smiles,
                     pose_pdb=str(ALR / "input_pdbs" / "scaffold-with-ALR.pdb"),
                     out_dir=str(tmp_path / "md"), resname="ALR", net_charge=0)


def test_a_pose_with_no_hetatm_is_refused(tmp_path):
    pytest.importorskip("rdkit", reason="the bond-order template needs RDKit")
    empty = tmp_path / "apo.pdb"
    empty.write_text("ATOM      1  N   HIS A   1      -6.714  31.191  -5.268\nEND\n")
    with pytest.raises(ParameterisationFailed, match="no HETATM"):
        parameterise(smiles="C", pose_pdb=str(empty), out_dir=str(tmp_path / "md"),
                     resname="LIG", net_charge=0)
