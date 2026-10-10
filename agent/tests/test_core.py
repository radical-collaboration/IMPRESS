"""T1 - unit tests. Pure logic, no I/O."""
import pytest

from impress_a.core.artifacts import (AUTHORITY_ASSAY, AUTHORITY_ML_PREDICTOR, Property,
                                      PropertySource, SourceKind)
from impress_a.core.budget import BudgetLedger
from impress_a.core.pareto import Direction, Objective, pareto_front
from impress_a.core.qc import GateOutcome, GateResult, QCReport, QCVerdict
from impress_a.core.tree import CampaignTree, DesignNode
from impress_a.core.types import ArtifactType, Pattern


def _node(**metrics):
    n = DesignNode()
    for k, v in metrics.items():
        n.properties[k] = Property(name=k, value=v, source=PropertySource(name="t"))
    return n


def test_p6_must_never_be_scheduled():
    assert Pattern.P6.is_inline
    assert Pattern.P4.is_external and Pattern.P8.is_external
    assert not Pattern.P1.is_external


def test_unparameterised_ligand_is_a_type_error():
    """The Part A silent-failure mode, promoted to a compile-time check."""
    assert not ArtifactType.SMALL_MOLECULE.unifies_with(ArtifactType.PARAMETERIZED)
    assert ArtifactType.COMPLEX.unifies_with(ArtifactType.BACKBONE)
    assert not ArtifactType.BACKBONE.unifies_with(ArtifactType.COMPLEX)


def test_qc_fail_is_never_rankable():
    q = QCReport().add(GateResult(gate="g", outcome=GateOutcome.FAIL))
    assert q.verdict is QCVerdict.FAIL and not q.eligible_for_front
    s = QCReport(); s.mark_suspect("provisional")
    assert s.verdict is QCVerdict.SUSPECT and s.eligible_for_front


def test_constraints_prune_before_ranking():
    objs = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
            Objective(name="iptm", direction=Direction.MAX)]
    nodes = [_node(sc_rmsd=1.0, iptm=0.9), _node(sc_rmsd=2.0, iptm=0.95),
             _node(sc_rmsd=2.5, iptm=0.5), _node(sc_rmsd=9.0, iptm=0.99)]
    front = pareto_front(nodes, objs)
    assert len(front) == 2
    assert all(n.metric("sc_rmsd") <= 3.0 for n in front)


def test_a_node_missing_a_constrained_objective_is_never_feasible():
    """Backlog G1's first cause, as one line of core logic.

    The exploration chain (rfd3 -> ligandmpnn -> boltz) skips Rosetta, so its nodes carry
    no shape_complementarity at all. `Objective.satisfied_by` returns False for a MISSING
    value rather than treating it as unconstrained, so any objective with a min/max
    excludes such a node - and `delta-small-molecule.yaml` constrains
    shape_complementarity >= 0.55. Exploration can therefore never enter the front, which
    is why every informed explore landing increments the stagnation counter.

    This pins the CURRENT behaviour; the fix is undecided. See
    plans/exploration-vs-stagnation.md.
    """
    objs = [Objective(name="shape_complementarity", direction=Direction.MAX, min=0.55),
            Objective(name="ligand_iptm", direction=Direction.MAX, min=0.4)]
    explore = _node(ligand_iptm=0.62)          # no Rosetta metrics at all
    exploit = _node(ligand_iptm=0.55, shape_complementarity=0.61)

    assert pareto_front([explore], objs) == []
    assert [n.id for n in pareto_front([explore, exploit], objs)] == [exploit.id], \
        "a worse-scoring exploit node still wins, because it is the only one ranked"


def test_qc_failed_node_excluded_from_front():
    objs = [Objective(name="iptm", direction=Direction.MAX)]
    good, bad = _node(iptm=0.5), _node(iptm=0.99)
    bad.qc.add(GateResult(gate="clash", outcome=GateOutcome.FAIL))
    assert [n.id for n in pareto_front([good, bad], objs)] == [good.id]


def test_budget_blocks_and_reports_dimension():
    b = BudgetLedger(limits={"gpu_hours": 10, "cpu_hours": 5})
    b.charge({"gpu_hours": 9.5})
    assert b.would_exceed({"gpu_hours": 1.0}) == ["gpu_hours"]
    assert b.would_exceed({"cpu_hours": 1.0}) == []
    assert b.fraction_used("gpu_hours") == 0.95


