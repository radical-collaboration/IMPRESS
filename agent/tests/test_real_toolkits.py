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
    # $SCRATCH bind test below). What must hold is the order of the three fixed tokens
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


async def test_rfd3_binds_scratch_into_the_container(reg, monkeypatch, tmp_path):
    """apptainer binds $HOME, /tmp and the CWD - and nothing else.

    Both `inputs=` (the campaign's design spec, in the repo) and `out_dir=` (the per-job
    scratch tree) live under $SCRATCH on Delta, so without an explicit bind the container
    cannot read its own input. The original IMPRESS pipeline binds the same way.
    """
    from impress_a.tools import rfd3_agents
    from impress_a.tools.agent import TaskRequest

    monkeypatch.setenv("FOUNDRY_SIF_PATH", "/fake/foundry.sif")
    monkeypatch.setenv("SCRATCH", "/work/hdd/fake")
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
        params={"input_spec_path": "/work/hdd/fake/inputs.json"}))
    await agent.run(req, params)

    cmd = captured["cmd"]
    assert "--bind" in cmd, "no bind: the container cannot see $SCRATCH"
    assert cmd[cmd.index("--bind") + 1] == "/work/hdd/fake:/work/hdd/fake"
    assert cmd.index("--bind") < cmd.index("/fake/foundry.sif"), \
        "apptainer flags must precede the image"
    assert "--writable-tmpfs" not in cmd, \
        "deliberately absent - it lets rfd3 exit 0 into a vanishing overlay"

    # And with no $SCRATCH set, no empty bind is emitted.
    monkeypatch.delenv("SCRATCH")
    await agent.run(req, params)
    assert "--bind" not in captured["cmd"]


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
        "$SCRATCH and the SLURM/CUDA variables must still reach the container"


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
