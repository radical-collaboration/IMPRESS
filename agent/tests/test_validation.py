"""T1 - the five composition gates."""
import pathlib

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


def test_trust_survives_a_campaign_running_from_a_different_directory(tmp_path, monkeypatch):
    """Promotion has to accumulate across JOBS, and on HPC every job is a fresh CWD.

    `spec.root` defaulted to the relative "campaigns/_runs", and `delta_gpu_run.sh` cds into a
    per-job directory under `$WORK_DIR/impress_a_runs` before launching - so the ledger resolved inside
    each job's own directory and started empty every time. On disk after two real runs:

        22684607/campaigns/_runs/_trust/cuda.jsonl   0 clean
        22692304/campaigns/_runs/_trust/cuda.jsonl   1 clean

    Two files, one clean run each, `promote_after=3` counting within one file. Promotion was
    unreachable on Delta from the first run onward - which means the entire trusted path (no
    forced dry-run, no 10% cost cap, concurrent instances allowed) had never executed, and no
    number of extra campaigns would have changed that.

    The ledger's own accumulation is covered above. What was never covered is how its path gets
    chosen, which is the whole of the defect - every other trust test hands it an explicit
    tmp_path.
    """
    from impress_a.manager import CampaignSpec
    from impress_a.runtime.executor import CampaignExecutor

    shared = tmp_path / "site_trust"
    sig = "a-pattern-signature"

    def executor_in(job_dir: str) -> CampaignExecutor:
        d = tmp_path / job_dir
        (d / "campaigns" / "_runs").mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(d)
        spec = CampaignSpec(campaign_id="c", goal="g", objectives=[],
                            trust_root=str(shared), site=SiteCaps(gpu_api="cuda"))
        return CampaignExecutor(spec, policy=None)

    for job in ("job_1", "job_2", "job_3"):
        ex = executor_in(job)
        ex.trust.record_for(sig, ["x"])
        ex.trust.on_clean_run(sig)

    assert executor_in("job_4").trust.is_trusted(sig), \
        "three clean runs from three job directories must promote the pattern; if this " \
        "fails the ledger is resolving per-job again and nothing can ever be trusted"


def test_trust_root_overrides_the_campaign_root(tmp_path, monkeypatch):
    """And with neither override, the path must not move - the laptop tier depends on it."""
    from impress_a.manager import CampaignSpec
    from impress_a.runtime.executor import CampaignExecutor

    monkeypatch.chdir(tmp_path)
    (tmp_path / "campaigns" / "_runs").mkdir(parents=True)

    explicit = tmp_path / "elsewhere"
    ex = CampaignExecutor(CampaignSpec(campaign_id="c", goal="g", objectives=[],
                                       trust_root=str(explicit),
                                       site=SiteCaps(gpu_api="cuda")), policy=None)
    assert pathlib.Path(ex.trust.path) == explicit / "cuda.jsonl"

    ex = CampaignExecutor(CampaignSpec(campaign_id="c", goal="g", objectives=[],
                                       site=SiteCaps(gpu_api="cuda")), policy=None)
    assert pathlib.Path(ex.trust.path) == pathlib.Path("campaigns/_runs/_trust/cuda.jsonl"), \
        "the default is relative on purpose - stable CWD, and tests rely on it"


def test_run_root_comes_from_the_environment_unless_the_yaml_names_one(tmp_path, monkeypatch):
    """`delta_gpu_run.sh` exports IMPRESS_A_RUN_ROOT as the job's own directory, so
    provenance lands beside campaign.log. A `root:` written in the YAML still wins, and with
    neither the laptop default must not move."""
    from impress_a.cli import load_spec

    src = pathlib.Path("campaigns/mock-stabilize.yaml").read_text()
    plain = tmp_path / "plain.yaml"
    plain.write_text(src)
    pinned = tmp_path / "pinned.yaml"
    pinned.write_text(src + "\nroot: /from/yaml\n")

    monkeypatch.delenv("IMPRESS_A_RUN_ROOT", raising=False)
    assert load_spec(plain).root == "campaigns/_runs"
    monkeypatch.setenv("IMPRESS_A_RUN_ROOT", "/from/env")
    assert load_spec(plain).root == "/from/env"
    assert load_spec(pinned).root == "/from/yaml"