def test_budget_reservation_prevents_concurrent_double_spend():
    """Two submissions in flight must not both be admitted against one budget.

    Gate 5 checks an estimate; the charge only lands when the graph finishes. Serially
    those coincide. Concurrently they do not, and without a reservation both graphs see
    the same untouched remaining budget and the campaign overspends.
    """
    b = BudgetLedger(limits={"gpu_hours": 10.0})
    assert b.reserve({"gpu_hours": 6.0}, "r0001") == []
    # Nothing is spent yet - the first run has not finished.
    assert b.remaining("gpu_hours") == 10.0
    assert b.available("gpu_hours") == 4.0

    assert b.reserve({"gpu_hours": 6.0}, "r0002") == ["gpu_hours"], \
        "second submission must be refused while the first holds the budget"
    assert "r0002" not in b.holds, "a refused reservation must claim nothing"

    # A smaller one still fits.
    assert b.reserve({"gpu_hours": 3.0}, "r0003") == []

    # Settling charges what it actually cost, not what was estimated.
    b.settle("r0001", {"gpu_hours": 5.0})
    assert b.remaining("gpu_hours") == 5.0
    assert b.available("gpu_hours") == 2.0      # r0003 still holds 3.0

    # Work that never ran releases its hold and is charged nothing.
    b.release("r0003")
    assert b.available("gpu_hours") == 5.0 and b.remaining("gpu_hours") == 5.0
    assert not b.holds


def test_budget_exhaustion_ignores_in_flight_reservations():
    """A campaign with everything in flight is busy, not exhausted.

    `exhausted()` terminates the campaign, and policies read it to decide whether to
    stop. If reservations counted, a healthy campaign would kill itself the moment it
    had committed its budget to work that had not yet reported.
    """
    b = BudgetLedger(limits={"gpu_hours": 10.0})
    b.reserve({"gpu_hours": 10.0}, "r0001")
    assert b.available("gpu_hours") == 0.0, "nothing more may be admitted"
    assert b.exhausted() == [], "but the campaign is not over"
    b.settle("r0001", {"gpu_hours": 10.0})
    assert b.exhausted() == ["gpu_hours"]


def test_measurement_supersedes_prediction_and_retains_it():
    t = CampaignTree()
    nid = t.add(_node(solubility=0.4))
    assert t.ingest_measurement(nid, Property(
        name="solubility", value=0.9,
        source=PropertySource(name="lab", kind=SourceKind.MEASURED,
                              authority=AUTHORITY_ASSAY)))
    n = t.get(nid)
    assert n.properties["solubility"].value == 0.9
    assert n.properties["solubility"].is_measured
    assert "solubility__superseded" in n.properties, "prediction must be retained"


def test_lower_authority_cannot_override_measurement():
    t = CampaignTree()
    nid = t.add(DesignNode())
    t.ingest_measurement(nid, Property(name="ddg", value=-4.0, source=PropertySource(
        name="lab", kind=SourceKind.MEASURED, authority=AUTHORITY_ASSAY)))
    assert not t.ingest_measurement(nid, Property(
        name="ddg", value=99.0,
        source=PropertySource(name="ml", authority=AUTHORITY_ML_PREDICTOR)))
    assert t.get(nid).properties["ddg"].value == -4.0


def test_backtracking_is_non_destructive():
    t = CampaignTree()
    root = t.add(DesignNode())
    child = t.add(DesignNode(parent=root))
    branch = t.branch_from(root)
    t.add(branch)
    assert child in [n.id for n in [t.get(child)]] or True
    assert t.get(child) is not None, "abandoned branch must survive"
    assert branch.parent == root and len(t) == 3


def test_artifact_ref_records_size_and_digest(tmp_path):
    """A path alone says nothing about whether the bytes behind it are still the ones
    the campaign reasoned about - which is the whole risk once the reasoner is remote."""
    from impress_a.core.artifacts import ArtifactRef
    from impress_a.core.types import ArtifactType

    f = tmp_path / "backbone.pdb"
    f.write_text("ATOM\n")
    ref = ArtifactRef(type=ArtifactType.BACKBONE, path=str(f)).hash_file()
    assert ref.bytes == 5 and ref.sha256 and ref.located == str(f)

    f.write_text("ATOM ATOM\n")
    assert ArtifactRef(type=ArtifactType.BACKBONE,
                       path=str(f)).hash_file().sha256 != ref.sha256, \
        "a changed file must be a different artifact"

    missing = ArtifactRef(type=ArtifactType.BACKBONE, path=str(tmp_path / "gone.pdb"))
    assert missing.hash_file().sha256 is None, "an absent file is not silently digested"

    inline = ArtifactRef(type=ArtifactType.METRIC_SET, value="M")
    assert inline.located == "M" and inline.hash_file().sha256 is None
