"""T1 - the five composition gates."""
import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.graph import TaskGraph, TaskNode
from impress_a.compose.interlock import Scrutiny, TrustLedger
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import ExperimentIntent
from impress_a.tools.registry import Registry

CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]


@pytest.fixture
def reg():
    return Registry().load()


def _v(reg, **site):
    caps = SiteCaps(**{"gpu_api": "cuda", "gpus_per_node": 1, **site})
    return Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 10, "cpu_hours": 50}))


def test_registry_loads_cleanly(reg):
    assert reg.errors == []
    assert set(reg.ids()) >= set(CHAIN)


def test_valid_chain_passes_all_gates(reg):
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    assert _v(reg).validate(g) is None


def test_gate1_rejects_type_mismatch(reg):
    """Folding a Backbone directly, with no inverse-folding step."""
    g = (TaskGraph()
         .add(TaskNode(id="a", tool="mock_generate"))
         .add(TaskNode(id="b", tool="mock_fold", deps=["a"],
                       inputs={"sequences": "a.designs"})))
    f = _v(reg).validate(g)
    assert f and f.gate == "type" and "type mismatch" in f.reason


def test_gate2_rejects_cycle(reg):
    g = (TaskGraph()
         .add(TaskNode(id="a", tool="mock_generate", deps=["b"]))
         .add(TaskNode(id="b", tool="mock_generate", deps=["a"])))
    f = _v(reg).validate(g)
    assert f and f.gate == "structure" and "cycle" in f.reason


def test_gate3_rejects_frozen_and_out_of_range(reg):
    g = TaskGraph().add(TaskNode(id="a", tool="mock_generate",
                                 params={"checkpoint": "other.pt"}))
    f = _v(reg).validate(g)
    assert f and f.gate == "parameter" and "frozen" in f.reason

    g2 = TaskGraph().add(TaskNode(id="a", tool="mock_generate",
                                  params={"num_designs": 9999}))
    f2 = _v(reg).validate(g2)
    assert f2 and f2.gate == "parameter" and "max" in f2.reason


def test_gate4_refuses_unproven_gpu_api(reg):
    """Part A risk R1 made enforceable: mock_fold has no HIP path."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = _v(reg, gpu_api="hip").validate(g)
    assert f and f.gate == "resource" and "hip" in f.reason


def test_gate5_refuses_over_budget(reg):
    caps = SiteCaps(gpu_api="cuda", gpus_per_node=1)
    v = Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 0.001}))
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = v.validate(g)
    assert f and f.gate == "budget" and "gpu_hours" in str(f.detail)


def test_replicas_are_independent_lineages(reg):
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN, replicas=3))
    assert len(g.nodes) == 12
    assert {n.lineage for n in g.nodes.values()} == {0, 1, 2}


def test_pattern_signature_ignores_parameter_values(reg):
    a = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    b = Composer(reg).compose(ExperimentIntent(
        goal="g", stages=CHAIN, params={"mock_generate": {"diffusion_steps": 199}}))
    assert a.pattern_signature() == b.pattern_signature()


def test_interlock_promotes_then_demotes():
    L = TrustLedger(promote_after=3)
    L.record_for("sig", ["x"])
    assert Scrutiny.for_pattern(L, "sig").mark_suspect
    assert not L.on_clean_run("sig") and not L.on_clean_run("sig")
    assert L.on_clean_run("sig"), "third clean run promotes"
    assert not Scrutiny.for_pattern(L, "sig").mark_suspect
    assert L.on_failure("sig"), "failure demotes"
    assert Scrutiny.for_pattern(L, "sig").mark_suspect
