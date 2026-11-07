"""T1 - the five composition gates."""
import pathlib

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.graph import TaskGraph, TaskNode
from impress_a.compose.interlock import Scrutiny, TrustLedger
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import ExperimentIntent
from impress_a.core.spec import (
    Aim,
    Deferral,
    Spec,
    SpecObjective,
    SpecRevision,
    Stage,
    TaskMapping,
)
from impress_a.runtime.reviewer import StageReviewer
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
    led = TrustLedger(promote_after=3)
    led.record_for("sig", ["x"])
    assert Scrutiny.for_pattern(led, "sig").mark_suspect
    assert not led.on_clean_run("sig") and not led.on_clean_run("sig")
    assert led.on_clean_run("sig"), "third clean run promotes"
    assert not Scrutiny.for_pattern(led, "sig").mark_suspect
    assert led.on_failure("sig"), "failure demotes"
    assert Scrutiny.for_pattern(led, "sig").mark_suspect


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
    per-job directory under `$WORK_DIR/impress_a_runs` before launching - so the ledger
    resolved inside
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
    led = TrustLedger(promote_after=2)
    led.record_for("sig", ["x"])
    assert led.on_clean_run("sig") is False
    assert led.on_clean_run("sig") is True
    assert led.path is None


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
                          ("boltz_predict", "ligand_iptm"),
                          # Backlog G4: upstream's own calibrated PROD values, verified
                          # against `run_small_molecule_binding.py`'s PROD instance -
                          # fa_rep 100.0, score -250.0, interact -8.0, ss_fraction 0.5.
                          ("fastrelax", "total_score"),
                          ("fastrelax", "fa_rep"),
                          ("fastrelax", "interaction_energy"),
                          ("rfd3_design", "ss_fraction")}, \
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


#: What the calibrated specs require and neither recorded job measured. Supplying them is a
#: stated COUNTERFACTUAL, never a measurement: the value is chosen to pass, so that a test
#: about the trust counter is testing the trust counter. `interaction_energy` was not computed
#: by any recorded run - the adapter did not compute it at all until phase 10 - and
#: `num_models` is a count the ledger rows did not carry.
#: `sc_selector_mode` is the exception: it is not a counterfactual but a FACT about these
#: runs. 0.0 says their shape complementarity came from the historical `jump="1"` filter, so
#: those numbers are not comparable with a calibrated run's - which is the point of recording
#: the mode at all (backlog G5).
_AS_IF_MEASURED = {"fastrelax": {"interaction_energy": -12.0},
                   "rfd3_design": {"num_models": 1},
                   "filter_shape": {"sc_selector_mode": 0.0}}


def _as_if_measured(metrics: dict) -> dict:
    """A recorded run's metrics, plus the ones the calibrated gates now require."""
    return {tool: {**values, **_AS_IF_MEASURED.get(tool, {})}
            for tool, values in metrics.items()}


def test_a_recorded_job_cannot_promote_a_pattern_under_the_calibrated_gates(reg, tmp_path):
    """The point of closing backlog G4, stated as what it costs.

    Neither recorded Delta job computed `interaction_energy` - the one metric fastrelax
    reports that measures binding rather than geometry - because the adapter did not compute
    it at all. Under the calibrated gates its absence is an INTEGRITY failure, so a replay of
    job 22702568's five `6/6 tasks ok` runs demotes the pattern on every one of them.

    That is the correct reading and it is the finding: those runs were never evidence that the
    chain worked, because the chain was not measuring what the campaign was for. A gate that
    only noticed a LOW interaction energy would have let this pass as five clean runs.
    """
    from types import SimpleNamespace

    ex = _executor_with_memory_ledger(tmp_path)
    for run_id, metrics in _JOB_22702568.items():
        failed = ex._record_evidence(SimpleNamespace(signature="sig"), _results(reg, metrics))
        assert failed is True, f"{run_id}: a run that never measured binding is not clean"
    assert not ex.trust.is_trusted("sig")


