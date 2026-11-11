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

import json
import pathlib
from pathlib import Path
from typing import Any

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.artifacts import Property, PropertySource
from impress_a.core.budget import BudgetLedger
from impress_a.core.data import DataRegistry
from impress_a.core.decision import CampaignObservation, ExperimentIntent
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.qc import QCVerdict
from impress_a.core.results import RunOutcome, RunState, TaskOutcome
from impress_a.core.spec import ObjectiveStatus, SpecRevision
from impress_a.core.tree import DesignNode
from impress_a.core.types import ArtifactType
from impress_a.policy.planner import PlanningContext
from impress_a.policy.planners import AgenticPlanner, ThresholdPlanner
from impress_a.policy.specifier import SpecEvidence
from impress_a.policy.specifiers import ThresholdSpecifier
from impress_a.tools._ensemble import member_index, pair_by_index, select_best
from impress_a.tools.ligandmpnn_agents import _parse_all_confidences, _parse_confidence
from impress_a.tools.registry import Registry
from impress_a.tools.view import view_of

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

    `CampaignSpec` had no `stages`, `load_spec` read none, and every reasoner falls back
    to its own default chain - which is the mock one. So `sbatch delta_gpu_run.sh`
    loaded the real toolkits, validated them, and then composed `mock_generate...`.
    """
    from impress_a.cli import build_roles, load_spec
    from impress_a.manager import CampaignManager

    spec = load_spec("campaigns/delta-small-molecule-smoke.yaml")
    assert spec.stages, "the campaign must declare its chain"
    assert spec.params.get("rfd3_design", {}).get("input_spec_path"), \
        "the campaign must be able to configure the design target"

    spec.root = str(tmp_path)
    spec.backend, spec.backend_config = "concurrent", {"workers": 1}
    mgr = CampaignManager(spec, build_roles("D", spec, guard=False), reg)

    intent = ExperimentIntent(goal=spec.goal)          # a reasoner that asks for nothing
    merged = mgr.executor._apply_campaign_defaults(intent)
    assert merged.stages == spec.stages
    assert merged.params["rfd3_design"]["input_spec_path"] == \
        spec.params["rfd3_design"]["input_spec_path"], \
        "campaign params must reach the tool without any policy knowing its names"
    assert not any(s.startswith("mock_") for s in merged.stages)


def test_campaign_params_defer_to_the_reasoner_and_replicas_is_a_cap(reg, tmp_path):
    from impress_a.cli import build_roles, load_spec
    from impress_a.manager import CampaignManager

    spec = load_spec("campaigns/delta-small-molecule-smoke.yaml")
    spec.root = str(tmp_path)
    spec.replicas = 2
    ex = CampaignManager(spec, build_roles("D", spec, guard=False), reg).executor

    asked = ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=9,
                             params={"rfd3_design": {"input_spec_path": "/tmp/other.json"}})
    merged = ex._apply_campaign_defaults(asked)
    assert merged.params["rfd3_design"]["input_spec_path"] == "/tmp/other.json", \
        "the reasoner wins on keys it set"
    assert merged.params["rfd3_design"]["num_designs"] == \
        spec.params["rfd3_design"]["num_designs"], "campaign fills the rest"
    assert merged.replicas == 2, "campaign replicas is a cap on breadth"
    assert ex._apply_campaign_defaults(
        ExperimentIntent(goal="g", stages=["rfd3_design"], replicas=1)).replicas == 1, \
        "a reasoner may still ask for fewer"


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


async def test_rfd3_agent_uses_the_real_hydra_contract(reg, tmp_path, monkeypatch):
    """rfd3's real CLI (verified against the installed rfd3.cli:design) takes Hydra
    `key=value` overrides, never `--flag` options - `--config`/`--out` are not real and
    would fail Hydra's override parsing immediately."""
    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.chdir(tmp_path)

    captured: dict[str, Any] = {}

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        captured["cmd"], captured["env"] = cmd, env
        return "", ""

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design")
    params = agent.parameterize(TaskRequest(
        tool="rfd3_design", node_id=req.node_id,
        params={"input_spec_path": "/fake/inputs.json", "num_designs": 3,
                "diffusion_steps": 42, "seed": 7}))
    await agent.run(req, params)

    cmd = captured["cmd"]
    # Positions are not asserted: the apptainer flag list is not fixed-width (see the
    # bind test below). What must hold is the order of the three fixed tokens
    # and that every apptainer flag precedes the image.
    assert cmd[0] == "apptainer" and cmd[1] == "exec"
    assert "--nv" in cmd
    sif = cmd.index("/fake/foundry.sif")
    assert cmd[sif + 1:sif + 3] == ["rfd3", "design"], \
        "the image must be the last apptainer argument, followed by the command"
    assert all(a.startswith("-") or a == "exec" or cmd[i - 1].startswith("-")
               for i, a in enumerate(cmd[2:sif], start=2)), \
        "only flags and their values may sit between `exec` and the image"
    overrides = cmd[sif + 3:]
    assert not any(o.startswith(("--config", "--out")) for o in overrides), \
        "these flags do not exist on the real CLI"
    assert "inputs=/fake/inputs.json" in overrides
    assert "skip_existing=False" in overrides
    # False, against the CLI's own default: trajectories were 99.4% of each output dir
    # upstream and nothing here reads them. If this ever flips back, a campaign's
    # footprint goes from ~3.8 GB to ~30 GB with no change in what is measured.
    assert "dump_trajectories=False" in overrides
    assert "prevalidate_inputs=True" in overrides
    assert "diffusion_batch_size=3" in overrides
    assert "inference_sampler.num_timesteps=42" in overrides
    assert "seed=7" in overrides
    assert any(o.startswith("out_dir=") for o in overrides)


async def test_rfd3_resolves_a_relative_design_input_against_its_spec(reg, monkeypatch, tmp_path):
    """The checked-in ALR spec names its scaffold relative to itself. rfd3 runs from the job
    directory, so the agent hands it a resolved copy in the task workdir; the original file
    is not touched."""
    import json

    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    data = tmp_path / "campaigns" / "data"
    data.mkdir(parents=True)
    spec_file = data / "inputs.json"
    spec_file.write_text(json.dumps({"partial": {"input": "pdbs/x.pdb", "length": "70-170"}}))
    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.setenv("WORK_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        captured["cmd"] = cmd
        return "", ""

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)
    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design",
                      params={"input_spec_path": str(spec_file)})
    await agent.run(req, agent.parameterize(req))

    inputs = next(a for a in captured["cmd"] if a.startswith("inputs="))[len("inputs="):]
    assert inputs != str(spec_file), "a relative input must not reach rfd3 as-is"
    assert json.loads(pathlib.Path(inputs).read_text())["partial"]["input"] == \
        str(data / "pdbs/x.pdb")
    assert json.loads(spec_file.read_text())["partial"]["input"] == "pdbs/x.pdb"


async def test_rfd3_binds_both_trees_into_the_container(reg, monkeypatch, tmp_path):
    """apptainer binds $HOME, /tmp and the CWD - and nothing else.

    Two trees have to reach the container and they are not siblings: `out_dir=` is under
    $WORK_DIR on NVMe, while `inputs=` points into the repo, which stayed on /work/hdd.
    The reference pipeline binds only $WORK_DIR because its checkout moved there too, and
    IMPRESS 3c7c67d is the commit where binding the wrong single tree made every input
    JSON raise FileNotFoundError inside the container. Binding one of ours would
    reproduce that for the other.
    """
    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    work_dir = tmp_path / "nvme"
    repo = tmp_path / "hdd" / "impress_a" / "campaigns"
    repo.mkdir(parents=True)
    (repo / "inputs.json").write_text("{}")
    work_dir.mkdir()

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.setenv("WORK_DIR", str(work_dir))
    monkeypatch.chdir(work_dir)

    captured: dict[str, Any] = {}

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        captured["cmd"], captured["env"] = cmd, env
        return "", ""

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design")
    params = agent.parameterize(TaskRequest(
        tool="rfd3_design", node_id=req.node_id,
        params={"input_spec_path": str(repo / "inputs.json")}))
    await agent.run(req, params)

    cmd = captured["cmd"]
    bound = {cmd[i + 1].split(":")[0] for i, a in enumerate(cmd) if a == "--bind"}
    assert str(work_dir.resolve()) in bound, "out_dir lives under $WORK_DIR"
    assert str(repo.resolve()) in bound, \
        "the design spec is in the repo, which did NOT move to $WORK_DIR"
    for i, a in enumerate(cmd):
        if a == "--bind":
            host, _, guest = cmd[i + 1].partition(":")
            assert host == guest, "the container path must match the host path"
    assert cmd.index("--bind") < cmd.index("/fake/foundry.sif"), \
        "apptainer flags must precede the image"
    assert "--writable-tmpfs" not in cmd, \
        "deliberately absent - it lets rfd3 exit 0 into a vanishing overlay"

    # A tree already covered by another bind is not bound twice: apptainer accepts it,
    # but a duplicated mount point is the kind of thing that works until it does not.
    assert len(bound) == len([a for a in cmd if a == "--bind"]), "binds must be unique"

    # With no $WORK_DIR set the input tree is still bound - a campaign that is merely
    # misconfigured must not also become unable to read its own input.
    monkeypatch.delenv("WORK_DIR")
    await agent.run(req, params)
    assert str(repo.resolve()) in {
        captured["cmd"][i + 1].split(":")[0]
        for i, a in enumerate(captured["cmd"]) if a == "--bind"}


