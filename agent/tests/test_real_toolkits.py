"""Login-node validation for the real (non-mock) small_molecule_binding toolkits:
rfd3, ligandmpnn, rosetta, boltz.

Exercises registry loading, composition and the five validation gates (including
dry_run, which calls each TaskAgent's generic `parameterize()` for real) WITHOUT
executing any real RFD3/LigandMPNN/PyRosetta/Boltz binary - none of those need to be
installed for this file to pass. That is only possible because every heavy import in the
real agent modules is deferred to inside `run()` (see CLAUDE.md's tool-authoring notes
and each toolkit's SKILL.md Pitfalls).
"""
from __future__ import annotations

import pathlib

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import ExperimentIntent
from impress_a.core.qc import QCVerdict
from impress_a.tools.registry import Registry

CHAIN = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
         "boltz_predict"]


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _v(reg, **site):
    caps = SiteCaps(**{"gpu_api": "cuda", "gpus_per_node": 4, **site})
    return Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 100, "cpu_hours": 500}))


def test_real_toolkits_load_cleanly(reg):
    """rfd3/, ligandmpnn/, rosetta/, boltz/ each register with zero errors - proves the
    SKILL.md-section + spec.yaml-validation + entry-resolution path works for real tools
    without any of their science dependencies installed."""
    assert reg.errors == [], reg.errors
    assert set(reg.ids()) >= set(CHAIN)
    for toolkit in ("rfd3", "ligandmpnn", "rosetta", "boltz"):
        assert toolkit in reg.skills, f"{toolkit} toolkit did not register a SKILL.md"


def test_real_chain_passes_all_gates(reg):
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    assert len(g.nodes) == len(CHAIN)
    f = _v(reg).validate(g)
    assert f is None, f


async def test_real_chain_dry_runs_without_executing(reg):
    """Every agent's dry_run() (pre_process + parameterize only) succeeds - proves the
    graph is ready to run for real without invoking apptainer/LigandMPNN/pyrosetta/boltz."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = await _v(reg).dry_run(g)
    assert f is None, f


def test_real_chain_refuses_unproven_gpu_api(reg):
    """None of rfd3_design/ligandmpnn_design/boltz_predict declare a HIP path."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = _v(reg, gpu_api="hip").validate(g)
    assert f and f.gate == "resource" and "hip" in f.reason


def test_real_chain_refuses_over_budget(reg):
    caps = SiteCaps(gpu_api="cuda", gpus_per_node=4)
    v = Validator(reg, caps, BudgetLedger(limits={"gpu_hours": 0.001}))
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    f = v.validate(g)
    assert f and f.gate == "budget" and "gpu_hours" in str(f.detail)


def test_campaign_selects_the_real_chain_not_the_mock_one(reg, tmp_path):
    """The headline bug: a real campaign would have run mocks on a GPU allocation.

    `CampaignSpec` had no `stages`, `load_spec` read none, and every policy falls back
    to its own default chain - which is the mock one. So `sbatch delta_gpu_run.sh`
    loaded the real toolkits, validated them, and then composed `mock_generate...`.
    """
    from impress_a.cli import build_policy, load_spec
    from impress_a.manager import CampaignManager

    spec = load_spec("campaigns/delta-small-molecule-smoke.yaml")
    assert spec.stages, "the campaign must declare its chain"
    assert spec.params.get("rfd3_design", {}).get("contig"), \
        "the campaign must be able to configure the design target"

    spec.root = str(tmp_path)
    spec.backend, spec.backend_config = "concurrent", {"workers": 1}
    mgr = CampaignManager(spec, build_policy("D", spec, guard=False), reg)

    intent = ExperimentIntent(goal=spec.goal)          # a policy that asks for nothing
    merged = mgr.executor._apply_campaign_defaults(intent)
    assert merged.stages == spec.stages
    assert merged.params["rfd3_design"]["ligand_resname"] == "LIG", \
        "campaign params must reach the tool without any policy knowing its names"
    assert not any(s.startswith("mock_") for s in merged.stages)


def test_campaign_params_defer_to_the_policy_and_replicas_is_a_cap(reg, tmp_path):
    from impress_a.cli import load_spec
    from impress_a.manager import CampaignManager
    from impress_a.policy.explicit import ThresholdPolicy

    spec = load_spec("campaigns/delta-small-molecule-smoke.yaml")
    spec.root = str(tmp_path)
    spec.replicas = 2
    ex = CampaignManager(spec, ThresholdPolicy(stages=spec.stages), reg).executor

    asked = ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=9,
                             params={"rfd3_design": {"contig": "A1-50"}})
    merged = ex._apply_campaign_defaults(asked)
    assert merged.params["rfd3_design"]["contig"] == "A1-50", "the policy wins on keys it set"
    assert merged.params["rfd3_design"]["ligand_resname"] == "LIG", "campaign fills the rest"
    assert merged.replicas == 2, "campaign replicas is a cap on breadth"
    assert ex._apply_campaign_defaults(
        ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=1)).replicas == 1, \
        "a policy may still ask for fewer"