def test_the_promotion_rule_still_promotes_at_the_third_clean_run(reg, tmp_path):
    """Decision 0013's arithmetic, unchanged by the calibration.

    Replayed with `_as_if_measured`, which is a stated counterfactual rather than data: the
    recorded runs did not measure `interaction_energy`, and a passing value is supplied so
    that what is under test is the trust counter rather than the gate inventory. The original
    prediction - failure/clean/failure/failure/clean under the OLD every-gate rule, promoting
    nothing, and promotion at r0003 under 0013 - still holds for the same five runs.
    """
    from types import SimpleNamespace

    runs = [_results(reg, _as_if_measured(m)) for m in _JOB_22702568.values()]
    assert [r.all_gates_passed for r in runs] == [False] * 5, (
        "NOT ONE of the five passes every gate now. Under the old every-gate rule two of "
        "them did (r0002, r0005), and the difference is the fold bar: at 0.5 their 0.678 and "
        "0.561 passed, and at upstream's own 0.75 neither does. Five runs this project "
        "recorded as `6/6 tasks ok` contain no design the reference would have accepted, "
        "which is the gap backlog G4 was about, priced")

    ex = _executor_with_memory_ledger(tmp_path)
    promoted_at = None
    for run_id, results in zip(_JOB_22702568, runs, strict=True):
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


# Per-task metrics of job 22726105, from its jobs/ledger.jsonl. It promoted after r0002 as
# predicted, ran r0003-r0004 trusted - the first trusted runs on Delta - and was then demoted
# by packmin's old `total_score <= 1000` integrity bound over r0004's +1064.5, a pose that
# relaxed normally to -336.0. That bound is gone; fastrelax converging is the judgement.
_JOB_22726105 = {
    "r0001": {"rfd3_design": {"ss_fraction": 0.878},
              "ligandmpnn_design": {"overall_confidence": 0.455, "ligand_confidence": 0.479},
              "packmin": {"total_score": 261.318},
              "fastrelax": {"total_score": -295.038, "fa_rep": 121.822},
              "filter_shape": {"shape_complementarity": 0.681},
              "boltz_predict": {"complex_plddt": 0.533, "ligand_iptm": 0.421}},
    "r0002": {"rfd3_design": {"ss_fraction": 0.868},
              "ligandmpnn_design": {"overall_confidence": 0.45, "ligand_confidence": 0.509},
              "packmin": {"total_score": 482.7},
              "fastrelax": {"total_score": -466.109, "fa_rep": 175.197},
              "filter_shape": {"shape_complementarity": 0.651},
              "boltz_predict": {"complex_plddt": 0.475, "ligand_iptm": 0.389}},
    "r0003": {"rfd3_design": {"ss_fraction": 0.854},
              "ligandmpnn_design": {"overall_confidence": 0.377, "ligand_confidence": 0.431},
              "packmin": {"total_score": 45.634},
              "fastrelax": {"total_score": -502.67, "fa_rep": 191.993},
              "filter_shape": {"shape_complementarity": 0.577},
              "boltz_predict": {"complex_plddt": 0.545, "ligand_iptm": 0.569}},
    "r0004": {"rfd3_design": {"ss_fraction": 0.849},
              "ligandmpnn_design": {"overall_confidence": 0.507, "ligand_confidence": 0.589},
              "packmin": {"total_score": 1064.49},
              "fastrelax": {"total_score": -336.022, "fa_rep": 119.133},
              "filter_shape": {"shape_complementarity": 0.582},
              "boltz_predict": {"complex_plddt": 0.498, "ligand_iptm": 0.448}},
    "r0005": {"rfd3_design": {"ss_fraction": 0.875},
              "ligandmpnn_design": {"overall_confidence": 0.432, "ligand_confidence": 0.475},
              "packmin": {"total_score": 37.245},
              "fastrelax": {"total_score": -211.53, "fa_rep": 80.048},
              "filter_shape": {"shape_complementarity": 0.677},
              "boltz_predict": {"complex_plddt": 0.417, "ligand_iptm": 0.382}},
}


def test_replaying_job_22726105_stays_trusted_once_promoted(reg, tmp_path):
    from types import SimpleNamespace

    ex = _executor_with_memory_ledger(tmp_path)
    ex.trust.on_clean_run("sig")      # the site ledger going in: one clean run (22702568 r0005)
    trusted_after = {}
    for run_id, metrics in _JOB_22726105.items():
        # `_as_if_measured` for the reason given at its definition: this job did not compute
        # `interaction_energy` either, and what is under test here is that a promoted pattern
        # is no longer demoted by a pre-relax score - not the gate inventory.
        assert ex._record_evidence(SimpleNamespace(signature="sig"),
                                   _results(reg, _as_if_measured(metrics))) is False, \
            f"{run_id}: every tool worked and every relax converged"
        trusted_after[run_id] = ex.trust.is_trusted("sig")
    assert trusted_after == {"r0001": False, "r0002": True, "r0003": True,
                             "r0004": True, "r0005": True}, \
        "promoted after r0002 as observed - and no longer demoted by r0004's pre-relax score"


