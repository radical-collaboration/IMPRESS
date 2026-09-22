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


def test_trust_ledger_survives_concurrent_writers(tmp_path):
    """The trust file is shared across campaigns by design, so two campaigns must not
    overwrite each other's evidence.

    The ledger used to rewrite the whole file on every update. Two campaigns holding it
    open would each persist only their own view, and whichever saved last silently
    discarded the other's clean runs - the interlock quietly losing the evidence it
    exists to accumulate.
    """
    path = tmp_path / "_trust" / "cuda.jsonl"
    a = TrustLedger.load(path, promote_after=3)
    b = TrustLedger.load(path, promote_after=3)

    a.record_for("sig", ["x"])
    b.record_for("sig", ["x"])
    a.on_clean_run("sig")          # campaign A observes one clean run
    b.on_clean_run("sig")          # campaign B observes another, concurrently
    a.on_clean_run("sig")

    fresh = TrustLedger.load(path, promote_after=3)
    assert fresh.patterns["sig"].clean_runs == 3, \
        "every writer's evidence must survive; a lost update would show fewer"
    assert fresh.is_trusted("sig"), "three clean runs promote the pattern"

    b.on_failure("sig")
    assert not TrustLedger.load(path, promote_after=3).is_trusted("sig"), \
        "demotion is evidence too and must persist"


def test_trust_ledger_without_a_path_persists_nothing():
    """The in-memory form is what the validation tier uses; it must not touch disk."""
    L = TrustLedger(promote_after=2)
    L.record_for("sig", ["x"])
    assert L.on_clean_run("sig") is False
    assert L.on_clean_run("sig") is True
    assert L.path is None