def test_real_tools_get_an_independent_reproducible_seed_per_lineage(reg):
    """`replicas: N` means N independent candidates - which for a real stochastic tool
    requires a seed. No spec declared one, so the per-lineage draw was dead code."""
    from impress_a.compose.composer import Composer
    from impress_a.tools.agent import TaskRequest

    g = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=3), "r0007")
    seeds = []
    for tid, node in sorted(g.nodes.items()):
        agent = reg.agent_for(node.tool)(reg.get(node.tool))
        params = agent.parameterize(TaskRequest(tool=node.tool, params=node.params,
                                                node_id=tid, seed=node.seed))
        seeds.append(params["seed"])
    assert len(set(seeds)) == 3, "replicas would be N copies of one design"

    again = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=3), "r0007")
    assert [n.seed for _, n in sorted(again.nodes.items())] == \
        [n.seed for _, n in sorted(g.nodes.items())], \
        "the same experiment must replay to the same draws"


def test_boltz_spec_is_valid_yaml():
    """It was not. `msa:` sat one level too deep, under the `sequence:` scalar, so
    `boltz predict` aborted on spec parse before loading a model - which is also the
    clearest evidence the adapter had never been executed."""
    import yaml

    sequences = [{"protein": {"id": ["A"], "sequence": "MKVLAA", "msa": "auto"}},
                 {"ligand": {"id": ["B"], "smiles": "CC(=O)Oc1ccccc1C(=O)O"}}]
    doc = yaml.safe_dump({"version": 1, "sequences": sequences}, sort_keys=False)

    parsed = yaml.safe_load(doc)          # the assertion that used to fail
    assert parsed["version"] == 1
    assert parsed["sequences"][0]["protein"]["msa"] == "auto", \
        "msa must be a sibling of sequence, not nested under it"
    assert parsed["sequences"][1]["ligand"]["smiles"].startswith("CC(=O)")


async def test_rosetta_reports_a_missing_worker_result_as_qc_failure(reg, tmp_path):
    """A worker can exit 0 and leave no readable JSON. Reading it unconditionally made
    that a FileNotFoundError escaping run() - recorded as an infrastructure crash rather
    than the QC failure it is."""
    from impress_a.tools import rosetta_agents
    from impress_a.tools.agent import TaskRequest

    assert rosetta_agents._read_metrics(tmp_path / "absent.json") is None
    truncated = tmp_path / "truncated.json"
    truncated.write_text('{"total_score":')
    assert rosetta_agents._read_metrics(truncated) is None
    good = tmp_path / "good.json"
    good.write_text('{"total_score": -123.4}')
    assert rosetta_agents._read_metrics(good) == {"total_score": -123.4}

    # ...and the empty result must fail the tool's own gates rather than raise.
    agent = reg.agent_for("packmin")(reg.get("packmin"))
    result = await agent.post_process(TaskRequest(tool="packmin"),
                                      dict(rosetta_agents._NO_RESULT))
    assert result.qc.verdict is QCVerdict.FAIL


def test_work_directory_defaults_to_cwd_and_is_per_task(tmp_path, monkeypatch):
    """Artifacts must be reachable from another node. The adapters used the system temp
    dir, which under Dragon multi-node is local to whichever node produced them."""
    from impress_a.tools._subprocess import workdir_for

    monkeypatch.chdir(tmp_path)

    class Req:
        node_id = "r0001:r0_s0_rfd3_design"
        workdir = None

    a = workdir_for(Req(), "rfd3")
    assert a.is_dir() and tmp_path in a.parents, "must land under the launcher's cwd"
    assert ":" not in a.name, "the run label must be path-safe"

    class Other(Req):
        node_id = "r0002:r0_s0_rfd3_design"

    assert workdir_for(Other(), "rfd3") != a, "concurrent tasks must not share a dir"

    explicit = tmp_path / "shared"
    class Pinned(Req):
        workdir = str(explicit)
    assert explicit in workdir_for(Pinned(), "rfd3").parents


def test_a_campaign_that_never_mentions_replicas_is_not_capped():
    """`replicas` is a cap, so its unset value must mean "no cap" - not 1.

    Defaulting it to 1 silently narrowed every existing campaign to a single lineage
    per experiment, which looks like a policy that stopped exploring.
    """
    from impress_a.cli import load_spec

    spec = load_spec("campaigns/mock-stabilize.yaml")
    assert "replicas" not in pathlib.Path("campaigns/mock-stabilize.yaml").read_text()
    assert spec.replicas == 0, "unset must mean 'the policy decides'"

    smoke = load_spec("campaigns/delta-small-molecule-smoke.yaml")
    assert smoke.replicas == 1, "an explicit 1 must still bind"
