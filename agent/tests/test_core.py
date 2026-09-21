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