async def test_rfd3_does_not_leak_this_pythons_packages_into_the_container(
        reg, monkeypatch, tmp_path):
    """apptainer passes the whole environment through and bind-mounts $HOME.

    Without an explicit env the container imports THIS campaign's Python on top of its
    own: `PYTHONPATH` carries the editable install of this repo, and `$HOME`'s user
    site-packages carry a second torch/numpy. The image ships a pinned stack; layering
    another over it is how a container that works interactively fails under a campaign.
    """
    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.setenv("PYTHONPATH", "/home/someone/exdrive/rad/impress-a/src")
    monkeypatch.setenv("PYTHONUSERBASE", "/home/someone/.local")
    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.chdir(tmp_path)

    captured: dict[str, Any] = {}

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        captured["env"] = env
        return "", ""

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design")
    params = agent.parameterize(TaskRequest(
        tool="rfd3_design", node_id=req.node_id,
        params={"input_spec_path": "/fake/inputs.json"}))
    await agent.run(req, params)

    env = captured["env"]
    assert env is not None, "no env passed: the container inherits ours wholesale"
    assert "PYTHONPATH" not in env
    assert "PYTHONUSERBASE" not in env
    assert env["PYTHONNOUSERSITE"] == "1", \
        "set, not unset - it is read for presence, so even '0' would disable user site"
    assert env["KEEP_ME"] == "yes", \
        "only the Python-resolution variables are stripped; $FOUNDRY_SIF_PATH, " \
        "$WORK_DIR and the SLURM/CUDA variables must still reach the container"


async def test_ligandmpnn_passes_absolute_checkpoints_and_runs_in_the_checkout(
        reg, monkeypatch, tmp_path):
    """`run.py` defaults both checkpoints to `./model_params/...` - relative to the CWD.

    A campaign's CWD is its own root, not the LigandMPNN checkout, so left implicit every
    invocation fails on a missing checkpoint. This pins both halves of the fix: absolute
    paths, and cwd set to the checkout.
    """
    from impress_a.core.artifacts import ArtifactRef
    from impress_a.tools import ligandmpnn_agents
    from impress_a.tools.agent import TaskRequest

    mpnn = tmp_path / "LigandMPNN"
    (mpnn / "model_params").mkdir(parents=True)
    monkeypatch.setenv("MPNN_DIR", str(mpnn))
    monkeypatch.chdir(tmp_path)

    captured: dict[str, object] = {}

    async def fake_run_cmd(cmd, cwd=None, env=None, timeout_s=None):
        captured["cmd"], captured["cwd"], captured["env"] = cmd, cwd, env
        return "", ""

    monkeypatch.setattr(ligandmpnn_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("ligandmpnn_design")(reg.get("ligandmpnn_design"))
    # Keyed by this tool's own DECLARED input port, with the upstream output port recorded -
    # which is what `exec/dispatch.node_task` builds from the composer's typed wiring. The
    # `dep0` form this replaces was the positional keying that made a two-input node mis-wire.
    req = TaskRequest(
        tool="ligandmpnn_design", node_id="r0001:r0_s1_ligandmpnn_design",
        input_ports={"backbone": "backbone"},
        inputs={"backbone": {"outputs": {
            "backbone": ArtifactRef(type="Backbone", path="/fake/bb.pdb")}}})
    await agent.run(req, agent.parameterize(TaskRequest(tool="ligandmpnn_design")))

    cmd = captured["cmd"]
    for flag, name in (("--checkpoint_ligand_mpnn", "ligandmpnn_v_32_010_25.pt"),
                       ("--checkpoint_path_sc", "ligandmpnn_sc_v_32_002_16.pt")):
        assert flag in cmd, f"{flag} must be explicit - the default is CWD-relative"
        value = cmd[cmd.index(flag) + 1]
        assert value == str(mpnn / "model_params" / name)
        assert pathlib.Path(value).is_absolute()

    assert captured["cwd"] == mpnn, \
        "must run inside the checkout - other relative paths resolve the same way"


def test_ligandmpnn_passes_fixed_residues_through(reg):
    """`--fixed_residues` is a real LigandMPNN flag (confirmed: `run.py --help`) - it must
    only be added when the campaign actually sets one, since an empty string is not a
    valid residue selection."""
    from impress_a.tools.agent import TaskRequest

    agent = reg.agent_for("ligandmpnn_design")(reg.get("ligandmpnn_design"))
    with_residues = agent.parameterize(TaskRequest(
        tool="ligandmpnn_design", params={"fixed_residues": "A16"}))
    assert with_residues["fixed_residues"] == "A16"

    without = agent.parameterize(TaskRequest(tool="ligandmpnn_design", params={}))
    assert without.get("fixed_residues", "") == ""


def test_rosetta_toolkits_accept_a_ligand_params_path(reg):
    """A real ALR-ligand PDB needs `-extra_res_fa <ligand>.params` or pose_from_pdb()
    raises on the unrecognized HETATM residue (confirmed: old IMPRESS's packmin.py,
    fastrelax.py, filter_shape.py all pass this unconditionally)."""
    from impress_a.tools.agent import TaskRequest

    for tool in ("packmin", "fastrelax", "filter_shape"):
        agent = reg.agent_for(tool)(reg.get(tool))
        resolved = agent.parameterize(TaskRequest(
            tool=tool, params={"ligand_params_path": "/fake/ALR.params"}))
        assert resolved["ligand_params_path"] == "/fake/ALR.params"


async def test_boltz_agent_passes_no_kernels(reg, tmp_path, monkeypatch):
    """cuequivariance_ops_torch's fused kernel needs cublasGemmGroupedBatchedEx, absent
    from the nvidia-cublas-cu12 version torch pins - the import fails every time without
    `--no_kernels` (verified, reproduced with no GPU present, in old IMPRESS's boltz.sh)."""
    from impress_a.tools import boltz_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("BOLTZ_CACHE", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)

    pdb = tmp_path / "in.pdb"
    pdb.write_text("ATOM      1  N   ALA A   1      11.104  13.207   2.100  1.00 20.00"
                   "           N\n"
                    "END\n")

    captured: dict[str, list[str]] = {}

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        captured["cmd"], captured["env"] = cmd, env
        return "", ""

    monkeypatch.setattr(boltz_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("boltz_predict")(reg.get("boltz_predict"))
    req = TaskRequest(tool="boltz_predict", input_ports={"structure": "structure"},
                      inputs={"structure": {"outputs": {"structure": str(pdb)}}})
    params = agent.parameterize(TaskRequest(
        tool="boltz_predict", params={"ligand_smiles": "CC(=O)Oc1ccccc1C(=O)O"}))
    await agent.run(req, params)

    assert "--no_kernels" in captured["cmd"]


def test_check_ligand_smiles_catches_the_silent_wrong_answer():
    """An empty ligand_smiles doesn't fail - it silently models no ligand. Backlog A2."""
    from impress_a.cli import _check_ligand_smiles
    from impress_a.core.pareto import Direction, Objective
    from impress_a.manager import CampaignSpec

    base = {"campaign_id": "c", "goal": "g",
           "objectives": [Objective(name="x", direction=Direction.MIN)]}

    blank = CampaignSpec(**base, stages=["boltz_predict"],
                         params={"boltz_predict": {"ligand_smiles": ""}})
    assert _check_ligand_smiles(blank) is not None

    filled = CampaignSpec(**base, stages=["boltz_predict"],
                          params={"boltz_predict": {"ligand_smiles": "CCO"}})
    assert _check_ligand_smiles(filled) is None

    no_boltz = CampaignSpec(**base, stages=["rfd3_design"], params={})
    assert _check_ligand_smiles(no_boltz) is None


def test_thread_caps_divide_the_allocation_not_the_node(monkeypatch):
    """The three Rosetta stages are CPU-bound and run one per lineage.

    Sized from `os.cpu_count()` they would each claim the whole node and fight; sized
    from the cgroup and divided by the pipelines in flight they do not. Backlog C9.
    """
    from impress_a.cli import _thread_caps
    from impress_a.core.pareto import Direction, Objective
    from impress_a.manager import CampaignSpec

    base = {"campaign_id": "c", "goal": "g",
            "objectives": [Objective(name="x", direction=Direction.MIN)]}
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: set(range(64)))

    caps = _thread_caps(CampaignSpec(**base, concurrency=2, replicas=4))
    assert caps["OMP_NUM_THREADS"] == "4", "64 cpus / (2*4 pipelines * 2) = 4"
    assert {caps[v] for v in ("MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                              "NUMEXPR_NUM_THREADS")} == {"4"}, \
        "all four libraries must agree, or the widest one wins"
    assert caps["OMP_WAIT_POLICY"] == "PASSIVE"

    # Never zero: more pipelines than cores must still leave each child one thread.
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: {0, 1})
    starved = _thread_caps(CampaignSpec(**base, concurrency=4, replicas=8))
    assert starved["OMP_NUM_THREADS"] == "1"

    # replicas defaults to 0 ("policy decides"), which must not divide by zero or
    # hand a single lineage the entire allocation's worth of threads per stage.
    monkeypatch.setattr("os.sched_getaffinity", lambda _pid: set(range(16)))
    unset = _thread_caps(CampaignSpec(**base))
    assert unset["OMP_NUM_THREADS"] == "8"


def test_the_boltz_cache_guard_serialises_once_then_gets_out_of_the_way(tmp_path):
    """`download_boltz2()` checks the CCD directory's PRESENCE, not its completeness,
    so a second lineage starting mid-extraction reads a half-populated cache and dies
    on `CCD component ... not found!`. Backlog C8, measured upstream.

    The guard must also be a one-time cost: once a run has proven the cache, later
    lineages take the fast path and predict in parallel.
    """
    import os as _os

    from impress_a.tools.boltz_agents import _CACHE_COMPLETE, _claim_cache

    cache = tmp_path / "boltz"
    fd = _claim_cache(cache)
    assert fd is not None, "an unproven cache must be claimed exclusively"
    assert cache.exists(), "and created if absent"
    _os.close(fd)

    # Nothing wrote the marker, so the cache is still unproven - a run that crashed
    # must not leave the next one thinking the extraction completed.
    assert _claim_cache(cache) is not None

    (cache / _CACHE_COMPLETE).write_text("proven\n")
    assert _claim_cache(cache) is None, \
        "a proven cache must not be locked, or replicas would serialise forever"


def test_the_boltz_cache_guard_never_deletes_a_cache_it_cannot_refetch(tmp_path):
    """Where this departs from upstream, deliberately.

    Upstream repairs a partial cache by removing it and re-downloading. Compute nodes
    have no egress - which is why the warm-up runs on a login node at all - so deleting
    a cache that turned out to be fine would end the campaign with no way back. An
    unproven-but-populated cache is left exactly as found; `impress-a preflight` is
    what catches it, on a node that can still repair it.
    """
    import os as _os

    from impress_a.tools.boltz_agents import _claim_cache

    cache = tmp_path / "boltz"
    (cache / "mols").mkdir(parents=True)
    (cache / "mols" / "ALR.pkl").write_text("payload")
    (cache / "boltz2_conf.ckpt").write_text("weights")

    fd = _claim_cache(cache)
    assert fd is not None
    _os.close(fd)

    assert (cache / "mols" / "ALR.pkl").read_text() == "payload"
    assert (cache / "boltz2_conf.ckpt").exists()


@pytest.mark.parametrize("args", [
    (["ligandmpnn", "--pdb", "x.pdb"], 2, "partial out", "Traceback: boom"),
    (["boltz", "predict"], -1, "", "timed out after 60.0s"),
])
def test_subprocess_error_survives_the_worker_boundary(args):
    """Dragon pickles a worker's exception into its results DDict. An exception that
    cannot be unpickled does not surface as FAILED: rhapsody's monitor loop drops the
    completion and the run sits in flight until walltime (job 22536706)."""
    import pickle

    from impress_a.tools._subprocess import SubprocessError

    cloudpickle = pytest.importorskip("cloudpickle")
    err = SubprocessError(*args)
    for dumps, loads in ((pickle.dumps, pickle.loads), (cloudpickle.dumps, cloudpickle.loads)):
        back = loads(dumps(err))
        assert type(back) is SubprocessError
        assert (back.cmd, back.returncode, back.stdout, back.stderr) == args
        assert str(back) == str(err)


async def test_rfd3_never_hands_downstream_a_trajectory(reg, monkeypatch, tmp_path):
    """The out_dir listing from job 22536706, verbatim.

    RFD3 writes its trajectories as `.cif.gz` too and they carry no sidecar JSON, so a
    bare `sorted(glob("*.cif.gz"))[0]` picked `..._denoised_model_0` - a multi-frame
    trajectory, 1.7 MB against the real design's 19 KB - converted it, measured
    `ss_fraction` on the stack and handed it to LigandMPNN as the backbone.

    `dump_trajectories=False` (G3) hides this by never writing those files. That is luck,
    not a fix: this asserts the selection is right even when they are present.
    """
    from impress_a.tools import _pdbtools, rfd3_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.chdir(tmp_path)
    stem = "ALR_binder_design_partial_0"

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        work = pathlib.Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("out_dir=")))
        for name in (f"{stem}_denoised_model_0.cif.gz", f"{stem}_noisy_model_0.cif.gz",
                     f"{stem}_model_0.cif.gz"):
            (work / name).write_bytes(b"x")
        (work / f"{stem}_model_0.json").write_text("{}")
        return "", ""

    converted: dict[str, Any] = {}

    def fake_convert(src, dst):
        converted["src"] = pathlib.Path(src)
        pathlib.Path(dst).write_text("PDB")

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(_pdbtools, "cif_gz_to_pdb", fake_convert)
    monkeypatch.setattr(_pdbtools, "secondary_structure_fraction", lambda p: 0.7)

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design")
    params = agent.parameterize(TaskRequest(
        tool="rfd3_design", node_id=req.node_id,
        params={"input_spec_path": "/fake/inputs.json"}))
    out = await agent.run(req, params)

    assert converted["src"].name == f"{stem}_model_0.cif.gz", \
        "the design is the model with a sidecar JSON, not whatever sorts first"
    assert out["count"] == out["metrics"]["num_models"] == 1, \
        "trajectories are not candidates; counting them would also inflate num_models"