def test_relative_path_params_resolve_against_the_campaign_yaml(tmp_path, monkeypatch):
    """The Delta launcher cds into a per-job directory before loading the spec, so a
    `*_path` param relative to the CWD would break there - and an absolute one ties the
    spec to one checkout. Relative means relative to the YAML; absolute is left alone."""
    from impress_a.cli import load_spec

    src = pathlib.Path("campaigns/mock-stabilize.yaml").read_text()
    spec_file = tmp_path / "c.yaml"
    spec_file.write_text(src + "\nparams:\n  rfd3_design: {input_spec_path: data/in.json, n: 3}\n"
                         "  packmin: {ligand_params_path: /abs/L.params}\n")
    monkeypatch.chdir("/")
    params = load_spec(spec_file).params
    assert params["rfd3_design"]["input_spec_path"] == str(tmp_path / "data/in.json")
    assert params["rfd3_design"]["n"] == 3
    assert params["packmin"]["ligand_params_path"] == "/abs/L.params"


def test_shipped_campaigns_carry_no_absolute_checkout_paths():
    """Campaign data lives beside the YAML; an absolute path into one user's checkout
    breaks every other checkout and leaks an allocation's directory layout."""
    for f in pathlib.Path("campaigns").glob("*.yaml"):
        assert "/work/" not in f.read_text(), f
    assert "/work/" not in pathlib.Path("campaigns/data/alr/ALR_binder_design.json").read_text()


# ---------------------------------------------------------------------------
# Asserted trust (phase 3 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def test_asserted_trust_skips_the_cap_and_the_forced_dry_run(tmp_path):
    """A pre-loaded Toolkit of proven Tasks should not re-earn trust at runtime.

    Promotion costs three consecutive clean runs under a forced dry-run, a 10%-of-available
    cost cap and one-instance-in-flight. For a wide pattern that is not merely wasteful but
    impossible: replica multiplicity is part of the signature, so width 4 can never reach three
    clean runs under a realistic budget while the one-in-flight rule serialises it (backlog
    A10).
    """
    led = TrustLedger.load(tmp_path / "cuda.jsonl")
    led.assert_trusted("sig", ["rfd3_design"], reason="proven elsewhere", by="tester")

    s = Scrutiny.for_pattern(led, "sig")
    assert s.trusted and not s.force_dry_run and not s.mark_suspect
    assert s.cost_cap_fraction is None


def test_asserted_trust_is_distinguishable_from_earned_trust(tmp_path):
    """Or "this pattern earned trust over three clean runs" becomes uncheckable.

    Three forged `clean` events would also produce a trusted record, and would be
    indistinguishable from evidence afterwards - which is why the ledger has a distinct event
    kind rather than a documented convention.
    """
    led = TrustLedger.load(tmp_path / "cuda.jsonl")
    led.assert_trusted("granted", ["x"], reason="proven elsewhere", by="tester",
                       git_sha="abc123")
    led.record_for("earned", ["y"])
    for _ in range(3):
        led.on_clean_run("earned")

    assert led.patterns["granted"].trusted and led.patterns["granted"].asserted
    assert led.patterns["granted"].asserted_reason == "proven elsewhere"
    assert led.patterns["granted"].git_sha == "abc123"
    assert led.patterns["earned"].trusted and not led.patterns["earned"].asserted
    assert led.patterns["earned"].clean_runs == 3
    assert led.patterns["granted"].clean_runs == 0, \
        "an assertion is not evidence, so it must not look like three runs of it"


def test_an_assertion_accumulates_no_phantom_promotion(tmp_path):
    led = TrustLedger.load(tmp_path / "cuda.jsonl")
    led.assert_trusted("sig", ["x"], reason="proven")
    assert led.on_clean_run("sig") is False, "already trusted; nothing to promote"
    assert led.patterns["sig"].clean_runs == 0


