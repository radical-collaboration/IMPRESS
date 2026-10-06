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
from typing import Any

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
    assert spec.params.get("rfd3_design", {}).get("input_spec_path"), \
        "the campaign must be able to configure the design target"

    spec.root = str(tmp_path)
    spec.backend, spec.backend_config = "concurrent", {"workers": 1}
    mgr = CampaignManager(spec, build_policy("D", spec, guard=False), reg)

    intent = ExperimentIntent(goal=spec.goal)          # a policy that asks for nothing
    merged = mgr.executor._apply_campaign_defaults(intent)
    assert merged.stages == spec.stages
    assert merged.params["rfd3_design"]["input_spec_path"] == \
        spec.params["rfd3_design"]["input_spec_path"], \
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
                             params={"rfd3_design": {"input_spec_path": "/tmp/other.json"}})
    merged = ex._apply_campaign_defaults(asked)
    assert merged.params["rfd3_design"]["input_spec_path"] == "/tmp/other.json", \
        "the policy wins on keys it set"
    assert merged.params["rfd3_design"]["num_designs"] == \
        spec.params["rfd3_design"]["num_designs"], "campaign fills the rest"
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

    async def fake_run_cmd(cmd, cwd=None, timeout_s=None):
        captured["cmd"], captured["cwd"] = cmd, cwd
        return "", ""

    monkeypatch.setattr(ligandmpnn_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("ligandmpnn_design")(reg.get("ligandmpnn_design"))
    req = TaskRequest(
        tool="ligandmpnn_design", node_id="r0001:r0_s1_ligandmpnn_design",
        inputs={"dep0": {"outputs": {
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
    pdb.write_text("ATOM      1  N   ALA A   1      11.104  13.207   2.100  1.00 20.00           N\n"
                    "END\n")

    captured: dict[str, list[str]] = {}

    async def fake_run_cmd(cmd, timeout_s=None):
        captured["cmd"] = cmd
        return "", ""

    monkeypatch.setattr(boltz_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("boltz_predict")(reg.get("boltz_predict"))
    req = TaskRequest(tool="boltz_predict",
                      inputs={"dep0": {"outputs": {"structure": str(pdb)}}})
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

    async def fake_run_cmd(cmd, cwd=None, timeout_s=None):
        captured["cmd"], captured["cwd"] = cmd, cwd
        return "", ""

    monkeypatch.setattr(ligandmpnn_agents, "run_cmd", fake_run_cmd)

    agent = reg.agent_for("ligandmpnn_design")(reg.get("ligandmpnn_design"))
    req = TaskRequest(
        tool="ligandmpnn_design", node_id="r0001:r0_s1_ligandmpnn_design",
        inputs={"dep0": {"outputs": {
            "backbone": ArtifactRef(type="Backbone", path="/fake/bb.pdb")}}})
    await agent.run(req, agent.parameterize(TaskRequest(tool="ligandmpnn_design")))

    cmd = captured["cmd"]
    assert cmd[0] == sys.executable, \
        "PATH happened to be right on job 22669509 because the launcher activates the " \
        "venv; this removes the dependency on that staying true"
    assert cmd[1] == "-P", \
        "without -P, CPython prepends the shim's directory - a LigandMPNN output dir - " \
        "to sys.path ahead of the stdlib"
    shim = pathlib.Path(cmd[2])
    assert shim.name == "mpnn_run.py" and shim.exists(), \
        "the shim must be written to disk before it can be run"
    assert "setattr(np, _alias, _builtin)" in shim.read_text()
    assert cmd[3] == str(mpnn), "the shim takes mpnn_dir as its first argument"
    assert str(mpnn / "run.py") not in cmd, \
        "run.py must never be invoked directly - it cannot import under numpy 2.x"
    assert cmd[4:6] == ["--model_type", "ligand_mpnn"], \
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

    out = subprocess.run([sys.executable, "-P", str(shim), str(mpnn), "--seed", "11"],
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
        ("-P must keep the shim's own directory off sys.path. Without it CPython prepends "
         "it, which puts a LigandMPNN *output* directory ahead of the stdlib for the whole "
         "run - invisible until something writes a .py-named file in there")


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
    out = subprocess.run([sys.executable, "-P", str(shim), str(mpnn)],
                         capture_output=True, timeout=120, check=False)
    err = out.stderr.decode()
    assert out.returncode != 0, "a raising run.py must not report success"
    assert "boom" in err, "the real exception has to reach SubprocessError's stderr"
    assert "run.py" in err, "runpy must set __file__, or the traceback names no source"

    # argparse exits 2 on a usage error; laundering that into 0 or 1 would mean a
    # malformed invocation reads as something else entirely.
    (mpnn / "run.py").write_text("import sys\nsys.exit(2)\n")
    out = subprocess.run([sys.executable, "-P", str(shim), str(mpnn)],
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

    out = subprocess.run([sys.executable, "-P", str(shim), str(empty)],
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
])
def test_cost_models_are_within_an_order_of_magnitude_of_measurement(
        reg, tool, dim, measured_s):
    """A magic number that is a bug report, per CLAUDE.md.

    These were literature guesses, and on job 22675512 the gpu ones summed to 0.65
    against an interlock cap of 0.60 - so the six-stage chain was refused three times
    and the policy truncated `boltz_predict`, the only producer of two of the campaign's
    four objectives, off the end. The run was then incapable of producing a front and
    said so nowhere.

    Job 22684607 measured all five. The bound here is deliberately loose in BOTH
    directions: an estimate feeding a refusal gate should err high, but being 50x high
    is how a budget gate starts refusing work that would have fit.
    """
    measured_h = measured_s / 3600
    declared = reg.get(tool).cost_model.cost[dim]
    assert declared >= measured_h, \
        f"{tool} declares {declared} {dim} but measured {measured_h:.4f} - an estimate " \
        "below the real cost lets a campaign overrun its budget"
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
    """`max: 0.0` on packmin was `fastrelax_max_total_score` ported onto the wrong stage.

    Upstream (`small_molecule_binding.py:678`) applies that threshold to fastrelax and
    gates nothing on packmin. Ours is PackRotamersMover + MinMover with no constraints -
    a preparation step. Job 22684607 measured +145.3 from packmin and -322.6 from
    fastrelax on that same structure one stage later, so the old gate failed a run that
    was going fine. fastrelax keeps the <= 0.0 gate, which is where it belongs.
    """
    def score_bound(tool):
        for g in reg.get(tool).qc_gates:
            if g.id == "metric_in_range" and g.params.get("metric") == "total_score":
                return g.params.get("max")
        return None

    assert score_bound("fastrelax") == 0.0, \
        "fastrelax is where upstream puts the <= 0.0 threshold, and it passed there"
    packmin_max = score_bound("packmin")
    assert packmin_max is not None and packmin_max > 145.3, \
        "packmin measured +145.3 on a healthy run; a bound at or below that rejects " \
        "every normal pre-relax score, and a gate that always fires carries no " \
        "information"


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