async def test_rfd3_refuses_an_out_dir_it_cannot_identify_a_design_in(reg, monkeypatch,
                                                                     tmp_path):
    """Structures with no metadata beside them. Which one is a design is a guess, and a
    confident guess is the failure mode this project exists to refuse - so this raises
    rather than converting one. An out_dir with no `.cif.gz` at all is a different case:
    that stays the quiet `count: 0` the `output_present` gate is written to catch
    (`tests/empty_out_dir.bad.json`)."""
    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.chdir(tmp_path)

    async def fake_run_cmd(cmd, env=None, timeout_s=None):
        work = pathlib.Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("out_dir=")))
        (work / "orphan_model_0.cif.gz").write_bytes(b"x")
        return "", ""

    monkeypatch.setattr(rfd3_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    req = TaskRequest(tool="rfd3_design", node_id="r0001:r0_s0_rfd3_design")
    params = agent.parameterize(TaskRequest(
        tool="rfd3_design", node_id=req.node_id,
        params={"input_spec_path": "/fake/inputs.json"}))

    with pytest.raises(RuntimeError, match="sidecar"):
        await agent.run(req, params)


async def test_ligandmpnn_runs_run_py_through_the_numpy_alias_shim(reg, monkeypatch,
                                                                   tmp_path):
    """`run.py` cannot import under this venv's numpy, so invoking it directly is a bug.

    Job 22669509: LigandMPNN died in its module-level imports, before parsing an argument
    - first on a missing `ml_collections`, then on `np.int`, removed in numpy 1.24. The
    venv carries numpy 2.x because Boltz needs it. The shim restores the aliases and
    hands off via runpy; this pins that the adapter goes through it, and that the
    interpreter is `sys.executable` rather than whatever a Dragon worker's PATH resolves
    `python` to.
    """
    import sys

    from impress_a.core.artifacts import ArtifactRef
    from impress_a.tools import ligandmpnn_agents
    from impress_a.tools.agent import TaskRequest

    mpnn = tmp_path / "LigandMPNN"
    (mpnn / "model_params").mkdir(parents=True)
    monkeypatch.setenv("MPNN_DIR", str(mpnn))
    monkeypatch.chdir(tmp_path)

    captured: dict[str, Any] = {}

    async def fake_run_cmd(cmd, cwd=None, env=None, timeout_s=None):
        captured["cmd"], captured["cwd"], captured["env"] = cmd, cwd, env
        return "", ""

    monkeypatch.setattr(ligandmpnn_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("ligandmpnn_design")(reg.get("ligandmpnn_design"))
    # Keyed by this tool's own DECLARED input port, with the upstream output port recorded -
    # which is what `exec/dispatch.node_task` builds from the composer's typed wiring. The
    # `dep0` form this replaces was the positional keying that made a two-input node mis-wire.
    req = TaskRequest(
        tool="ligandmpnn_design", node_id="r0001:r0_s1_ligandmpnn_design",
        input_ports={"backbone": "backbone"},
        inputs={"backbone": {"outputs": {
            "backbone": ArtifactRef(type="Backbone", path="/fake/bb.pdb")}}})
    await agent.run(req, agent.parameterize(TaskRequest(tool="ligandmpnn_design")))

    cmd = captured["cmd"]
    assert cmd[0] == sys.executable, \
        "PATH happened to be right on job 22669509 because the launcher activates the " \
        "venv; this removes the dependency on that staying true"
    shim = pathlib.Path(cmd[1])
    assert shim.name == "mpnn_run.py" and shim.exists(), \
        "the shim must be written to disk before it can be run"
    text = shim.read_text()
    assert "setattr(np, _alias, _builtin)" in text
    assert "-P" not in cmd, \
        "-P is 3.11+ and this package supports 3.10, where it is a hard Unknown option"
    assert "sys.path[:] = [p for p in sys.path" in text, \
        "so the shim scrubs its own directory itself - CPython otherwise prepends it, " \
        "a LigandMPNN output dir, to sys.path ahead of the stdlib"
    assert cmd[2] == str(mpnn), "the shim takes mpnn_dir as its first argument"
    assert str(mpnn / "run.py") not in cmd, \
        "run.py must never be invoked directly - it cannot import under numpy 2.x"
    assert cmd[3:5] == ["--model_type", "ligand_mpnn"], \
        "everything after the shim's own argument is run.py's argv, unchanged"


def test_the_mpnn_shim_restores_the_aliases_openfold_needs(tmp_path):
    """The shim, run for real against a fake checkout. No torch, no GPU, no LigandMPNN.

    `np.int` and `np.object` are what the vendored openfold actually uses and what numpy
    1.24 removed. `np.bool` is deliberately not forced - numpy 2.x defines it as its own
    bool scalar, which is a valid dtype, and the only `np.bool` site in the checkout is
    off the import path. This also pins the three things a wrapper silently gets wrong:
    argv forwarding, the working directory, and the child's exit code.
    """
    import json
    import subprocess
    import sys

    from impress_a.tools.ligandmpnn_agents import MPNN_SHIM

    mpnn = tmp_path / "LigandMPNN"
    mpnn.mkdir()
    (mpnn / "run.py").write_text(
        "import json, os, sys\n"
        "import numpy as np\n"
        "assert np.int is int, np.int\n"
        "assert np.object is object, np.object\n"
        "assert np.zeros([2, 2], dtype=np.int).dtype == np.int64\n"
        "assert hasattr(np, 'bool'), 'numpy 2 defines this one itself'\n"
        "print(json.dumps({'argv': sys.argv, 'cwd': os.getcwd(), 'path': sys.path}))\n"
        "sys.exit(7)\n")
    shim = tmp_path / "mpnn_run.py"
    shim.write_text(MPNN_SHIM)

    out = subprocess.run([sys.executable, str(shim), str(mpnn), "--seed", "11"],
                         capture_output=True, timeout=120, check=False, cwd=tmp_path)

    assert out.returncode == 7, \
        f"the child's exit code must survive runpy, got {out.returncode}: {out.stderr.decode()}"
    assert not out.stderr, \
        f"probing np.object emits a FutureWarning; stderr is the diagnostic: {out.stderr.decode()}"
    payload = json.loads(out.stdout.decode().strip().splitlines()[-1])
    assert payload["argv"] == [str(mpnn / "run.py"), "--seed", "11"], \
        "run.py must see its own name as argv[0] and nothing of the shim's"
    assert pathlib.Path(payload["cwd"]).resolve() == mpnn.resolve(), \
        "run.py resolves its bundled resources relative to the checkout"
    assert str(tmp_path) not in payload["path"], \
        ("the shim must scrub its own directory off sys.path. CPython prepends it, which "
         "puts a LigandMPNN *output* directory ahead of the stdlib for the whole run - "
         "invisible until something writes a .py-named file in there. `-P` is the "
         "interpreter's own answer to this, but it is 3.11+ and the floor here is 3.10")


def test_the_mpnn_shim_does_not_launder_a_failure(tmp_path):
    """A wrapper is the easiest place to lose the diagnostic G6 just finished restoring.

    Three ways that happens: swallowing the exit code, swallowing the traceback, and
    losing `__file__` so the frames no longer name run.py. The shim's own frames staying
    on top is deliberate - when the shim is the bug, those frames are the evidence.
    """
    import subprocess
    import sys

    from impress_a.tools.ligandmpnn_agents import MPNN_SHIM

    shim = tmp_path / "mpnn_run.py"
    shim.write_text(MPNN_SHIM)

    mpnn = tmp_path / "LigandMPNN"
    mpnn.mkdir()
    (mpnn / "run.py").write_text("raise RuntimeError('boom')\n")
    out = subprocess.run([sys.executable, str(shim), str(mpnn)],
                         capture_output=True, timeout=120, check=False)
    err = out.stderr.decode()
    assert out.returncode != 0, "a raising run.py must not report success"
    assert "boom" in err, "the real exception has to reach SubprocessError's stderr"
    assert "run.py" in err, "runpy must set __file__, or the traceback names no source"

    # argparse exits 2 on a usage error; laundering that into 0 or 1 would mean a
    # malformed invocation reads as something else entirely.
    (mpnn / "run.py").write_text("import sys\nsys.exit(2)\n")
    out = subprocess.run([sys.executable, str(shim), str(mpnn)],
                         capture_output=True, timeout=120, check=False)
    assert out.returncode == 2, f"exit code must pass through runpy, got {out.returncode}"


def test_the_mpnn_shim_says_so_when_mpnn_dir_is_not_a_checkout(tmp_path):
    """Otherwise a mis-set $MPNN_DIR is a bare FileNotFoundError three frames inside
    runpy, which reads like a LigandMPNN bug rather than a configuration one."""
    import subprocess
    import sys

    from impress_a.tools.ligandmpnn_agents import MPNN_SHIM

    shim = tmp_path / "mpnn_run.py"
    shim.write_text(MPNN_SHIM)
    empty = tmp_path / "not-a-checkout"
    empty.mkdir()

    out = subprocess.run([sys.executable, str(shim), str(empty)],
                         capture_output=True, timeout=120, check=False)
    assert out.returncode != 0
    assert "no run.py under" in out.stderr.decode()


def test_ligandmpnn_walltime_covers_the_measured_import_cost(reg):
    """A magic number that is a bug report, per CLAUDE.md - so here is the report.

    Job 22669509: `task.000002` went RUNNING at 23:09:51 and FAILED at 23:14:27. That is
    276s to reach a ModuleNotFoundError in run.py's module-level imports, before a single
    tensor was allocated - ~280s of it `import torch` paging off Lustre. The old
    `walltime_s: 300` left 24s for the actual work, so the next run would have died as
    `timed out after 300s`: indistinguishable from a hang, and blamed on LigandMPNN.
    """
    spec = reg.get("ligandmpnn_design")
    assert spec.resources.walltime_s >= 900, \
        ("the measured import alone is ~280-360s; anything under 900s is a budget that "
         "cannot cover it plus inference")


@pytest.mark.parametrize("tool,dim,measured_s", [
    ("rfd3_design", "gpu_hours", 145.7),
    ("ligandmpnn_design", "gpu_hours", 18.1),
    ("packmin", "cpu_hours", 15.9),
    ("fastrelax", "cpu_hours", 25.9),
    ("filter_shape", "cpu_hours", 10.2),
    # Job 22692304, the first run in which boltz_predict executed at all.
    ("boltz_predict", "gpu_hours", 57.8),
])
def test_cost_models_are_within_an_order_of_magnitude_of_measurement(
        reg, tool, dim, measured_s):
    """A magic number that is a bug report, per CLAUDE.md.

    These were literature guesses, and on job 22675512 the gpu ones summed to 0.65
    against an interlock cap of 0.60 - so the six-stage chain was refused three times
    and the policy truncated `boltz_predict`, the only producer of two of the campaign's
    four objectives, off the end. The run was then incapable of producing a front and
    said so nowhere.

    Job 22684607 measured five; 22692304 added boltz_predict. The bound here is
    deliberately loose in BOTH directions: an estimate feeding a refusal gate should err
    high, but being 50x high is how a budget gate starts refusing work that would have fit.

    It is loose for a second reason. These are single samples and wall time is not
    stable: rfd3_design took 145.7s in 22684607 and 45.0s in 22692304 - same campaign,
    same allocation shape, same parameters, 3.2x apart. A cost model pinned to a fast
    observation starts rejecting graphs the first time a slow one shows up, so the
    declared figures deliberately sit a few multiples above what was measured and this
    test must not tighten toward equality.
    """
    # CPU-HOURS ARE WALL x CORES. This line read `measured_s / 3600` and so carried the same
    # units error as the specs it was checking - which is why it passed while
    # `impress-a validate-tasks` on job 23670171 failed `fastrelax` at measured/declared =
    # 2.38. The executor has always measured the ratio the right way; the spec comments, and
    # this test, were the two places that did not, so they agreed with each other and with
    # nothing that runs. GPU dimensions stay wall-based: the declared figure is device-time,
    # and `cores` is the CPU request.
    spec = reg.get(tool)
    cores = spec.resources.cores if dim == "cpu_hours" else 1
    measured_h = measured_s * cores / 3600
    declared = spec.cost_model.cost[dim]
    assert declared >= measured_h, \
        f"{tool} declares {declared} {dim} but measured {measured_h:.4f} " \
        f"({measured_s}s x {cores} cores) - an estimate below the real cost makes gate 5 " \
        "and the untrusted-pattern cap refuse work that fits"
    assert declared <= measured_h * 10, \
        f"{tool} declares {declared} {dim} against {measured_h:.4f} measured " \
        f"({declared / measured_h:.0f}x). Over-estimating by this much is what got " \
        "boltz_predict dropped in job 22675512"


def test_the_six_stage_chain_fits_the_untrusted_pattern_cap(reg):
    """The whole point of the cost-model correction.

    An untrusted pattern is capped at 10% of available budget (`TrustLedger.
    provisional_budget_fraction`). The smoke campaign budgets 6.0 gpu-h / 10.0 cpu-h, so
    a first run of the full chain has 0.60 / 1.00 to fit inside. It did not, and the
    correction that followed was silently destructive.
    """
    stages = ["rfd3_design", "ligandmpnn_design", "packmin", "fastrelax",
              "filter_shape", "boltz_predict"]
    est: dict[str, float] = {}
    for tool in stages:
        for dim, value in reg.get(tool).cost_model.cost.items():
            est[dim] = est.get(dim, 0.0) + value

    assert est["gpu_hours"] <= 6.0 * 0.10, \
        f"gpu estimate {est['gpu_hours']:.3f} exceeds the 0.600 provisional cap - the " \
        "first run of the full chain would be refused and a stage truncated away"
    assert est["cpu_hours"] <= 10.0 * 0.10, \
        f"cpu estimate {est['cpu_hours']:.3f} exceeds the 1.000 provisional cap"


def test_packmin_does_not_gate_on_a_relaxed_score(reg):
    """Whether a pose blew up is fastrelax's call, made by whether it converges.

    Both bounds packmin ever had were wrong the same way. `max: 0.0` was upstream's
    fastrelax threshold on the wrong stage (job 22684607: +145.3 here, -322.6 from
    fastrelax). `max: 1000.0` replaced it and, as an integrity gate, demoted a trusted
    pattern on its first trip: job 22726105 r0004 scored +1064.5 and relaxed to -336.0.
    Upstream (`small_molecule_binding.py:678`) gates nothing on packmin either.
    """
    def bounds(tool):
        # Keyed by (metric, role), not by metric. One metric now carries two gates with
        # different roles and different bounds - which is decision 0013's whole point - and
        # keying on the metric alone let the acceptance gate shadow the divergence bound this
        # test exists to protect.
        return {(g.params["metric"], g.role): g.params.get("max")
                for g in reg.get(tool).qc_gates if g.id == "metric_in_range"}

    assert not [m for m, _ in bounds("packmin") if m == "total_score"], \
        "a bound inside the normal spread of a pre-relax score carries no information"
    assert any(g.id == "metrics_reported" and "total_score" in g.params["metrics"]
               and g.role == "integrity" for g in reg.get("packmin").qc_gates), \
        "packmin must still REPORT a score - a worker that exits without one has broken"

    relax = bounds("fastrelax")
    assert relax[("total_score", "integrity")] == 0.0
    assert relax[("fa_rep", "integrity")] == 500.0, \
        "fastrelax converging is still the only judgement of an exploded pose, so the WIDE " \
        "divergence bounds must stay integrity whatever the acceptance thresholds are"
    assert relax[("total_score", "acceptance")] == -250.0
    assert relax[("fa_rep", "acceptance")] == 100.0
    assert relax[("interaction_energy", "acceptance")] == -8.0, \
        "upstream's own calibrated PROD values, as acceptance gates (backlog G4)"


async def test_run_cmd_keeps_what_a_timed_out_process_already_said():
    """A timeout used to raise with "" for both streams.

    Job 22675512's packmin died that way: 300s, an empty work dir, and a message that
    named no cause - indistinguishable from a hang. The workers print phase timings to
    stderr precisely so a kill still leaves evidence, which only works if run_cmd drains
    the pipes instead of discarding them.
    """
    import sys

    from impress_a.tools._subprocess import SubprocessError, run_cmd

    script = ("import sys, time\n"
              "sys.stderr.write('[phase] import pyrosetta  471.0s\\n'); sys.stderr.flush()\n"
              "sys.stdout.write('partial stdout\\n'); sys.stdout.flush()\n"
              "time.sleep(30)\n")
    with pytest.raises(SubprocessError) as exc:
        await run_cmd([sys.executable, "-c", script], timeout_s=2.0)

    err = exc.value
    assert err.returncode == -1
    assert "timed out after 2.0s" in err.stderr
    assert "[phase] import pyrosetta" in err.stderr, \
        "the phase timings are the whole diagnostic; losing them is the old bug"
    assert "partial stdout" in err.stdout


# ---------------------------------------------------------------------------
# The ToolkitView and the model-D Specifier (phase 2 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def test_the_view_exposes_every_declared_parameter_with_its_range(reg):
    """A reasoner given bare tool ids cannot choose, so it guesses - which is backlog H3.

    Every policy emitted params keyed to `mock_generate` and `mock_design`, the composer
    dropped them because no such tool was in the graph, and no policy could vary a real tool's
    parameter at all. The view is what makes that choosable: typed ports, ranges, and the one
    sentence the spec gives about what a parameter trades.
    """
    view = view_of(reg)
    assert set(view.ids) == set(reg.ids())
    for tool_id in view.ids:
        card, spec = view.tools[tool_id], reg.get(tool_id)
        assert set(card.parameters) == set(spec.parameters), tool_id
        assert set(card.frozen) == set(spec.frozen_parameters), tool_id
        assert set(card.parameters).isdisjoint(card.frozen), (
            f"{tool_id}: a frozen parameter must not be proposable")
        for name, p in spec.parameters.items():
            assert card.parameters[name].min == p.min
            assert card.parameters[name].max == p.max
            assert card.parameters[name].trades == p.trades
    assert view.tools["rfd3_design"].parameters["diffusion_steps"].trades, \
        "`trades` is the only prose a reasoner gets about cost; it must survive projection"


def test_the_view_carries_the_skill_documents(reg):
    """`Registry.toolkit_skills()` had no caller at all (backlog H4).

    The guidance written for an agent had therefore never reached one.
    """
    view = view_of(reg)
    toolkits = {reg.get(t).toolkit for t in reg.ids()}
    assert set(view.skills) == {t for t in toolkits if t in reg.skills}
    assert all(view.skills.values()), "an empty skill document is a load error, not a blank"


def test_the_view_narrows_to_the_campaigns_own_stages(reg):
    """A Specifier shown the mock toolkit on a real campaign can propose mocks on a GPU.

    `plans/done/02-real-toolkit.md` records that as the headline bug of that work: the
    documented real run loaded the real toolkits, validated them, and executed mock tools on an
    allocation. Narrowing is the cheap half of preventing it; the `tool_delivery` gate is the
    other.
    """
    view = view_of(reg, CHAIN)
    assert view.ids == sorted(CHAIN)
    assert "mock" not in set(view.skills), "no mock guidance reaches a real campaign's reasoner"


def test_the_view_answers_by_output_type_and_by_metric(reg):
    """The two questions a Planner and a Specifier actually ask."""
    view = view_of(reg, CHAIN)
    assert [t.id for t in view.reporting("complex_plddt")] == ["boltz_predict"]
    assert "rfd3_design" in [t.id for t in view.producers_of(ArtifactType.BACKBONE)]
    # The unification rule applies here exactly as it does in gate 1: a Complex satisfies a
    # Backbone requirement, never the reverse.
    assert view.tools["boltz_predict"].produces(ArtifactType.BACKBONE)
    assert not view.tools["rfd3_design"].produces(ArtifactType.COMPLEX)
    assert view.tools["boltz_predict"].acceptance_metrics == ["complex_plddt", "ligand_iptm"]


def _evidence(view, goal, spec, front=()):
    obs = CampaignObservation(campaign_id="c", cycle=1, goal=goal.text,
                              objectives=goal.objectives, toolkit=view, spec=spec,
                              pareto_front=list(front))
    return SpecEvidence(obs, DataRegistry())


def _real_goal():
    return Goal(text="design a small-molecule binder", objectives=[
        Objective(name="total_score", direction=Direction.MIN),
        Objective(name="shape_complementarity", direction=Direction.MAX, min=0.55),
        Objective(name="complex_plddt", direction=Direction.MAX, min=0.75),
        Objective(name="ligand_iptm", direction=Direction.MAX, min=0.4)])


async def test_the_specifier_gives_an_unbounded_objective_a_measurement_rule(reg):
    """`total_score: minimize` has no finish line, so what the campaign owes it is a number.

    A `metric_in_range` with no range expresses no condition, so using one here would leave an
    objective that can never be satisfied and a Spec that can never complete. `metric_present`
    is the honest requirement: without a measurement the front cannot order anything by it.
    """
    sp = ThresholdSpecifier()
    spec = await sp.initial_spec(_real_goal())
    rules = {o.targets[0]: o.satisfied_when.kind for o in spec.objectives.values()}
    assert rules == {"total_score": "metric_present",
                     "shape_complementarity": "metric_in_range",
                     "complex_plddt": "metric_in_range",
                     "ligand_iptm": "metric_in_range"}
    assert not spec.complete()


async def test_the_specifier_names_an_objective_no_enabled_task_can_produce(reg):
    """Job 22675512, caught at specification instead of never.

    There, a budget correction removed the only producer of two of four objectives; nothing
    noticed, and the admitted graph recorded `rejected: null`. An objective the Toolkit cannot
    report is left OPEN and named, so the coverage gate sees it rather than the campaign
    quietly optimising three quarters of what it was for.
    """
    goal = _real_goal()
    goal.objectives.append(Objective(name="nonexistent_metric", direction=Direction.MAX,
                                     min=1.0))
    sp = ThresholdSpecifier()
    spec = await sp.initial_spec(goal)
    ev = _evidence(view_of(reg, CHAIN), goal, spec)

    bad = sp.unproducible(spec, ev)
    assert [spec.objectives[b].targets for b in bad] == [["nonexistent_metric"]]
    assert await sp.failed(spec, ev) == bad, "unproducible is the one thing retrying cannot fix"
    # And narrowing matters: with boltz dropped, its two objectives become unproducible too.
    ev_narrow = _evidence(view_of(reg, CHAIN[:-1]), goal, spec)
    targets = {spec.objectives[b].targets[0] for b in sp.unproducible(spec, ev_narrow)}
    assert {"complex_plddt", "ligand_iptm"} <= targets


async def test_the_specifier_exploits_by_adding_a_refinement_objective(reg):
    """Exploitation as a Spec change, which is what `parent_node` is for.

    The legacy cascade raised `diffusion_steps` - asking for the same draw again, harder. A
    refinement objective names the design to improve on, which keeps ADR 0004's backtracking
    reachable from the Spec and is the thing phase 8 makes executable by feeding a parent's
    artifacts into a child chain.
    """
    goal = _real_goal()
    sp = ThresholdSpecifier()
    spec = await sp.initial_spec(goal)

    assert (await sp.revise(spec, _evidence(view_of(reg, CHAIN), goal, spec))).is_empty, \
        "with an empty front there is nothing to refine, and inventing work from the absence " \
        "of evidence is not specification"

    node = DesignNode()
    for name, value in (("shape_complementarity", 0.56), ("complex_plddt", 0.95),
                        ("ligand_iptm", 0.9), ("total_score", -300.0)):
        node.properties[name] = Property(name=name, value=value,
                                         source=PropertySource(name="t"))
    ev = _evidence(view_of(reg, CHAIN), goal, spec, front=[node])

    rev = await sp.revise(spec, ev)
    assert len(rev.new_objectives) == 1
    added = rev.new_objectives[0]
    assert added.parent_node == node.id
    assert added.targets == ["shape_complementarity"], (
        "the weakest objective by normalised margin: 0.56 clears 0.55 by 1.8%, where "
        "complex_plddt clears 0.75 by 27%")

    spec.apply(rev)
    assert (await sp.revise(spec, ev)).is_empty, \
        "one open refinement at a time, or the Spec grows without bound and never completes"


async def test_a_refinement_objective_is_not_satisfied_by_its_parents_own_measurement(reg):
    """Bound to NEW evidence, or it satisfies itself the moment it exists.

    `DataRegistry.satisfies` counts hits against everything realized so far, and the parent's
    measurement is by definition already among them - so a default `n=1` rule is met at
    creation. That also defeats the open-refinement cap, because an objective satisfied
    immediately is not an open one, so the next signal adds another and the Spec grows every
    cycle. `n = hits + 1` is what "one MORE design over the threshold" has to mean.
    """
    goal = _real_goal()
    sp = ThresholdSpecifier()
    spec = await sp.initial_spec(goal)

    node = DesignNode()
    for name, value in (("shape_complementarity", 0.56), ("complex_plddt", 0.95),
                        ("ligand_iptm", 0.9), ("total_score", -300.0)):
        node.properties[name] = Property(name=name, value=value,
                                         source=PropertySource(name="t"))
    obs = CampaignObservation(campaign_id="c", cycle=1, goal=goal.text,
                              objectives=goal.objectives, toolkit=view_of(reg, CHAIN),
                              spec=spec, pareto_front=[node])
    # The parent's own numbers are on the record, exactly as they would be in a real campaign.
    data = DataRegistry()
    data.ingest(RunOutcome(run_id="r1", graph_id="g1", state=RunState.DONE, nodes=[node.id],
                           tasks=[TaskOutcome(task_id="t1", tool="filter_shape",
                                              metrics={"shape_complementarity": 0.56})]))
    ev = SpecEvidence(obs, data)

    rev = await sp.revise(spec, ev)
    added = rev.new_objectives[0]
    assert added.satisfied_when.n == 2, (
        "one existing hit, so satisfaction needs a second - otherwise the objective is met "
        "before any new work runs")
    spec.apply(rev)
    assert not data.satisfies(added.satisfied_when), \
        "the parent's measurement alone must not satisfy a refinement of it"
    assert [o.id for o in spec.open_objectives() if o.parent_node] == [added.id], \
        "and it stays OPEN, so the one-at-a-time cap actually binds"


# ---------------------------------------------------------------------------
# Ensemble selection (phase 8 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def test_the_mpnn_parser_reads_every_candidate_not_the_first():
    """Real LigandMPNN writes every candidate for a design into ONE file.

    So a parser that stops at the first header reads one candidate out of `num_seqs` and the
    rest are computed, charged for and discarded. The reference pipeline recorded exactly this:
    `analysis_sequence` "silently never compared MPNN candidates against each other", and
    fixing it there is what made `mpnn_ensemble_size` mean anything.
    """
    text = (">design, id=1, overall_confidence=0.5100, ligand_confidence=0.4000\nMKT\n"
            ">design, id=2, overall_confidence=0.8200, ligand_confidence=0.7100\nMKV\n"
            ">design, id=3, overall_confidence=0.6300, ligand_confidence=0.5500\nMKW\n")
    every = _parse_all_confidences(text)
    assert [c["overall_confidence"] for c in every] == [0.51, 0.82, 0.63]
    assert _parse_confidence(text)["overall_confidence"] == 0.82, \
        "the BEST candidate, not the first - 0.82 is what the acceptance gate reads"


def test_an_unreadable_header_is_skipped_rather_than_scored_zero():
    """A parser failure must not be indistinguishable from a genuinely bad design.

    Omitted, the integrity gate `metrics_reported` catches it; reported as 0.0 it reads as a
    weak design and an acceptance gate takes the blame for a broken tool (decision 0013).
    """
    text = (">design, id=1, confidence=unparseable\nMKT\n"
            ">design, id=2, overall_confidence=0.7000, ligand_confidence=0.6000\nMKV\n")
    assert len(_parse_all_confidences(text)) == 1
    assert _parse_confidence(text)["overall_confidence"] == 0.7
    assert _parse_confidence(">no confidences here\nMKT\n") == {}


def test_a_member_index_is_absent_rather_than_zero_when_the_name_carries_none():
    """"This is member zero" and "this filename does not say" must not be the same answer.

    Only one of them is safe to pair on, and pairing on the wrong one attributes a confidence
    to another member's structure.
    """
    assert member_index("confidence_abc_model_3.json") == 3
    assert member_index("abc_model_0.pdb") == 0
    assert member_index("backbone_0_packed_1_2.pdb") == 2, "the LAST integer in the stem"
    assert member_index("structure.pdb") is None


def test_pairing_refuses_rather_than_falls_back_to_position():
    """Two independently sorted globs agree only by luck.

    `rfd3_agents` already states the principle for its trajectory bug: a confident guess is
    worse than a loud failure. A caller that gets `None` here must say it could not pair, which
    is what `ensemble_paired: 0` records.
    """
    conf = [Path("confidence_x_model_0.json"), Path("confidence_x_model_1.json")]
    pdbs = [Path("x_model_0.pdb"), Path("x_model_1.pdb")]
    paired = pair_by_index(conf, pdbs)
    assert paired is not None
    assert [(c.name, p.name) for c, p in paired] == [
        ("confidence_x_model_0.json", "x_model_0.pdb"),
        ("confidence_x_model_1.json", "x_model_1.pdb")]

    # Counts differ, indices differ, or a name carries no index: all unpairable.
    assert pair_by_index(conf, pdbs[:1]) is None
    assert pair_by_index(conf, [Path("x_model_0.pdb"), Path("x_model_7.pdb")]) is None
    assert pair_by_index(conf, [Path("a.pdb"), Path("b.pdb")]) is None


def test_select_best_skips_a_member_whose_metric_cannot_be_read():
    """The same rule the gates use: an unreadable value is an omission, not a zero."""
    members = [{"plddt": None}, {"plddt": 0.4}, {}, {"plddt": 0.9}, {"plddt": 0.6}]
    chosen = select_best(members, lambda m: m.get("plddt"))
    assert chosen == (3, {"plddt": 0.9})
    assert select_best(members, lambda m: m.get("plddt"), higher_is_better=False) \
        == (1, {"plddt": 0.4})
    assert select_best([{}, {"plddt": None}], lambda m: m.get("plddt")) is None


def test_mpnn_prefers_one_wide_batch_over_several_narrow_ones(reg):
    """The one place the preference is mechanical rather than a comment.

    `--batch_size` is candidates per forward pass and `--number_of_batches` is passes, so the
    old form - batches set to `num_seqs` with `--batch_size` left at its default of 1 - asked
    for N sequential batches of one. For a model tuned for batched output that is the worse of
    the two options: linear in N where a single wide batch is close to sublinear.
    """
    spec = reg.get("ligandmpnn_design")
    assert spec.parameters["batch_size"].default == 8
    assert spec.parameters["number_of_batches"].default == 1
    # And the declared sampling must be reachable: a width the spec forbids is a width the
    # Planner cannot ask for.
    assert spec.parameters["batch_size"].max >= 8


def test_the_sampled_tools_declare_what_the_adapter_reports(reg):
    """`ensemble_size`/`ensemble_paired` come from the adapter, not the tool - and must still
    be declared, or a reasoner cannot see that the campaign is measuring them."""
    for tool in ("ligandmpnn_design", "boltz_predict"):
        declared = set(reg.get(tool).metrics)
        assert {"ensemble_size", "ensemble_paired"} <= declared, tool


def test_rfd3_sampling_stays_at_one_with_its_reason_recorded(reg):
    """The honest exception: rfd3's adapter still keeps `cif_models[0]`.

    Selecting among its designs needs the sidecar `*_model_*.json`'s metric names confirmed
    against a real out_dir, which is backlog G2's remaining half. Raising it before that pays N
    times for one design - which is precisely what the comment there used to describe as a
    design principle.
    """
    assert reg.get("rfd3_design").parameters["num_designs"].default == 1
    assert reg.get("boltz_predict").parameters["diffusion_samples"].default == 8, \
        "the tools whose adapters DO select are the ones raised"


# ---------------------------------------------------------------------------
# Model D's Planner half, against the REAL specs. The point of testing it here rather than
# only on mocks is backlog H3: the defect was that no reasoner could vary a real tool's
# parameter, and a planner exercised only against `mock_generate` is exactly how that went
# unnoticed - the shipped policy's hardcoded params named two mock tools and were silently
# dropped on every real campaign.
# ---------------------------------------------------------------------------

def _planning_context(view, goal, spec, stages, front=()):
    obs = CampaignObservation(campaign_id="c", cycle=1, goal=goal.text,
                              objectives=goal.objectives, toolkit=view, spec=spec,
                              stages=list(stages), pareto_front=list(front))
    return PlanningContext(goal, obs)


async def _refined_spec(reg, goal, sp):
    """A Spec mid-campaign: the declared objectives met, one refinement objective open.

    The four declared objectives are closed with an explicit revision rather than through
    `Specifier.satisfied`, which would need a populated `DataRegistry` - this fixture is for
    testing the *Planner*, and the Specifier's satisfaction rules have their own tests above.
    What matters here is the shape of the Spec a Planner is handed on an exploit cycle.
    """
    spec = await sp.initial_spec(goal)
    node = DesignNode()
    for name, value in (("shape_complementarity", 0.56), ("complex_plddt", 0.95),
                        ("ligand_iptm", 0.9), ("total_score", -300.0)):
        node.properties[name] = Property(name=name, value=value,
                                         source=PropertySource(name="t"))
    ev = _evidence(view_of(reg, CHAIN), goal, spec, front=[node])
    spec.apply(SpecRevision(status_changes={
        oid: ObjectiveStatus.SATISFIED for oid in spec.objectives}))
    spec.apply(await sp.revise(spec, ev))
    return spec, node


async def test_a_planner_can_vary_a_real_tools_parameter(reg):
    """Backlog H3, which blocks any claim about decision quality.

    `ThresholdPolicy` emitted `params={"mock_generate": {...}, "mock_design": {...}}` on every
    arm. Against this chain those keys name tools that are not in the graph, so the composer
    dropped them without a word and no real tool's parameter was ever varied by any reasoner -
    which means the four models differed in no parameter at all, and a comparison between them
    could not have been measuring what it claimed.

    The value has to be real on three counts, so all three are asserted: the tool is one of
    this chain's own, the parameter is one that tool declares, and the number is inside the
    declared range rather than merely different.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec, node = await _refined_spec(reg, goal, sp)
    planner = ThresholdPlanner(stages=CHAIN)
    stage = await planner.plan(spec, _planning_context(view_of(reg, CHAIN), goal, spec,
                                                       CHAIN, front=[node]))

    varied = {t.tool: t.params for t in stage.runs if t.params}
    assert varied, "the planner varied nothing on a refinement, which is H3 unfixed"
    for tool, params in varied.items():
        assert tool in CHAIN, f"{tool} is not in this campaign's chain"
        declared = reg.get(tool).parameters
        for name, value in params.items():
            assert name in declared, f"{tool}.{name} is not a declared parameter"
            card = declared[name]
            assert card.min is None or value >= card.min, f"{tool}.{name}={value} below min"
            assert card.max is None or value <= card.max, f"{tool}.{name}={value} above max"
            assert value != card.default, f"{tool}.{name} was not actually varied"

    assert "diffusion_steps" in varied.get("rfd3_design", {}), (
        "rfd3's `diffusion_steps` trades 'quality vs wall-clock', which is the refinement "
        "axis this chain offers")


async def test_the_planner_leaves_breadth_and_identity_parameters_alone(reg):
    """Escalating `num_designs` or `seed` would cost GPU-hours or break the lineages.

    `rfd3_design`'s spec says `num_designs` stays at 1 because its adapter still keeps index
    0, so a planner reading "coverage vs GPU-hours" as an improvement axis pays N times for
    one design. `seed` is lineage identity: moving it would break the independence of the
    replicas the arm is being credited for. Both are declared, tunable and in range - so
    nothing but the `trades` sentence distinguishes them from the knob above.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec, node = await _refined_spec(reg, goal, sp)
    planner = ThresholdPlanner(stages=CHAIN)
    stage = await planner.plan(spec, _planning_context(view_of(reg, CHAIN), goal, spec,
                                                       CHAIN, front=[node]))

    asked = {name for t in stage.runs for name in t.params}
    for forbidden in ("num_designs", "seed", "batch_size", "number_of_batches",
                      "diffusion_samples", "nstruct"):
        assert forbidden not in asked, (
            f"{forbidden} is breadth or identity, not quality - raising it is either an "
            f"N-times bill for one design or a broken replica")


async def test_the_planner_escalates_toward_the_declared_maximum(reg):
    """One step per refinement, not a jump to the limit.

    The declared max is a limit, not a target: arriving there on the first refinement leaves
    nothing to escalate and no record of which step helped. It must also never exceed the
    max, because gate 3 refuses a parameter outside its declared range and a planner whose
    only move is refused has no moves.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec, node = await _refined_spec(reg, goal, sp)
    planner = ThresholdPlanner(stages=CHAIN)
    ctx = _planning_context(view_of(reg, CHAIN), goal, spec, CHAIN, front=[node])
    card = reg.get("rfd3_design").parameters["diffusion_steps"]

    seen = []
    for _ in range(8):
        stage = await planner.plan(spec, ctx)
        steps = next(t.params["diffusion_steps"] for t in stage.runs
                     if t.tool == "rfd3_design")
        seen.append(steps)
    assert seen == sorted(seen), f"escalation must be monotonic, got {seen}"
    assert seen[0] > card.default and seen[0] < card.max, (
        f"the first step must move off {card.default} without reaching {card.max}: {seen[0]}")
    assert max(seen) == card.max, f"escalation must reach the declared max: {seen}"


async def test_the_planner_wires_the_real_chain_by_declared_port(reg):
    """Typed wiring over the real specs, and the chain in the campaign's own order.

    Nearest-preceding by type is the rule `Composer.compose` applies to a linear chain, so a
    Stage this planner wires explicitly and a chain the composer wires by position describe
    the same graph. Asserted against the real ports because the mock chain is uniform and
    would hide a type error that this one would not.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec = await sp.initial_spec(goal)
    planner = ThresholdPlanner(stages=CHAIN, base_replicas=1)
    stage = await planner.plan(spec, _planning_context(view_of(reg, CHAIN), goal, spec, CHAIN))

    assert [t.tool for t in stage.runs] == CHAIN, "the campaign's order, not id order"
    for task in stage.runs:
        spec_ = reg.get(task.tool)
        required = {name for name, p in spec_.inputs.items() if p.required}
        assert required <= set(task.inputs), (
            f"{task.tool} left required port(s) {sorted(required - set(task.inputs))} unwired")
        for port, ref in task.inputs.items():
            src_id, out_port = ref.split(".", 1)
            src = next(t for t in stage.runs if t.task_id == src_id)
            want = spec_.inputs[port].type
            assert reg.get(src.tool).outputs[out_port].type.unifies_with(want), (
                f"{task.tool}.{port} wired to {src.tool}.{out_port}, which cannot satisfy "
                f"{want}")


async def test_a_refinement_stage_still_measures_every_campaign_objective(reg):
    """The minimal chain for one objective makes a child nobody can compare.

    Planning only `filter_shape`'s producers for a `shape_complementarity` refinement
    produced a node measured on that alone - incomparable with every design on the front, and
    refused outright by the executor's A8 check, so the refinement was unwinnable from the
    moment it was planned. That is job 22675512's defect reached by the opposite route: there
    a chain was truncated to fit a budget, here it was never built.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec, node = await _refined_spec(reg, goal, sp)
    ready = spec.ready()
    assert [o.parent_node for o in ready] == [node.id], "precondition: one refinement objective"

    planner = ThresholdPlanner(stages=CHAIN, base_replicas=1)
    stage = await planner.plan(spec, _planning_context(view_of(reg, CHAIN), goal, spec,
                                                       CHAIN, front=[node]))
    assert stage.parent_node == node.id
    reported = {m for t in stage.runs for m in reg.get(t.tool).metrics}
    missing = sorted({o.name for o in goal.objectives} - reported)
    assert missing == [], f"the refinement cannot be ranked on {missing}"


def test_every_real_adapter_recovers_its_inputs_by_port(reg):
    """No adapter may scan the dependency payloads for an artifact.

    `first_dep_output` searched them for one whose `outputs` happened to contain the name it
    wanted, which is right only while a node has exactly one upstream dependency: with two
    typed inputs it returned whichever came first, and that type-checks at composition and
    mis-wires at runtime. Worse, an adapter asked for an upstream *output* port while
    declaring an *input* port, and the two coincided here by luck - `ligandmpnn_design`
    consumes `backbone` and rfd3 emits `backbone`, so nothing ever disagreed.

    Checked two ways, because the mechanical one alone would pass a scan written by hand:
    every port name an adapter asks `input_path` for must be a port that tool DECLARES, and
    the scanning helper must be gone from the package entirely.
    """
    import ast

    src = pathlib.Path(impress_a_tools_dir())
    offenders, checked = [], 0
    for path in sorted(src.glob("*_agents.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        declared: set[str] = set()
        for tool_id in reg.ids():
            spec = reg.get(tool_id)
            if spec.entry.rsplit(".", 2)[-2] == path.stem:
                declared |= set(spec.inputs)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id == "first_dep_output":
                offenders.append(f"{path.name}:{node.lineno}: still scans")
            if node.func.id == "input_path" and len(node.args) == 2:
                port = node.args[1]
                if isinstance(port, ast.Constant):
                    checked += 1
                    if port.value not in declared:
                        offenders.append(
                            f"{path.name}:{node.lineno}: asks for {port.value!r}, which no "
                            f"tool in this module declares as an input port "
                            f"({sorted(declared)})")
    assert offenders == [], "\n".join(offenders)
    assert checked == 5, f"{checked} port lookups found; the real adapters have five"


def impress_a_tools_dir() -> str:
    import impress_a.tools
    return str(pathlib.Path(impress_a.tools.__file__).parent)


async def test_model_a_also_varies_a_real_tools_parameter(reg):
    """H3 for model A, which had the same defect and a different shape of it.

    `FourNodePolicy` asked for `diffusion_steps: 170` and `temperature: 0.35` keyed to
    `mock_generate` and `mock_design`. Against this chain those keys name nothing in the
    graph, so the composer dropped them silently; and even keyed correctly, 170 is a literal
    that happens to be inside rfd3's declared range and would be a gate-3 rejection on a tool
    whose range is narrower. The planner half asks for the same *fractions* of each tool's own
    declared range, which is the only form in which those numbers survive a chain nobody wrote
    them for.
    """
    goal, sp = _real_goal(), ThresholdSpecifier()
    spec = await sp.initial_spec(goal)
    stage = await AgenticPlanner(stages=CHAIN).plan(
        spec, _planning_context(view_of(reg, CHAIN), goal, spec, CHAIN))

    varied = {t.tool: t.params for t in stage.runs if t.params}
    assert varied, "model A varied nothing on the real chain, which is H3 unfixed for A"
    for tool, params in varied.items():
        assert tool in CHAIN
        for name, value in params.items():
            card = reg.get(tool).parameters[name]
            assert card.min <= value <= card.max, f"{tool}.{name}={value} outside its range"
            assert name not in reg.get(tool).frozen_parameters, \
                f"{tool}.{name} is frozen; gate 3 refuses a graph that proposes it"

    steps = varied["rfd3_design"]["diffusion_steps"]
    assert steps == 169, (
        "FourNodePolicy's exploring 170 as a fraction of the 20-200 range it was written "
        f"against (0.83), rounded to the declared int type; got {steps}")
    assert varied["ligandmpnn_design"]["temperature"] == 0.35


def _without_comments(worker: str) -> str:
    """A worker's code with its comments removed.

    Every rule asserted against a worker's source is about what it DOES, and these workers
    carry comments naming the defect each fix replaced - `jump="1"`, `scores.get("fa_rep",
    0.0)` - so a naive text match trips over the explanation of the thing it is checking for.
    Both of these tests caught their own documentation on the first run.
    """
    return "\n".join(line.split("#", 1)[0] for line in worker.splitlines())


def test_the_fastrelax_worker_computes_interaction_energy_by_selector(reg):
    """Backlog G4's missing metric, and the one choice in it that could be silently wrong.

    `interaction_energy` is the only number this stage reports that measures BINDING rather
    than geometry, and it was not computed at all: a converged, well-packed pose that does not
    bind was indistinguishable from a real binder by anything the campaign measured.

    The port is **selector-based**, matching upstream's own `scripts/fastrelax.py`:
    `ResiduePropertySelector(LIGAND)` against its complement. A chain-based split
    (`jump="1"`, or `chains="A"/"B"`) would be correct only if the ligand were its own chain,
    which is a property of the input rather than of the tool - and wrong silently, by
    measuring the energy between two halves of the protein.

    Asserted against the worker source because pyrosetta is not installed in the local tier
    and the real call needs a pose. That is a weaker test than running it, and it is the part
    that can be checked without hardware: `impress-a validate-tasks` is what proves the
    number arrives.
    """
    from impress_a.tools import rosetta_agents

    worker = _without_comments(rosetta_agents._FASTRELAX_WORKER)
    assert "InteractionEnergyMetric" in worker
    assert "ResiduePropertySelector(ResidueProperty.LIGAND)" in worker, \
        "the selector pair must be upstream's own, not a chain or jump split"
    assert "NotResidueSelector(ligand_sel)" in worker
    assert "jump" not in worker, \
        "a jump-based interface is right only if the ligand is its own chain"
    assert "no LIGAND-property residue in the pose" in worker, \
        "an empty ligand selection must omit the metric, not compute a confident zero"


def test_no_rosetta_metric_is_defaulted_to_zero(reg):
    """`scores.get("fa_rep", 0.0)` reported a fabricated zero for a term Rosetta had not
    computed - and 0.0 is a *passing* fa_rep, so a broken score function read as a perfectly
    packed structure. The invariant is that an adapter omits what it could not read and
    `metrics_reported` turns that into an integrity failure; a default silently converts "the
    tool broke" into "the design is good".
    """
    from impress_a.tools import rosetta_agents

    for name in ("_PACKMIN_WORKER", "_FASTRELAX_WORKER", "_FILTER_SHAPE_WORKER"):
        code = _without_comments(getattr(rosetta_agents, name))
        assert ", 0.0)" not in code, (
            f"{name}: a metric defaulted to 0.0. Omit it instead - the presence gate is what "
            f"catches an unreadable value, and a fabricated zero PASSES a max-bound gate, so "
            f"a broken score function reads as a perfectly packed structure")


def test_every_calibrated_threshold_matches_upstreams_prod_value(reg):
    """The four numbers, once, with their source - so a later edit has to argue with it.

    Read off `examples/small_molecule_binding/run_small_molecule_binding.py`'s `PROD`
    instance, which has months of multi-node campaigns behind it:
    `fastrelax_max_fa_rep=100.0`, `fastrelax_max_score=-250.0` (data range -193 to -510),
    `fastrelax_max_interact=-8.0` (p75 = -8.8), `interface_min_sc=0.55`,
    `backbone_min_ss_fraction=0.5`, `fold_min_plddt=75.0`.

    `fold_min_plddt` is the one that needs its rescale stated: it is a 0-100 figure upstream
    and `complex_plddt` here is the 0-1 one, so 75.0 becomes 0.75. And `fold_min_ligand_iptm`
    is **None** in PROD - upstream leaves that gate off - so this project is stricter than the
    reference on exactly one axis, which every T3 figure has to say.
    """
    def acceptance(tool, metric):
        for g in reg.get(tool).qc_gates:
            if (g.role == "acceptance" and g.id == "metric_in_range"
                    and g.params.get("metric") == metric):
                return g.params.get("min"), g.params.get("max")
        raise AssertionError(f"no acceptance gate on {tool}.{metric}")

    assert acceptance("fastrelax", "fa_rep") == (None, 100.0)
    assert acceptance("fastrelax", "total_score") == (None, -250.0)
    assert acceptance("fastrelax", "interaction_energy") == (None, -8.0)
    assert acceptance("filter_shape", "shape_complementarity")[0] == 0.55
    assert acceptance("rfd3_design", "ss_fraction")[0] == 0.5
    assert acceptance("boltz_predict", "complex_plddt") == (0.75, 1.0), \
        "PROD's fold_min_plddt is 75.0 on a 0-100 scale; complex_plddt is the 0-1 one"
    assert acceptance("boltz_predict", "ligand_iptm")[0] == 0.4, \
        "kept, and stricter than PROD, which leaves this gate off entirely"


def test_filter_shape_measures_the_protein_ligand_interface(reg):
    """Backlog G5: `jump="1"` measures whatever jump 1 happens to be.

    If the ligand is not across jump 1 the number is not wrong in any visible way - it is a
    shape complementarity between two parts of the protein, in exactly the range a real
    interface produces. Upstream splits by chain instead, which is right only when the ligand
    is its own chain, and that is a property of the input rather than of the tool. So the pair
    is the ligand residue PROPERTY against its complement, the same pair the interaction
    energy port uses.

    Asserted against the worker source, like the interaction-energy port and for the same
    reason: pyrosetta is not in the local tier. `impress-a validate-tasks` is what proves it
    builds.

    **The selectors are built through the Python API now, not a RosettaScripts XML string.**
    The XML was rejected outright by the PyRosetta build on Delta - `Element
    'ResidueProperty': This element is not expected` - so `filter_shape` ran 0 of 1 rows on
    job 23670171 and the chain stopped there with `boltz_predict` never reached. The old
    version of this test asserted the XML spelling, which is the one thing it could check and
    was never evidence that the schema would accept it; the previous docstring said as much
    ("the XML is the one part of this that no local test can exercise"). The Python route has
    no schema in it, and it is the same pair of calls the interaction-energy port already
    makes, so the two ports agree by construction instead of by two spellings kept in step.
    Confirmed against job 23670171's own relaxed pose: 1 ligand residue, SC = 0.612.
    """
    from impress_a.tools import rosetta_agents

    worker = rosetta_agents._FILTER_SHAPE_WORKER
    code = _without_comments(worker)
    assert 'jump="1"' not in code, "the interface must not be chosen by jump number"
    assert 'chains="A"' not in code, "nor by chain letter - that is the input's business"
    assert "XmlObjects" not in code, (
        "the RosettaScripts schema rejected this build's selector names; building the filter "
        "in Python removes the schema from the path")
    assert "ResiduePropertySelector(_ResidueProperty.LIGAND)" in code, \
        "the ligand is selected by residue PROPERTY, whatever the chain layout is"
    assert "NotResidueSelector(ligand_sel)" in code, "against its own complement"
    assert "sc_filter.selector1(" in code and "sc_filter.selector2(" in code, \
        "both sides of the interface must be set explicitly"
    assert "sc_filter.quick(False)" in code, \
        "quick mode is a faster, less accurate SC; upstream sets it explicitly and so must we"
    assert "Refusing rather than falling back" in worker, (
        "a fallback to a jump or chain split would keep producing numbers while measuring a "
        "different interface, and nothing downstream could tell")
    assert "sc_selector_mode" in worker, \
        "which interface produced the number must be a reported metric, not a log line"


def test_rfd3_partial_diffusion_would_have_to_drop_length():
    """A guard that abstains today and fires the moment partial diffusion is declared.

    RFD3's `DesignInputSpecification` validator rejects `length` outright whenever
    `partial.input`/`partial_t` are set - length is inferred from the input structure in that
    mode (`ValidationError: ... Length argument must not be provided during partial
    diffusion`). The committed `ALR_binder_design.json` carries BOTH `partial.input` and
    `"length": "70-170"`, and that is correct today only because `rfd3_design` declares no
    `partial_t` and no input port, so partial diffusion cannot be requested.

    The sibling example paid for this: job `21928556`, 3 of 3 pipelines that reached guided
    feedback crashed on their first attempt, fixed with `partial.pop('length', None)`. Our
    `_inputs_with_absolute_paths` rewrites `input` paths and nothing else, so it would carry
    `length` straight through. Backlog C8.

    So this does not assert the fix exists - it asserts that the day someone declares
    `partial_t`, they cannot also leave `length` in place unnoticed.
    """
    import json as _json

    spec_yaml = pathlib.Path("toolkits/rfd3/tools/rfd3_design/spec.yaml").read_text()
    declares_partial = "partial_t" in spec_yaml

    base = pathlib.Path("campaigns/data/alr/ALR_binder_design.json")
    carries_length = any(
        isinstance(entry, dict) and "length" in entry
        for entry in _json.loads(base.read_text()).values())

    if not declares_partial:
        # The abstaining branch, pinned so it cannot quietly become vacuous: `length` is the
        # from-scratch contig and must stay, because from-scratch is the only mode there is.
        assert carries_length, (
            f"{base} no longer carries `length`, and nothing declares `partial_t` - so "
            f"from-scratch diffusion has lost its contig. If partial diffusion was just "
            f"added, this test's other branch is the one to read")
        return

    source = pathlib.Path("src/impress_a/tools/rfd3_agents.py").read_text()
    assert not carries_length or 'pop("length"' in source or "pop('length'" in source, (
        "rfd3_design now declares `partial_t`, so partial diffusion is reachable, and "
        f"{base} still carries `length` - RFD3's validator rejects that combination and every "
        "guided run would fail its input validation. Drop `length` when writing the guided "
        "spec, as examples/small_molecule_binding's _write_guided_rfd3_json does (backlog C8)")


def test_the_rfd3_sidecar_metrics_come_from_the_shape_rfd3_actually_writes(tmp_path):
    """Every declared metric must be readable from a real `*_model_*.json`, at its real depth.

    The spec declared `ca_deviation` and `ligand_clashes` with the key names GUESSED, and said
    so: "the key names are inferred rather than observed ... the gates land when one real
    out_dir confirms the names". Job 23670171 is that out_dir, and it failed the
    `metrics_declared_and_finite` integrity row on exactly those two - while `helix_fraction`
    and `sheet_fraction`, guessed in the same breath, came back fine.

    What the file actually holds, inside one top-level `metrics` object:

        max_ca_deviation            the name was wrong - it is a MAX, not a mean
        n_clashing.ligand_clashes   the name was right, the SPELLING wrong
        helix_fraction              guessed right
        sheet_fraction              guessed right

    **The dot in `n_clashing.ligand_clashes` is part of the key, not a path.** `metrics` is
    flat; there is no `n_clashing` object. That was misread once in the other direction, and
    the fixture below is written from `list(metrics)` on the real file precisely so the
    distinction is pinned: a test built from a nested fixture would pass against a lookup
    that descends and fail against the file that exists.
    """
    import gzip

    from impress_a.tools.rfd3_agents import _sidecar_metrics

    cif = tmp_path / "ALR_binder_design_partial_0_model_0.cif.gz"
    cif.write_bytes(gzip.compress(b"# not read by _sidecar_metrics\n"))
    cif.with_name("ALR_binder_design_partial_0_model_0.json").write_text(json.dumps({
        "metrics": {
            "max_ca_deviation": 0.053571462631225586,
            "n_chainbreaks": 0,
            "n_clashing.interresidue_clashes_w_sidechain": 0,
            "n_clashing.interresidue_clashes_w_backbone": 0,
            "n_clashing.ligand_clashes": 0,
            "n_clashing.ligand_min_distance": 2.9610626697540283,
            "helix_fraction": 0.7112676056338029,
            "sheet_fraction": 0.0,
            "num_residues": 142,
        },
        "seed": 1602315461,
    }))

    got = _sidecar_metrics(cif)
    assert got["ca_deviation"] == pytest.approx(0.0536, abs=1e-4), \
        "ca_deviation must be read from `max_ca_deviation`"
    assert got["ligand_clashes"] == 0.0, \
        "`n_clashing.ligand_clashes` is one key with a dot in it, not a nested lookup"
    assert got["helix_fraction"] == pytest.approx(0.7113, abs=1e-4)
    assert got["sheet_fraction"] == 0.0
    # Every metric the spec declares, so the integrity gate that failed on hardware passes.
    assert {"ca_deviation", "ligand_clashes", "helix_fraction", "sheet_fraction"} <= set(got)