def test_an_asserted_pattern_still_demotes_and_does_not_survive_it(tmp_path):
    """Demotion applies, and is a FINDING: it says the assertion was wrong.

    The in-memory record and a re-fold of the log must agree, or a pattern is trusted in one
    process and not in the next.
    """
    path = tmp_path / "cuda.jsonl"
    led = TrustLedger.load(path)
    led.assert_trusted("sig", ["x"], reason="proven")
    assert led.on_failure("sig") is True, "demoting an asserted pattern is a demotion"
    live = (led.patterns["sig"].trusted, led.patterns["sig"].asserted)

    refolded = TrustLedger.load(path)
    assert live == (False, False)
    assert live == (refolded.patterns["sig"].trusted, refolded.patterns["sig"].asserted)
    assert refolded.patterns["sig"].demotions == 1


def test_an_assertion_without_a_reason_is_refused(tmp_path):
    """The reason is the justification on the record, and what a later reader will ask for."""
    led = TrustLedger.load(tmp_path / "cuda.jsonl")
    with pytest.raises(ValueError, match="needs a reason"):
        led.assert_trusted("sig", ["x"], reason="   ")
    assert "sig" not in led.patterns or not led.patterns["sig"].trusted


def test_revoking_withdraws_an_assertion(tmp_path):
    led = TrustLedger.load(tmp_path / "cuda.jsonl")
    led.assert_trusted("sig", ["x"], reason="proven")
    assert led.revoke("sig", reason="superseded") is True
    assert not led.patterns["sig"].trusted and not led.patterns["sig"].asserted
    assert led.revoke("sig", reason="again") is False, "nothing left to revoke"


def test_asserting_at_one_width_does_not_trust_another(reg):
    """Backlog A10, as a property of the signature rather than a footnote.

    The pattern signature includes replica multiplicity, so trust earned - or granted - at
    width 1 does not transfer to width 4. `impress-a trust --replicas` therefore takes the
    widths a campaign will actually run.
    """
    composer = Composer(reg)
    narrow = composer.compose(ExperimentIntent(goal="g", stages=["mock_generate"], replicas=1))
    wide = composer.compose(ExperimentIntent(goal="g", stages=["mock_generate"], replicas=4))
    assert narrow.pattern_signature() != wide.pattern_signature()

    led = TrustLedger()
    led.assert_trusted(narrow.pattern_signature(), ["mock_generate"], reason="proven at 1")
    assert led.is_trusted(narrow.pattern_signature())
    assert not led.is_trusted(wide.pattern_signature()), \
        "asserting at width 1 must not trust width 4"


# ---------------------------------------------------------------------------
# The Reviewer (phase 3 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def _spec_with(*objectives):
    aim = Aim(statement="test aim")
    objs = [SpecObjective(aim=aim.id, statement=s, targets=[m], **kw)
            for s, m, kw in objectives]
    spec = Spec()
    spec.apply(SpecRevision(new_aims=[aim], new_objectives=objs))
    return spec, objs


def _reviewer(reg):
    budget = BudgetLedger(limits={"gpu_hours": 10.0, "cpu_hours": 10.0})
    return StageReviewer(Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1), budget),
                         budget)


def _stage(objective_ids, tools=("mock_generate", "mock_design"), **kw):
    return Stage(tasks=[TaskMapping(task_id=f"r0_s{i}_{t}", tool=t, lineage=0,
                                    objectives=list(objective_ids))
                        for i, t in enumerate(tools)], **kw)


async def test_the_reviewer_refuses_a_stage_that_leaves_a_ready_objective_unanswered(reg):
    """Backlog A8's shape: a gate, not a `log.warning`.

    On job 22675512 a budget correction truncated `boltz_predict` off the chain, taking the
    only producer of two of four objectives with it. Nothing refused it, the run was
    unwinnable from the moment it was admitted, and the admitted graph recorded
    `rejected: null`. A warning in a log nobody reads during an allocation is not a gate.
    """
    spec, objs = _spec_with(("make a backbone", "ss_fraction", {}),
                            ("fold it", "iptm", {}))
    stage = _stage([objs[0].id])        # answers the first, ignores the second

    failure = _reviewer(reg).coverage(stage, spec)
    assert failure is not None and failure.gate == "coverage"
    assert objs[1].id in failure.detail["missing"]
    assert "neither planned nor deferred" in failure.reason