def test_trust_ledger_without_a_path_persists_nothing():
    """The in-memory form is what the validation tier uses; it must not touch disk."""
    L = TrustLedger(promote_after=2)
    L.record_for("sig", ["x"])
    assert L.on_clean_run("sig") is False
    assert L.on_clean_run("sig") is True
    assert L.path is None


# -- integrity vs acceptance (decision 0013) ------------------------------------------

def _executor_with_memory_ledger(tmp_path):
    from impress_a.manager import CampaignSpec
    from impress_a.runtime.executor import CampaignExecutor

    ex = CampaignExecutor(CampaignSpec(campaign_id="c", goal="g", objectives=[],
                                       root=str(tmp_path), site=SiteCaps(gpu_api="cuda")),
                          policy=None)
    ex.trust = TrustLedger(promote_after=3)
    ex.trust.record_for("sig", ["x"])
    return ex


def _results(reg, per_tool: dict, failures: dict | None = None):
    """ExecutionResults whose QC comes from the REAL specs' gates over these metrics."""
    from impress_a.exec.dispatch import ExecutionResults
    from impress_a.tools import gates
    from impress_a.tools.agent import TaskResult

    per_task = {}
    for tool, metrics in per_tool.items():
        payload = {"result": "x", "count": 1, "outputs": {}, "metrics": metrics}
        per_task[tool] = TaskResult(tool=tool, outputs={}, metrics=metrics,
                                    qc=gates.evaluate(reg.get(tool), payload), cost={})
    return ExecutionResults(graph_id="g", per_task=per_task, failures=failures or {})


def test_gate_role_defaults_to_integrity_and_rejects_anything_else():
    from impress_a.tools.spec import GateSpec

    assert GateSpec(id="output_present").role == "integrity", \
        "an unclassified gate must keep blocking trust"
    with pytest.raises(ValueError):
        GateSpec(id="metric_in_range", role="advisory")


def test_an_acceptance_threshold_needs_a_presence_check(reg):
    """Otherwise a value the adapter never read is just a low score, and promotes."""
    from impress_a.tools.spec import ToolSpec

    spec = reg.get("boltz_predict").model_dump()
    spec["qc_gates"] = [g for g in spec["qc_gates"] if g["id"] != "metrics_reported"]
    with pytest.raises(ValueError, match="metrics_reported"):
        ToolSpec(**spec)


def test_the_real_toolkits_classify_exactly_the_quality_thresholds_as_acceptance(reg):
    acceptance = {(t, g.params["metric"]) for t in reg.specs
                  for g in reg.get(t).qc_gates if g.role == "acceptance"}
    assert acceptance == {("ligandmpnn_design", "overall_confidence"),
                          ("ligandmpnn_design", "ligand_confidence"),
                          ("filter_shape", "shape_complementarity"),
                          ("boltz_predict", "complex_plddt"),
                          ("boltz_predict", "ligand_iptm")}, \
        "every other gate - presence, structure, the Rosetta divergence bounds - is integrity"


def test_qc_report_separates_integrity_from_acceptance():
    from impress_a.core.qc import GateOutcome, GateResult, QCReport

    q = QCReport().add(GateResult(gate="t", outcome=GateOutcome.FAIL, role="acceptance",
                                  observed=0.3, threshold=[0.4, None]))
    assert q.integrity_ok and not q.eligible_for_front, \
        "an acceptance FAIL still fails the node - it just is not evidence against the pattern"
    q.add(GateResult(gate="present", outcome=GateOutcome.FAIL))
    assert not q.integrity_ok
    assert [f["role"] for f in q.failed()] == ["acceptance", "integrity"]


def test_only_integrity_failures_reset_trust(reg, tmp_path):
    from types import SimpleNamespace

    ex = _executor_with_memory_ledger(tmp_path)
    rec = SimpleNamespace(signature="sig")
    weak = {"boltz_predict": {"complex_plddt": 0.3, "ligand_iptm": 0.2}}  # worked, scored low
    for _ in range(3):
        assert ex._record_evidence(rec, _results(reg, weak)) is False
    assert ex.trust.is_trusted("sig"), "three acceptance-only failures are three clean runs"

    no_ligand = {"boltz_predict": {"complex_plddt": 0.88}}                # broke silently
    assert ex._record_evidence(rec, _results(reg, no_ligand)) is True
    assert not ex.trust.is_trusted("sig"), "an integrity failure demotes immediately"

    ex.trust.record_for("sig", ["x"])
    fine = {"boltz_predict": {"complex_plddt": 0.8, "ligand_iptm": 0.6}}
    assert ex._record_evidence(rec, _results(reg, fine, failures={"t": "boom"})) is True, \
        "a task that failed outright is still a failure, whatever its gates say"


