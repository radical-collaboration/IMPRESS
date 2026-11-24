"""The scaffold pass: the corpus-level step the system did not have.

What matters here is not that clustering works -- `asteer` owns the rule and tests it against
the real 2,733-sequence corpus -- but that **a design tree comes out of this with a cluster and
a sequence on every node it could read**, because that is the thing nothing did (item 71), and
that the designs it could not read are *reported* rather than quietly left out.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from impress_a.core.artifacts import ArtifactRef, Property, PropertySource, SourceKind
from impress_a.core.scaffolds import MEMBERS_FOR_A_FOLD, assign_scaffolds
from impress_a.core.tree import CampaignTree, DesignNode
from impress_a.core.types import ArtifactType

#: One residue per line is enough: the reader takes CA atoms like any other, and the sequence
#: is what the pass is about. Element columns are present, so nothing is inferred.
_ATOM = ("ATOM  {serial:5d}  CA  {resname:>3s} {chain}{resnum:4d}    "
         "{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C")
_HET = ("HETATM{serial:5d}  N1  ALR {chain}{resnum:4d}    "
        "{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           N")

_THREE = {"A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY",
          "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU", "M": "MET", "N": "ASN",
          "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER", "T": "THR", "V": "VAL",
          "W": "TRP", "Y": "TYR"}


def _write_pdb(path: Path, sequence: str, *, ligand: bool = True) -> str:
    """A one-chain design whose protein sequence is exactly `sequence`, plus its ligand."""
    lines = [
        _ATOM.format(serial=i + 1, resname=_THREE[letter], chain="A", resnum=i + 1,
                     x=float(i), y=0.0, z=0.0)
        for i, letter in enumerate(sequence)
    ]
    if ligand:
        lines.append(_HET.format(serial=len(sequence) + 1, chain="A", resnum=900,
                                 x=0.0, y=5.0, z=0.0))
    path.write_text("\n".join(lines) + "\nEND\n", encoding="utf-8")
    return str(path)


def _design(tree: CampaignTree, path: str | None,
            artifact_type: ArtifactType = ArtifactType.COMPLEX) -> str:
    node = DesignNode(cycle=0)
    if path is not None:
        node.artifacts["structure"] = ArtifactRef(type=artifact_type, path=path)
    return tree.add(node)


@pytest.fixture
def base() -> str:
    return "ACDEFGHIKLMNPQRSTVWY" * 5          # 100 residues, the length of a real design


def test_every_design_comes_out_with_a_cluster_and_a_sequence(tmp_path, base):
    """**Item 71, closed on the impress-a side.** Nothing wrote either of these properties.

    `scaffold` is the key ROME's `_group_of` reads; `design_sequence` is what makes the
    grouping recomputable when the corpus grows, and `MeasurementBridge` refuses to copy a
    cluster onto a label without it.
    """
    tree = CampaignTree()
    near = base[:60] + "M" + base[61:]
    far = "".join(reversed(base))
    ids = [_design(tree, _write_pdb(tmp_path / f"d{i}.pdb", seq))
           for i, seq in enumerate((base, near, far))]

    report = assign_scaffolds(tree)

    assert report.nodes == report.sequenced == 3
    assert not report.unreadable
    assert report.rule == "single-linkage-0.80"
    for node_id in ids:
        properties = tree.nodes[node_id].properties
        assert properties["scaffold"].value.startswith("sl80-")
        assert properties["design_sequence"].value


def test_near_duplicates_land_in_one_cluster_and_an_unrelated_design_does_not(tmp_path, base):
    """The grouping doing its job on a tree: this is what a holdout boundary must not split."""
    tree = CampaignTree()
    near = base[:60] + "M" + base[61:]
    far = "".join(reversed(base))
    a = _design(tree, _write_pdb(tmp_path / "a.pdb", base))
    b = _design(tree, _write_pdb(tmp_path / "b.pdb", near))
    c = _design(tree, _write_pdb(tmp_path / "c.pdb", far))

    assign_scaffolds(tree)
    cluster = {nid: tree.nodes[nid].properties["scaffold"].value for nid in (a, b, c)}

    assert cluster[a] == cluster[b], "two designs one substitution apart were separated"
    assert cluster[c] != cluster[a]


def test_the_ligand_is_not_part_of_the_sequence(tmp_path, base):
    """`ALR` is a HETATM and not a residue the map knows, which is how it stays out.

    Worth a test of its own because the ligand is in every design here and a reader that
    included it would make one cluster of every design that shares the ligand -- which is
    every design in this project.
    """
    tree = CampaignTree()
    with_ligand = _design(tree, _write_pdb(tmp_path / "holo.pdb", base, ligand=True))
    without = _design(tree, _write_pdb(tmp_path / "apo.pdb", base, ligand=False))

    assign_scaffolds(tree)

    assert tree.nodes[with_ligand].properties["design_sequence"].value == base
    assert (tree.nodes[without].properties["design_sequence"].value
            == tree.nodes[with_ligand].properties["design_sequence"].value)


def test_a_design_with_no_structure_is_reported_rather_than_skipped(tmp_path, base):
    """A corpus that was only partly grouped must say so: a count the caller can refuse on."""
    tree = CampaignTree()
    _design(tree, _write_pdb(tmp_path / "ok.pdb", base))
    bare = _design(tree, None)
    metrics_only = _design(tree, str(tmp_path / "nothing.json"), ArtifactType.METRIC_SET)

    report = assign_scaffolds(tree)

    assert report.nodes == 3
    assert report.sequenced == 1
    assert set(report.unreadable) == {bare, metrics_only}
    assert "no Complex or Backbone artifact" in report.unreadable[bare]
    assert "scaffold" not in tree.nodes[bare].properties


def test_a_structure_that_will_not_parse_names_the_file_and_the_reason(tmp_path, base):
    tree = CampaignTree()
    broken = tmp_path / "broken.pdb"
    broken.write_text("this is not a PDB\n", encoding="utf-8")
    node = _design(tree, str(broken))

    report = assign_scaffolds(tree)

    assert report.sequenced == 0
    assert str(broken) in report.unreadable[node]


def test_a_backbone_is_accepted_when_no_complex_exists(tmp_path, base):
    """An early cycle may not have reached packing; the protein chain reads the same."""
    tree = CampaignTree()
    node = _design(tree, _write_pdb(tmp_path / "bb.pdb", base, ligand=False),
                   ArtifactType.BACKBONE)
    report = assign_scaffolds(tree)
    assert report.sequenced == 1
    assert tree.nodes[node].properties["design_sequence"].value == base


def test_a_complex_is_preferred_to_a_backbone_on_the_same_node(tmp_path, base):
    """By artifact *type*, never by port name: a tree sees every tool's naming at once."""
    tree = CampaignTree()
    node = DesignNode(cycle=0)
    node.artifacts["backbone"] = ArtifactRef(
        type=ArtifactType.BACKBONE,
        path=_write_pdb(tmp_path / "bb.pdb", "AAAAAAAAAA", ligand=False))
    node.artifacts["structure"] = ArtifactRef(
        type=ArtifactType.COMPLEX, path=_write_pdb(tmp_path / "cx.pdb", base))
    node_id = tree.add(node)

    assign_scaffolds(tree)

    assert tree.nodes[node_id].properties["design_sequence"].value == base