async def test_the_reviewer_accepts_a_deferral_in_place_of_a_task(reg):
    """A Deferral is an answer. Demanding a Task for blocked work would force the invention
    this gate exists to prevent."""
    spec, objs = _spec_with(("make a backbone", "ss_fraction", {}),
                            ("fold it", "iptm", {}))
    stage = _stage([objs[0].id])
    stage.deferrals = [Deferral(objective=objs[1].id, reason="waits on the backbone",
                                waiting_on=[objs[0].id])]

    assert _reviewer(reg).coverage(stage, spec) is None


async def test_the_reviewer_does_not_demand_a_task_for_a_blocked_objective(reg):
    """`ready()`, not `open_objectives()`: an objective whose dependency is unmet cannot be
    planned, so requiring it would make every Stage impossible until the last one."""
    spec, objs = _spec_with(("first", "ss_fraction", {}), ("second", "iptm", {}))
    spec.objectives[objs[1].id].depends_on = [objs[0].id]
    stage = _stage([objs[0].id])

    assert _reviewer(reg).coverage(stage, spec) is None, \
        "the second objective is blocked, so it is not the Planner's to answer yet"


async def test_the_reviewer_refuses_a_task_that_serves_no_live_objective(reg):
    """A task working only for DELETED objectives belongs in `cancels`, not in `tasks`.

    This is the other half of what makes cancellation decidable: `objectives` is a list, so a
    task serving one live objective and three dead ones is still wanted.
    """
    spec, objs = _spec_with(("one", "ss_fraction", {}), ("two", "iptm", {}))
    stage = _stage([objs[0].id])
    stage.deferrals = [Deferral(objective=objs[1].id)]
    rev = _reviewer(reg)
    assert rev.coverage(stage, spec) is None

    spec.apply(SpecRevision(deleted=[objs[0].id]))
    failure = rev.coverage(stage, spec)
    assert failure is not None and "only deleted objectives" in failure.reason

    # But a task with one live objective among dead ones is still legitimate.
    stage.tasks[0].objectives = [objs[0].id, objs[1].id]
    stage.tasks[1].objectives = [objs[0].id, objs[1].id]
    stage.deferrals = []
    assert rev.coverage(stage, spec) is None


async def test_the_reviewer_refuses_an_objective_that_is_not_in_the_applied_spec(reg):
    """A Planner cannot widen its own coverage by naming objectives it imagined.

    Not trusting that claim is the Reviewer's entire purpose, and it is why the Spec has one
    writer on the execution side: in phase 7 a remote Planner must not be able to smuggle a
    Spec revision in with a Stage.
    """
    spec, objs = _spec_with(("one", "ss_fraction", {}))
    stage = _stage([objs[0].id, "o-invented"])

    failure = _reviewer(reg).coverage(stage, spec)
    assert failure is not None and failure.detail["unknown"] == ["o-invented"]


async def test_the_reviewer_marks_a_budget_refusal_transient(reg):
    """Contention is a property of the moment, not of the graph.

    Without that distinction a policy answers contention by mutilating its intent - dropping
    replicas, truncating stages - in response to what OTHER runs are consuming, which reads as
    the policy quietly degrading.
    """
    budget = BudgetLedger(limits={"gpu_hours": 0.001})
    rev = StageReviewer(
        Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1), budget), budget)
    graph = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=["mock_generate"], replicas=1))

    failure = rev.affordable(graph)
    assert failure is not None and failure.gate == "budget" and failure.transient is True


# ---------------------------------------------------------------------------
# Gate 6: tool delivery (backlog E1).
# ---------------------------------------------------------------------------

