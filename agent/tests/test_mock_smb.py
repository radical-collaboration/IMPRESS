"""The small-molecule binding surrogate: `toolkits/mock/tools/mock_*` + `mock_smb_agents`.

Six `toolkit: mock` stand-ins for `rfd3_design -> ligandmpnn_design -> packmin ->
fastrelax -> filter_shape -> boltz_predict`, so the campaign engine's behaviour can be
watched on a laptop. Nothing here executes a real binary, needs a GPU, or says anything
about a molecule - every number the surrogates report is a seeded draw.

What this file pins, and why each claim needs pinning:

* **The mirror.** Ports, pattern, parameter names, metric names and every QC gate -
  thresholds included - match the real spec stage for stage. That is the whole value of
  the surrogate: a reader watching `complex_plddt` cross 0.75 here is watching the bar
  the Delta arms measure against. It is also the thing that silently decays, because the
  real specs are edited by people reading hardware and these are not.
* **The calibration.** The defaults pass, so a first run succeeds and the knobs have
  somewhere to move; `difficulty` is what takes that away, and it takes it away in two
  distinguishable ways - an acceptance shortfall around 0.55 that leaves a pattern's trust
  alone, and an integrity failure above ~0.75 that does not (decision 0013). A tutorial
  whose promised effect does not reproduce is worse than no tutorial, so the numbers
  `campaigns/README.md` quotes are asserted rather than described.
* **The propagation.** A knob on the first stage has to be able to change the last
  stage's verdict. Each agent inherits from its IMMEDIATE upstream only, because that is
  all `TaskRequest.inputs` carries; a stage reaching two hops back would silently freeze
  that number at its default and every knob above it would stop mattering, with nothing
  failing.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

from impress_a.compose.composer import Composer
from impress_a.compose.validate import SiteCaps, Validator
from impress_a.core.budget import BudgetLedger
from impress_a.core.decision import ExperimentIntent
from impress_a.core.qc import QCVerdict
from impress_a.tools import gates
from impress_a.tools.agent import TaskRequest
from impress_a.tools.registry import Registry

CHAIN = ["mock_rfd3_design", "mock_mpnn_design", "mock_packmin", "mock_fastrelax",
         "mock_filter_shape", "mock_boltz_predict"]
#: surrogate -> the real tool it stands in for. The pairing the mirror tests walk.
MIRRORS = {
    "mock_rfd3_design": "rfd3_design",
    "mock_mpnn_design": "ligandmpnn_design",
    "mock_packmin": "packmin",
    "mock_fastrelax": "fastrelax",
    "mock_filter_shape": "filter_shape",
    "mock_boltz_predict": "boltz_predict",
}
#: The output port each stage's successor consumes. Declared here so the chain runner
#: wires by port, exactly as `exec/dispatch` does, rather than guessing.
OUT_PORT = {"mock_rfd3_design": "backbone", "mock_mpnn_design": "structure",
            "mock_packmin": "structure", "mock_fastrelax": "structure",
            "mock_filter_shape": "structure", "mock_boltz_predict": "complex"}
IN_PORT = {"mock_mpnn_design": "backbone", "mock_packmin": "structure",
           "mock_fastrelax": "structure", "mock_filter_shape": "structure",
           "mock_boltz_predict": "structure"}
SPEC_PATH = "campaigns/mock-small-molecule-binding.yaml"


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _defaults(spec) -> dict:
    return {k: p.default for k, p in spec.parameters.items() if p.default is not None}


async def _run_chain(reg, overrides: dict[str, dict] | None = None,
                     node_id: str = "n000001-test"):
    """The six stages in order, each handed the previous one's payload on its own port.

    Returns `{tool_id: (metrics, QCReport)}`. Built here rather than through the executor
    because the claims under test are about the agents and their gates; the executor's own
    path is covered by `test_campaign.py`. `node_id` is what distinguishes one lineage's
    draw from another's, so a population of them is how a rate is measured.
    """
    overrides = overrides or {}
    out, prev, prev_tool = {}, None, None
    for tool_id in CHAIN:
        spec = reg.get(tool_id)
        params = _defaults(spec) | overrides.get(tool_id, {})
        inputs, ports = {}, {}
        if prev is not None:
            inputs[IN_PORT[tool_id]] = prev
            ports[IN_PORT[tool_id]] = OUT_PORT[prev_tool]
        req = TaskRequest(tool=tool_id, params=params, node_id=node_id,
                          inputs=inputs, input_ports=ports)
        raw = await reg.agent_for(tool_id)(spec).run(req, params)
        report = gates.evaluate(spec, raw)
        out[tool_id] = (raw["metrics"], report)
        prev = {"tool": tool_id, "outputs": raw["outputs"], "metrics": raw["metrics"],
                "qc": report.model_dump()}
        prev_tool = tool_id
    return out


async def _rates(reg, overrides, n=60):
    """Per-stage (failures, integrity failures) over `n` lineages, and the chain's pass count.

    A rate rather than one draw, because a single `node_id` is a single sample and the
    thresholds these tests are about are crossed gradually.
    """
    passed, failed, integrity = 0, {t: 0 for t in CHAIN}, {t: 0 for t in CHAIN}
    for i in range(n):
        out = await _run_chain(reg, overrides, node_id=f"n{i:06d}-rate")
        clean = True
        for tool_id, (_, report) in out.items():
            if report.verdict is QCVerdict.FAIL:
                failed[tool_id] += 1
                clean = False
            if not report.integrity_ok:
                integrity[tool_id] += 1
        passed += clean
    return passed, failed, integrity


# -- the mirror ------------------------------------------------------------------------

def test_the_surrogates_are_in_the_mock_toolkit(reg):
    """Gate 6 classifies by `ToolSpec.toolkit` exactly, never by a `mock_` prefix.

    A surrogate in a toolkit of its own would be classified REAL, so a campaign declaring
    `tool_delivery: real` would admit a chain of random number generators and report its
    draws as science - the documented failure gate 6 exists to prevent. The `mock_` in
    these ids is a convention; this field is the fact.
    """
    for tool_id in CHAIN:
        assert reg.get(tool_id).toolkit == "mock", tool_id


@pytest.mark.parametrize("surrogate,real", sorted(MIRRORS.items()))
def test_each_surrogate_mirrors_its_real_spec(reg, surrogate, real):
    """Pattern, ports, parameter names, metric names and every QC gate, thresholds included.

    The decay this catches is one-sided and quiet: the real specs move when somebody reads
    a measurement off hardware, these do not, and nothing else in the suite compares them.
    A surrogate whose `complex_plddt` bar has drifted from the campaign's still passes
    every other test in this file while teaching the wrong thing.

    `difficulty` is the one allowed divergence - it has no rfd3 counterpart, and
    `test_difficulty_is_the_only_parameter_without_a_real_counterpart` is what holds that
    exception to one.
    """
    m, r = reg.get(surrogate), reg.get(real)
    assert m.pattern is r.pattern
    assert {p: s.type for p, s in m.inputs.items()} == \
           {p: s.type for p, s in r.inputs.items()}
    assert {p: s.type for p, s in m.outputs.items()} == \
           {p: s.type for p, s in r.outputs.items()}
    assert set(m.parameters) - {"difficulty"} == set(r.parameters)
    assert m.metrics == r.metrics
    # Gates compared as (id, role, params), which is the whole of what a gate does.
    def shape(spec):
        return sorted((g.id, g.role, tuple(sorted(g.params.items(), key=repr)))
                      for g in spec.qc_gates)
    assert shape(m) == shape(r), f"{surrogate} no longer measures against {real}'s bars"


def test_difficulty_is_the_only_parameter_without_a_real_counterpart(reg):
    """An undocumented extra knob would quietly break the mirror, so there is exactly one.

    And it is documented in both places a reader looks: the spec's `trades` string and the
    toolkit's SKILL.md.
    """
    extra = {s: set(reg.get(s).parameters) - set(reg.get(r).parameters)
             for s, r in MIRRORS.items()}
    assert {k: v for k, v in extra.items() if v} == {"mock_rfd3_design": {"difficulty"}}
    assert "surrogate-only" in reg.get("mock_rfd3_design").parameters["difficulty"].trades
    assert "difficulty" in reg.skills["mock"]


def test_the_surrogate_chain_composes_and_passes_every_gate(reg):
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    assert len(g.nodes) == len(CHAIN)
    v = Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1),
                  BudgetLedger(limits={"gpu_hours": 4.0, "cpu_hours": 4.0}),
                  tool_delivery="mock")
    assert v.validate(g) is None


def test_gate_6_refuses_the_surrogate_chain_under_tool_delivery_real(reg):
    """The reason these are `toolkit: mock`, asserted on the chain rather than in prose."""
    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=CHAIN))
    v = Validator(reg, SiteCaps(gpu_api="cuda", gpus_per_node=1),
                  BudgetLedger(limits={"gpu_hours": 4.0, "cpu_hours": 4.0}),
                  tool_delivery="real")
    failure = v.validate(g)
    assert failure is not None and failure.gate == "tool_delivery"


# -- the campaign ----------------------------------------------------------------------

def test_the_campaign_declares_the_surrogate_chain_and_the_real_thresholds():
    """Its objectives are the Delta arms' own - the point of mirroring the bars.

    Read from the two YAML files rather than restated here, so this cannot be the place
    the two quietly disagree.
    """
    from impress_a.cli import load_spec

    mock = load_spec(SPEC_PATH)
    arms = yaml.safe_load(
        pathlib.Path("campaigns/delta-small-molecule-arms-smoke.yaml").read_text())
    assert mock.stages == CHAIN
    assert mock.tool_delivery == "mock"
    assert mock.backend == "concurrent", "a laptop campaign must not ask for Dragon"
    assert mock.goal == arms["goal"]
    assert [(o.name, o.min, o.max) for o in mock.objectives] == \
           [(o["name"], o.get("min"), o.get("max")) for o in arms["objectives"]]


def test_every_campaign_param_the_surrogate_campaign_sets_is_a_declared_parameter(reg):
    """A typo in a knob the README tells a reader to turn would be silently ignored."""
    from impress_a.cli import load_spec

    spec = load_spec(SPEC_PATH)
    for tool_id, params in spec.params.items():
        declared = set(reg.get(tool_id).parameters)
        assert set(params) <= declared, f"{tool_id}: {set(params) - declared}"


# -- the calibration -------------------------------------------------------------------

async def test_the_defaults_pass_every_gate_in_the_chain(reg):
    """So a first run succeeds and every knob has somewhere to move from.

    200 lineages, every stage, no exceptions - a surrogate whose default run fails for one
    lineage in fifty would send a reader hunting a bug in the engine. The tightest bar in
    the chain is `complex_plddt >= 0.75`; over these 200 the lowest draw is ~0.82, so the
    margin is real rather than the sampling being lucky.
    """
    worst = 1.0
    for node in range(200):
        out = await _run_chain(reg, node_id=f"n{node:06d}-cal")
        for tool_id, (_, report) in out.items():
            assert report.verdict is QCVerdict.PASS, (
                f"lineage {node}: {tool_id} failed "
                f"{[g.gate for g in report.gates if g.outcome.value == 'fail']}")
        worst = min(worst, out["mock_boltz_predict"][0]["complex_plddt"])
    assert worst > 0.78, f"the default margin over the 0.75 bar has shrunk to {worst}"


async def test_a_middling_difficulty_is_an_acceptance_shortfall_and_not_an_integrity_one(reg):
    """0.55: the backbone misses `ss_fraction >= 0.5` and clears the 0.3 integrity floor.

    Which is decision 0013's distinction, and the reason the dial is worth having: the node
    FAILs, and the pattern's trust is untouched. A surrogate that could only break things
    would teach that every failure costs trust.
    """
    out = await _run_chain(reg, {"mock_rfd3_design": {"difficulty": 0.55}})
    metrics, report = out["mock_rfd3_design"]
    assert 0.3 <= metrics["ss_fraction"] < 0.5
    assert report.verdict is QCVerdict.FAIL
    assert report.integrity_ok, "an acceptance shortfall must not count against trust"


async def test_a_high_difficulty_is_an_integrity_failure(reg):
    """0.85: `ss_fraction` goes under the `has_secondary_structure` floor.

    The node fails AND the pattern's trust suffers - the other half of 0013, and the half
    a reader can only tell apart by watching both.
    """
    out = await _run_chain(reg, {"mock_rfd3_design": {"difficulty": 0.85}})
    metrics, report = out["mock_rfd3_design"]
    assert metrics["ss_fraction"] < 0.3
    assert report.verdict is QCVerdict.FAIL
    assert not report.integrity_ok
    assert "has_secondary_structure" in {g.gate for g in report.gates
                                         if g.outcome.value == "fail"}


# -- the propagation -------------------------------------------------------------------

async def test_an_upstream_knob_changes_the_last_stages_verdict(reg):
    """`difficulty` on stage one decides whether stage six clears `complex_plddt >= 0.75`.

    This is the claim the whole surrogate rests on. If the draw stopped propagating, every
    stage would still pass its own gates at its own defaults and nothing in the suite would
    notice - the campaign would simply stop responding to its knobs.
    """
    _, easy, easy_integrity = await _rates(reg, {"mock_rfd3_design": {"difficulty": 0.0}})
    _, hard, hard_integrity = await _rates(reg, {"mock_rfd3_design": {"difficulty": 0.7}})
    assert easy["mock_boltz_predict"] == 0
    assert hard["mock_boltz_predict"] >= 50, \
        f"only {hard['mock_boltz_predict']}/60 lineages failed the last stage"
    # And at 0.7 it is still an acceptance story end to end: the campaign cannot satisfy
    # its Spec, and no pattern is demoted for it. The integrity failure is a separate
    # setting of the same dial, which is what makes the two worth telling apart.
    assert sum(easy_integrity.values()) == sum(hard_integrity.values()) == 0


async def test_every_stage_moves_when_the_stage_above_it_moves(reg):
    """Each link of the chain, separately, so a broken one names itself.

    Asserted link by link rather than end to end because `_inherit` silently falls back to
    a default: one agent reading the wrong metric name leaves the chain working and the
    knobs above that point inert, and an end-to-end test on `difficulty` alone would still
    pass as long as SOME path survived.
    """
    easy = await _run_chain(reg, {"mock_rfd3_design": {"difficulty": 0.0}})
    hard = await _run_chain(reg, {"mock_rfd3_design": {"difficulty": 0.7}})
    for tool_id, metric in (("mock_rfd3_design", "ss_fraction"),
                            ("mock_mpnn_design", "overall_confidence"),
                            ("mock_packmin", "total_score"),
                            ("mock_fastrelax", "interaction_energy"),
                            ("mock_filter_shape", "shape_complementarity"),
                            ("mock_boltz_predict", "complex_plddt")):
        assert easy[tool_id][0][metric] != hard[tool_id][0][metric], \
            f"{tool_id}.{metric} did not move - the draw stops propagating above it"


async def test_a_downstream_knob_can_rescue_a_marginal_chain(reg):
    """`diffusion_samples` is worth ~0.09 of pLDDT between 1 and 8, as picking the best of
    N is on the real tool. Without it the README's "turn this one" advice is a guess."""
    one = await _run_chain(reg, {"mock_boltz_predict": {"diffusion_samples": 1}})
    many = await _run_chain(reg, {"mock_boltz_predict": {"diffusion_samples": 25}})
    assert one["mock_boltz_predict"][0]["complex_plddt"] < \
        many["mock_boltz_predict"][0]["complex_plddt"]