def test_a_sequence_already_on_the_node_is_believed_rather_than_re_read(tmp_path, base):
    """One derivation of "the sequence of this design", by construction.

    The node's structure says `base`; the property says something else; the property wins, so
    a file that moved cannot silently produce a second sequence for the same design.
    """
    tree = CampaignTree()
    node = DesignNode(cycle=0)
    node.artifacts["structure"] = ArtifactRef(
        type=ArtifactType.COMPLEX, path=_write_pdb(tmp_path / "d.pdb", base))
    node.properties["design_sequence"] = Property(
        name="design_sequence", value="MKVLID",
        source=PropertySource(name="elsewhere", kind=SourceKind.PREDICTED))
    node_id = tree.add(node)

    assign_scaffolds(tree)

    assert tree.nodes[node_id].properties["design_sequence"].value == "MKVLID"


def test_a_re_run_reassigns_the_cluster_when_a_design_joins_it_and_counts_that(tmp_path, base):
    """Single linkage is not stable under growth, which is why ids are content-addressed.

    Two designs 0.97 apart are two clusters at 0.98 and one the moment the threshold lets
    them merge. The pass reports the reassignment rather than leaving every old row pointing at an
    id nothing reproduces -- and the label rows carry their sequences, so they can be grouped
    again.
    """
    tree = CampaignTree()
    near = base[:60] + "MMM" + base[63:]           # three substitutions in 100: ratio 0.97
    a = _design(tree, _write_pdb(tmp_path / "a.pdb", base))
    b = _design(tree, _write_pdb(tmp_path / "b.pdb", near))

    strict = assign_scaffolds(tree, threshold=0.98)
    assert strict.groups == 2
    assert strict.reassigned == 0
    first = tree.nodes[a].properties["scaffold"].value

    merged = assign_scaffolds(tree, threshold=0.80)
    assert merged.groups == 1
    assert merged.reassigned == 2, "both nodes changed cluster and the pass did not say so"
    assert tree.nodes[a].properties["scaffold"].value != first
    assert (tree.nodes[a].properties["scaffold"].value
            == tree.nodes[b].properties["scaffold"].value)


def test_the_pass_reports_whether_a_round_could_be_validated_at_all(tmp_path, base):
    """Necessary and not sufficient, and the docstring says which -- the gate counts groups in
    the holdout, and whole clusters move largest-first."""
    tree = CampaignTree()
    for i in range(3):
        _write_pdb(tmp_path / f"s{i}.pdb", base[:40] + _THREE_LETTER_FILLER[i] * 20)
        _design(tree, str(tmp_path / f"s{i}.pdb"))

    thin = assign_scaffolds(tree)
    assert thin.usable_groups == 0
    assert thin.can_validate_a_round is False

    # Four clusters of MEMBERS_FOR_A_FOLD, each cluster a set of near-identical designs.
    tree = CampaignTree()
    for cluster in range(4):
        stem = (_THREE_LETTER_FILLER[cluster] * 100)[:100]
        for member in range(MEMBERS_FOR_A_FOLD):
            sequence = stem[:50] + "ACDEFGHIKL"[member] + stem[51:]
            path = _write_pdb(tmp_path / f"c{cluster}m{member}.pdb", sequence)
            _design(tree, path)

    rich = assign_scaffolds(tree)
    assert rich.usable_groups == 4
    assert rich.can_validate_a_round is True


#: Four residues that make four mutually unrelated 100-mers, one letter each.
_THREE_LETTER_FILLER = "ACDE"