def test_gate_6_refuses_a_mock_tool_under_tool_delivery_real(reg):
    """Backlog E1, finally wired - and a gate rather than a guard, deliberately.

    `sites/*.yaml` carried a `tool_delivery` switch read by no code from the day it was
    written, and it is the switch that would have refused the documented mock-chain-on-a-GPU
    run. A mock chain completes `6/6 tasks ok` with plausible metrics and invented designs;
    `mock_noodle` goes further and reports a confident `designability` for a structure with no
    secondary structure, so such a run does not merely waste an allocation - it produces
    numbers a reader would act on.

    A gate and not `RuleCorrectionsPolicy(forbid_tools=...)` because `--no-guard` must not be
    able to switch off "is this real".
    """
    budget = BudgetLedger(limits={"gpu_hours": 100.0, "cpu_hours": 100.0})
    site = SiteCaps(gpu_api="cuda", gpus_per_node=4)
    mock_graph = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=["mock_generate", "mock_design"], replicas=1), "r")
    real_graph = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=["rfd3_design", "ligandmpnn_design"], replicas=1),
        "r")

    # `any` is the default, so every existing campaign is unaffected.
    for graph in (mock_graph, real_graph):
        assert Validator(reg, site, budget)._g6_delivery(graph) is None

    failure = Validator(reg, site, budget, tool_delivery="real")._g6_delivery(mock_graph)
    assert failure is not None and failure.gate == "tool_delivery"
    assert failure.detail["offending_tools"] == ["mock_design", "mock_generate"]
    assert Validator(reg, site, budget,
                     tool_delivery="real")._g6_delivery(real_graph) is None

    # And the other way, so a mock test tier cannot accidentally reach a real tool.
    assert Validator(reg, site, budget,
                     tool_delivery="mock")._g6_delivery(real_graph) is not None
    assert Validator(reg, site, budget,
                     tool_delivery="mock")._g6_delivery(mock_graph) is None


def test_gate_6_reads_the_declared_toolkit_not_the_tool_id(reg):
    """A name beginning `mock_` is a convention; the toolkit a spec declares is a fact.

    A real tool named `mock_affinity_predictor` would be refused by a prefix check, and a
    mock one named `fast_screen` would be admitted. `ToolSpec.toolkit` is what the registry
    loaded it under.
    """
    mock_tools = {t for t in reg.ids() if reg.get(t).toolkit == "mock"}
    assert mock_tools, "precondition: the mock toolkit is loaded"
    assert all(reg.get(t).toolkit != "mock" for t in reg.ids() if t not in mock_tools)
    # The one that would break a prefix check in the other direction, if it ever exists.
    assert not [t for t in reg.ids()
                if t.startswith("mock_") and reg.get(t).toolkit != "mock"]


def test_every_delta_campaign_declares_real_tool_delivery():
    """The gate is worth nothing on a campaign that does not ask for it.

    Checked here rather than left to review, because the failure it prevents is a GPU
    allocation producing invented designs and the cost of forgetting is one allocation.
    """
    import yaml

    from impress_a.cli import load_spec

    for path in sorted(pathlib.Path("campaigns").glob("delta-*.yaml")):
        doc = yaml.safe_load(path.read_text())
        assert doc.get("tool_delivery") == "real", f"{path.name} does not declare it"
        assert load_spec(str(path)).tool_delivery == "real", \
            f"{path.name}: declared but did not reach the spec"


def test_no_policy_answers_a_rejection_by_truncating_its_chain():
    """Job 22675512, refused by construction - and it was defeating a second rule too.

    Dropping the tail to fit a budget took `boltz_predict` off that campaign's chain, solely
    because it is listed last, and `boltz_predict` is the only producer of `complex_plddt` and
    `ligand_iptm` - two of its four objectives. The run was unwinnable from the moment it was
    admitted and the admitted graph records `rejected: null`.

    Removing it exposed the second effect, which nothing had noticed: truncation produces a
    different SHAPE, so it also produced a different pattern signature - and an instance
    refused by the interlock's one-instance-in-flight rule was then admitted as a different
    pattern. Two concurrency tests in `test_campaign.py` were passing because of it.
    """
    import ast
    import inspect
    import textwrap

    from impress_a.policy.explicit import ThresholdPolicy
    from impress_a.policy.oracle import OraclePolicy

    for cls in (ThresholdPolicy, OraclePolicy):
        # The whole function, dedented and parsed. A docstring is a `Constant` and never a
        # `Subscript`, so there is no need to cut it out - and cutting it out by splitting on
        # triple quotes is what broke this test's first version.
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls.on_rejected)))
        slices = [n for n in ast.walk(tree) if isinstance(n, ast.Subscript)
                  and isinstance(n.slice, ast.Slice)]
        assert slices == [], (
            f"{cls.__name__}.on_rejected slices a sequence - the only thing it used to slice "
            f"was `intent.stages[:-1]`, and dropping a stage is what this forbids")