# Per-task metrics of job 22702568, copied from its jobs/ledger.jsonl. Under the old rule
# (every gate counts) its five 6/6 runs recorded failure/clean/failure/failure/clean and
# promoted nothing. This is the offline prediction the next Delta run is checked against.
_JOB_22702568 = {
    "r0001": {"rfd3_design": {"ss_fraction": 0.827},
              "ligandmpnn_design": {"overall_confidence": 0.45, "ligand_confidence": 0.455},
              "packmin": {"total_score": 45.91},
              "fastrelax": {"total_score": -291.79, "fa_rep": 110.75},
              "filter_shape": {"shape_complementarity": 0.653},
              "boltz_predict": {"complex_plddt": 0.486, "ligand_iptm": 0.327}},
    "r0002": {"rfd3_design": {"ss_fraction": 0.896},
              "ligandmpnn_design": {"overall_confidence": 0.494, "ligand_confidence": 0.57},
              "packmin": {"total_score": 231.797},
              "fastrelax": {"total_score": -466.539, "fa_rep": 195.602},
              "filter_shape": {"shape_complementarity": 0.731},
              "boltz_predict": {"complex_plddt": 0.678, "ligand_iptm": 0.844}},
    "r0003": {"rfd3_design": {"ss_fraction": 0.879},
              "ligandmpnn_design": {"overall_confidence": 0.355, "ligand_confidence": 0.4},
              "packmin": {"total_score": 140.123},
              "fastrelax": {"total_score": -503.14, "fa_rep": 183.626},
              "filter_shape": {"shape_complementarity": 0.519},
              "boltz_predict": {"complex_plddt": 0.878, "ligand_iptm": 0.905}},
    "r0004": {"rfd3_design": {"ss_fraction": 0.832},
              "ligandmpnn_design": {"overall_confidence": 0.503, "ligand_confidence": 0.548},
              "packmin": {"total_score": 99.713},
              "fastrelax": {"total_score": -352.975, "fa_rep": 133.96},
              "filter_shape": {"shape_complementarity": 0.676},
              "boltz_predict": {"complex_plddt": 0.426, "ligand_iptm": 0.493}},
    "r0005": {"rfd3_design": {"ss_fraction": 0.847},
              "ligandmpnn_design": {"overall_confidence": 0.455, "ligand_confidence": 0.474},
              "packmin": {"total_score": -7.635},
              "fastrelax": {"total_score": -204.115, "fa_rep": 71.342},
              "filter_shape": {"shape_complementarity": 0.672},
              "boltz_predict": {"complex_plddt": 0.561, "ligand_iptm": 0.489}},
}


def test_replaying_job_22702568_promotes_at_its_third_run(reg, tmp_path):
    from types import SimpleNamespace

    runs = [_results(reg, m) for m in _JOB_22702568.values()]
    assert [r.all_gates_passed for r in runs] == [False, True, False, False, True], \
        "the old rule's verdicts, reproduced from the recorded metrics"

    ex = _executor_with_memory_ledger(tmp_path)
    promoted_at = None
    for run_id, results in zip(_JOB_22702568, runs):
        assert ex._record_evidence(SimpleNamespace(signature="sig"), results) is False, \
            f"{run_id}: every tool worked, so no run is evidence against the pattern"
        if promoted_at is None and ex.trust.is_trusted("sig"):
            promoted_at = run_id
    assert promoted_at == "r0003"


def test_the_lying_mock_never_earns_trust(reg, tmp_path):
    """mock_noodle reports success and designs a noodle; `has_secondary_structure` is an
    integrity gate, so however many times it runs, it is never a clean run."""
    import json
    from types import SimpleNamespace

    bad = json.loads(pathlib.Path(
        "toolkits/mock/tools/mock_noodle/tests/noodle.bad.json").read_text())["output"]
    ex = _executor_with_memory_ledger(tmp_path)
    for _ in range(5):
        assert ex._record_evidence(SimpleNamespace(signature="sig"),
                                   _results(reg, {"mock_noodle": bad["metrics"]})) is True
    assert not ex.trust.is_trusted("sig")