# -- determinism -----------------------------------------------------------------------

async def test_the_same_inputs_draw_the_same_numbers_twice(reg):
    """A difference means a draw is keyed on something it should not be.

    `mock_agents._upstream` records that bug twice: seeding on the QC report made the
    science a function of the QC schema, and seeding on the input KEYS made a rename of the
    wiring reshuffle every downstream draw. These agents import it rather than copying it,
    and this is what would notice if a copy crept back.
    """
    first = await _run_chain(reg)
    second = await _run_chain(reg)
    assert {k: v[0] for k, v in first.items()} == {k: v[0] for k, v in second.items()}


async def test_the_draw_does_not_depend_on_the_qc_schema_or_the_port_names(reg):
    """The two bugs `_upstream` was taught by, asserted on this chain rather than assumed.

    An extra field on an upstream's QC report, and an upstream payload arriving under a
    different key, must both leave every downstream number unchanged.
    """
    spec = reg.get("mock_mpnn_design")
    params = _defaults(spec)
    upstream = {"tool": "mock_rfd3_design", "outputs": {"backbone": "backbone[1]"},
                "metrics": {"ss_fraction": 0.6, "num_models": 1.0},
                "qc": {"verdict": "pass", "gates": []}}
    agent = reg.agent_for("mock_mpnn_design")(spec)

    base = await agent.run(TaskRequest(
        tool="mock_mpnn_design", params=params, node_id="n1",
        inputs={"backbone": upstream},
        input_ports={"backbone": "backbone"}), params)

    noisier = dict(upstream, qc={"verdict": "pass", "gates": [], "a_new_field": 1})
    with_schema_change = await agent.run(TaskRequest(
        tool="mock_mpnn_design", params=params, node_id="n1",
        inputs={"backbone": noisier},
        input_ports={"backbone": "backbone"}), params)
    assert base["metrics"] == with_schema_change["metrics"]

    renamed = await agent.run(TaskRequest(
        tool="mock_mpnn_design", params=params, node_id="n1",
        inputs={"dep0": upstream}, input_ports={}), params)
    assert base["metrics"] == renamed["metrics"]
