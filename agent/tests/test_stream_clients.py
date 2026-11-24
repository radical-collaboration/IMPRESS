"""The two ROME-stream clients (item 13, EI.10).

**The outage case is the subject.** Scoring arithmetic is the stream's, and attribution is the
contract's — `SurrogateResponse` cannot be built without `(model_id, version)`. What only these
tools can get wrong is what they do when the stream is not there, and the wrong answer is a
number rather than an error: a defaulted score is well-formed, enters the design tree, gets
ranked on, and trains the next round of the model that was supposed to produce it. No QC gate
can catch that. So four distinct absences are asserted to raise, and one test asserts the
positive form — that nothing in the module has a default-score path at all.

The second subject is `dg_lcb`, which is omitted rather than defaulted when sigma is missing,
because an LCB computed without a sigma *is* the posterior mean wearing the name of a
conservative estimate and item 14 ranks on it.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

# `fake_stream` is this directory's own module, which ruff groups with the third-party
# imports because it cannot know that. The blank-line grouping below is ruff's, not a
# statement about where these come from.
from asteer.contracts.surrogate import SurrogateRequest, SurrogateResponse  # noqa: E402
from fake_stream import DownStream, FakeStream, ImpostorStream, WrongShapeStream  # noqa: E402

from impress_a.core.qc import GateOutcome  # noqa: E402
from impress_a.tools import asteer_design_agents as sc  # noqa: E402
from impress_a.tools import gates as impress_gates  # noqa: E402
from impress_a.tools import mock_asd_agents as mock_asd  # noqa: E402
from impress_a.tools.agent import TaskRequest  # noqa: E402
from impress_a.tools.spec import ToolSpec  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "toolkits" / "asteer_design"
MOCK = REPO / "toolkits" / "mock"

B_VALUES = {"preorg_rmsd": 1.21, "rotamer_entropy": 2.33,
            "ligand_rmsf": 0.84, "induced_fit_risk": 0.37}
C_VALUES = {"dg_corrected": -9.4}

STRUCTURE = "/designs/n0041/complex.cif"


def _spec(toolkit: Path, tool: str) -> ToolSpec:
    return ToolSpec(**yaml.safe_load((toolkit / "tools" / tool / "spec.yaml").read_text()))


def _run(agent, params: dict | None = None, structure: str | None = STRUCTURE,
         node_id: str = "n0041") -> dict:
    """Through `parameterize` so declared defaults resolve, as a real task would."""
    req = TaskRequest(tool=agent.spec.id, params=dict(params or {}),
                      inputs={"structure": structure} if structure else {},
                      node_id=node_id)
    resolved = agent.parameterize(req)
    return asyncio.run(agent.run(req, resolved))


def _preorg():
    return sc.PreorgScoreAgent(spec=_spec(DESIGN, "preorg_score"))


def _affdelta():
    return sc.AffDeltaScoreAgent(spec=_spec(DESIGN, "affdelta_score"))


# ---------------------------------------------------------------------------
# the outage, which is what this episode is for
# ---------------------------------------------------------------------------


def test_an_unbound_model_refuses_and_says_how_to_bind_one():
    agent = _preorg()
    with pytest.raises(sc.StreamUnavailable) as exc:
        _run(agent)
    message = str(exc.value)
    assert "pocket_preorg" in message
    assert "bind_stream" in message, "the refusal must name the fix, not only the fault"
    assert "default score" in message


def test_a_stream_that_raises_is_an_outage_and_chains_its_cause():
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, DownStream()), \
            pytest.raises(sc.StreamUnavailable) as exc:
        _run(agent)
    assert "TimeoutError" in str(exc.value)
    assert isinstance(exc.value.__cause__, TimeoutError), (
        "the cause must survive, or a timeout and a crash read identically in a log"
    )


def test_a_stream_answering_the_wrong_shape_is_an_outage_with_extra_steps():
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, WrongShapeStream()), \
            pytest.raises(sc.StreamUnavailable) as exc:
        _run(agent)
    assert "SurrogateResponse" in str(exc.value)
    assert "asteer.contracts.surrogate" in str(exc.value)


def test_a_stream_answering_for_another_model_is_refused():
    """The dangerous one: the numbers are well-formed and attributed, to the wrong weights."""
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, ImpostorStream(answers_as="pocket_preorg")), \
            pytest.raises(sc.StreamUnavailable) as exc:
        _run(agent)
    assert "pocket_preorg" in str(exc.value)
    assert "CON-5" in str(exc.value)


def test_no_default_score_path_exists_in_the_module():
    """The positive form of the four tests above, asserted over the source.

    Every test above shows one absence raising. This one says there is no fifth absence
    waiting to be found: a default score would have to come from a literal in this module,
    and the only numeric literals it carries are the LCB's default multiplier and the version
    floor. Crude, and it is the one check that keeps working when someone adds a path the
    four tests above do not cover.
    """
    # Through the imported module, not a repo-relative path -- the source that matters is the
    # one that runs, and the path stops being true when the module moves repos (H4). H7 then
    # merged three modules into that file, so slice back to this one's section before the
    # grep: liganchor's burial interpolation carries a `= 0.0` that is not a defaulted score,
    # and a grep over all three would fail on it for a reason this test is not about.
    import impress_a.tools.asteer_design_agents as mod
    whole = Path(mod.__file__).read_text()
    marker = "# (was `asteer/impress/stream_clients.py`, moved in H7)"
    assert marker in whole, (
        "the section banner this test slices on is gone. Re-anchor it rather than letting the "
        "grep below run over sections it was never written for, or silently over nothing"
    )
    source = whole[whole.index(marker):]
    for forbidden in ("values.get(", ".get(name, 0", "or 0.0", "= 0.0"):
        assert forbidden not in source, (
            f"{forbidden!r} in the stream-client section of {Path(mod.__file__).name}: a "
            "defaulted score is the one failure these two agents exist to prevent"
        )


# ---------------------------------------------------------------------------
# the happy path, and what rides on it
# ---------------------------------------------------------------------------


def test_a_score_round_trips_and_carries_its_model_version():
    agent = _preorg()
    stream = FakeStream(sc.MODEL_B, B_VALUES, {"preorg_rmsd": 0.26}, version=3)
    with sc.bound_stream(sc.MODEL_B, stream):
        out = _run(agent)
    assert out["result"] == "preorg_score"
    assert out["metrics"]["preorg_rmsd"] == 1.21
    assert out["metrics"]["sigma_preorg"] == 0.26
    assert set(out["model_versions"]) == set(out["metrics"]), (
        "every reported metric needs an attribution, not just the headline one"
    )
    assert set(out["model_versions"].values()) == {"pocket_preorg@v3"}


def test_the_design_passes_through_unchanged():
    """A scoring stage annotates a design; it does not produce a new one."""
    agent = _preorg()
    with sc.bound_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES)):
        out = _run(agent)
    assert out["outputs"] == {"structure": STRUCTURE}


def test_the_request_carries_the_node_and_the_campaign():
    agent = _preorg()
    stream = FakeStream(sc.MODEL_B, B_VALUES)
    with sc.bound_stream(sc.MODEL_B, stream):
        _run(agent, {"design_campaign_id": "asd-smb-mock"}, node_id="n0041")
    assert len(stream.seen) == 1
    seen = stream.seen[0]
    assert (seen.node_id, seen.design_campaign_id) == ("n0041", "asd-smb-mock")
    assert seen.features["structure"] == STRUCTURE


def test_an_empty_wired_structure_is_refused_rather_than_scored():
    """A wired port can still arrive empty, and scoring an empty path would report on it."""
    agent = _preorg()
    with sc.bound_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES)), \
            pytest.raises(ValueError, match="nothing to score"):
        _run(agent, structure=None)


# ---------------------------------------------------------------------------
# dg_lcb: the sign, and the omission
# ---------------------------------------------------------------------------


def test_the_bound_is_the_upper_one_because_delta_g_is_minimised():
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, FakeStream(sc.MODEL_C, C_VALUES, {"dg_corrected": 0.8})):
        out = _run(agent, {"lcb_k": 2.0})
    assert out["metrics"]["dg_corrected"] == -9.4
    assert out["metrics"]["sigma_dg"] == 0.8
    assert out["metrics"]["dg_lcb"] == pytest.approx(-9.4 + 2.0 * 0.8), (
        "mean + k*sigma: ΔG is minimised, so the conservative bound is the upper one"
    )


def test_k_zero_ranks_on_the_mean_and_says_so_by_arithmetic():
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, FakeStream(sc.MODEL_C, C_VALUES, {"dg_corrected": 0.8})):
        out = _run(agent, {"lcb_k": 0.0})
    assert out["metrics"]["dg_lcb"] == pytest.approx(out["metrics"]["dg_corrected"])


def test_no_sigma_means_no_bound_and_the_gate_catches_it():
    """The decision this episode carries, end to end: omitted, then refused.

    An LCB with no sigma is the posterior mean under another name, so the adapter omits it —
    and `metrics_reported` is what turns the omission into the integrity failure it is. 0.0
    would have passed any bound anyone put on it.
    """
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, FakeStream(sc.MODEL_C, C_VALUES, sigmas={})):
        out = _run(agent)
    assert "dg_lcb" not in out["metrics"]
    assert "sigma_dg" not in out["metrics"]

    qc = impress_gates.evaluate(agent.spec, out)
    failed = [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL]
    assert "metrics_reported" in failed


def test_a_calibrated_answer_passes_every_gate_the_spec_declares():
    agent = _affdelta()
    with sc.bound_stream(sc.MODEL_C, FakeStream(sc.MODEL_C, C_VALUES, {"dg_corrected": 0.8})):
        out = _run(agent)
    qc = impress_gates.evaluate(agent.spec, out)
    assert [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL] == []


# ---------------------------------------------------------------------------
# attribution: by construction first, by gate second
# ---------------------------------------------------------------------------


def test_the_contract_refuses_an_unversioned_response():
    """CON-5 by construction: there is no code path that produces an unattributed score."""
    with pytest.raises(ValueError, match="model_id is required"):
        SurrogateResponse(request_id="r", model_id="", version=1)
    with pytest.raises(ValueError, match="version is required"):
        SurrogateResponse(request_id="r", model_id="aff_delta", version=-1)


def test_surrogate_version_present_passes_on_what_the_client_emits():
    """EI.7's gate over this episode's real payload, which is the only honest way to pair them."""
    agent = _preorg()
    with sc.bound_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES)):
        out = _run(agent)
    result = impress_gates.get("surrogate_version_present")(
        out, {"metrics": sorted(out["metrics"])})
    assert result.outcome is GateOutcome.PASS


def test_surrogate_version_present_fails_when_the_attribution_is_stripped():
    """What makes the test above mean something."""
    agent = _preorg()
    with sc.bound_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES)):
        out = _run(agent)
    out["model_versions"] = {}
    result = impress_gates.get("surrogate_version_present")(
        out, {"metrics": sorted(out["metrics"])})
    assert result.outcome is GateOutcome.FAIL
    assert "integrity" in result.detail


# ---------------------------------------------------------------------------
# the binding
# ---------------------------------------------------------------------------


def test_a_binding_nests_and_restores_the_previous_one():
    outer, inner = FakeStream(sc.MODEL_B, B_VALUES), FakeStream(sc.MODEL_B, B_VALUES)
    with sc.bound_stream(sc.MODEL_B, outer):  # noqa: SIM117 -- the nesting IS the subject
        with sc.bound_stream(sc.MODEL_B, inner):
            assert sc.stream_for(sc.MODEL_B) is inner
        assert sc.stream_for(sc.MODEL_B) is outer, "a swapped stream must restore, not clear"
    with pytest.raises(sc.StreamUnavailable):
        sc.stream_for(sc.MODEL_B)


def test_unbinding_twice_is_a_shutdown_not_an_error():
    sc.bind_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES))
    sc.unbind_stream(sc.MODEL_B)
    sc.unbind_stream(sc.MODEL_B)
    with pytest.raises(sc.StreamUnavailable):
        sc.stream_for(sc.MODEL_B)


def test_binding_an_empty_model_id_is_refused():
    with pytest.raises(ValueError, match="model_id is required"):
        sc.bind_stream("", FakeStream(sc.MODEL_B, B_VALUES))


# ---------------------------------------------------------------------------
# the twins, and the toolkit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "tool"),
    [(mock_asd.MockPreorgScoreAgent, "mock_preorg_score"),
     (mock_asd.MockAffDeltaScoreAgent, "mock_affdelta_score")],
)
def test_each_twin_populates_every_gated_metric_and_attributes_them(cls, tool):
    agent = cls(spec=_spec(MOCK, tool))
    out = _run(agent, {"model_version": 7})
    qc = impress_gates.evaluate(agent.spec, out)
    assert [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL] == []
    assert set(out["model_versions"]) == set(out["metrics"])
    assert all(v.endswith("@v7") for v in out["model_versions"].values()), (
        "the version dial is what lets a mock campaign watch attribution follow a swap"
    )


def test_the_twins_and_the_real_clients_report_the_same_payload_shape():
    """They share `_payload`, and this is what says so rather than the docstring."""
    real = _preorg()
    with sc.bound_stream(sc.MODEL_B, FakeStream(sc.MODEL_B, B_VALUES, {"preorg_rmsd": 0.26})):
        real_out = _run(real)
    twin_out = _run(mock_asd.MockPreorgScoreAgent(spec=_spec(MOCK, "mock_preorg_score")))
    assert set(real_out) == set(twin_out)
    assert set(real_out["metrics"]) == set(twin_out["metrics"])
    assert set(real_out["outputs"]) == set(twin_out["outputs"])


def test_a_collapsed_posterior_is_reachable_on_the_twin_for_calibration_in_range():
    """The dial exists so EI.7's acceptance gate gets a payload to refuse with no allocation."""
    agent = mock_asd.MockAffDeltaScoreAgent(spec=_spec(MOCK, "mock_affdelta_score"))
    out = _run(agent, {"sigma_floor": 0.0})
    assert out["metrics"]["sigma_dg"] <= 0.05
    result = impress_gates.get("calibration_in_range")(out, {"metric": "sigma_dg", "min": 0.1})
    assert result.outcome is GateOutcome.FAIL
    assert "collapsed" in result.detail


@pytest.mark.parametrize("tool", ["preorg_score", "affdelta_score"])
def test_each_tool_ships_a_fixture_that_really_fails_the_gate_it_names(tool):
    """Stronger than checking the declared set: the payload is run through `gates.evaluate`.

    EI.12's version of this test asserted only that `failing_gates` named gates the spec
    declares. A fixture can satisfy that and still not fail anything, which would make it a
    passing payload filed as a known-bad one. Rendered labels are compared by prefix because
    `metric_in_range` renders as `metric_in_range[<metric>]`.
    """
    spec = _spec(DESIGN, tool)
    fixtures = sorted((DESIGN / "tools" / tool / "tests").glob("*.bad.json"))
    assert fixtures, f"{tool} ships no known-bad fixture"
    for path in fixtures:
        payload = json.loads(path.read_text())
        assert payload["why"].strip(), f"{path.name} does not say why it is bad"
        declared = {g.id for g in spec.qc_gates}
        assert set(payload["failing_gates"]) <= declared

        qc = impress_gates.evaluate(spec, payload["output"])
        failed = [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL]
        assert failed, f"{path.name} is filed as known-bad and passes every gate"
        for named in payload["failing_gates"]:
            assert any(label.startswith(named) for label in failed), (
                f"{path.name} claims {named!r} fails; what failed was {failed}"
            )


def test_the_toolkit_registers_in_a_cold_interpreter():
    """Both specs load, the entries resolve, and no gate id is unresolvable.

    A cold interpreter because `_load_toolkit` is all-or-nothing on gate ids: if either spec
    declared one of EI.7's gates, this toolkit would register NOTHING and the only evidence
    would be a line in `reg.errors` (item 39). That is why neither spec declares one yet, and
    this is the test that notices if somebody adds one.
    """
    # Named exactly, because `search_paths` always appends impress-a's own bundled
    # `toolkits/` and a substring filter picks up its `mock_score` too.
    ours = ["preorg_score", "affdelta_score", "mock_preorg_score", "mock_affdelta_score"]
    code = (
        "from impress_a.tools.registry import Registry;"
        f"r = Registry().load();"
        f"print(sorted(t for t in r.ids() if t in {ours!r}),"
        "      [e for e in r.errors if 'asteer_design' in e])"
    )
    out = subprocess.run([sys.executable, "-c", code], check=False,
                         capture_output=True, text=True, cwd=REPO,
                         env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.strip() == (
        "['affdelta_score', 'mock_affdelta_score', 'mock_preorg_score', 'preorg_score'] []"
    ), out.stdout


@pytest.mark.parametrize("tool", ["preorg_score", "affdelta_score"])
def test_neither_scoring_tool_declares_a_gpu(tool):
    """The GPU belongs to the stream's slot, not to the task that asks it a question.

    Declaring one here would double-count the device and make CON-3's slot arithmetic wrong —
    and `P1` would have forced it, which is half of why these are `P2`.
    """
    spec = _spec(DESIGN, tool)
    assert spec.resources.gpus == 0
    assert spec.pattern.value == "P2"


@pytest.mark.parametrize(
    ("real", "twin"),
    [("preorg_score", "mock_preorg_score"), ("affdelta_score", "mock_affdelta_score")],
)
def test_each_twin_takes_a_distinct_id_and_declares_the_mock_toolkit_field(real, twin):
    """Both halves of the twin convention, which have bitten this project once each.

    The id because `_load_toolkit` is all-or-nothing on a duplicate, so a twin sharing its
    real tool's id disables the whole real toolkit. The field because gate 6 classifies on
    `toolkit == "mock"` exactly, so a twin declaring `toolkit: mock_asd` is classified real.
    """
    real_spec, twin_spec = _spec(DESIGN, real), _spec(MOCK, twin)
    assert twin_spec.id != real_spec.id
    assert twin_spec.toolkit == "mock"
    assert real_spec.toolkit == "asteer_design"
    assert set(twin_spec.outputs) == set(real_spec.outputs)
    assert set(twin_spec.inputs) == set(real_spec.inputs)


def test_the_request_contract_refuses_an_unaddressed_question():
    with pytest.raises(ValueError, match="model_id is required"):
        SurrogateRequest(request_id="r", model_id="")


# ---------------------------------------------------------------------------
# J10: the features Model C is asked on, assembled from what the graph wired


def _upstream(tool: str, metrics: dict) -> dict:
    """One upstream task's payload, in the shape `_payload` writes."""
    return {"result": tool, "count": 1, "outputs": {"structure": STRUCTURE},
            "metrics": dict(metrics), "model_versions": {}}


def _features_of(agent, inputs: dict) -> dict:
    req = TaskRequest(tool=agent.spec.id, params={}, inputs=inputs, node_id="n0041")
    return agent._features(STRUCTURE, agent.parameterize(req), req)


def test_model_cs_features_carry_the_chain_metrics_keyed_by_the_tool_that_made_them():
    """Keyed by tool id and not by port, because a port is named for what it carries.

    `packmin` and `fastrelax` both emit `total_score` and they are not the same number -- on
    job 22726105 r0004, +1064.5 and -336.0 on the same structure. asteer's `chain-metrics-1`
    declares both as separate columns; this is what fills them apart.
    """
    features = _features_of(_affdelta(), {
        "structure": _upstream("fastrelax", {"total_score": -336.0, "fa_rep": 119.1,
                                             "interaction_energy": -26.4}),
        "dep0": _upstream("packmin", {"total_score": 1064.5}),
    })
    assert features["chain_metrics"]["fastrelax"]["total_score"] == -336.0
    assert features["chain_metrics"]["packmin"]["total_score"] == 1064.5
    assert features["structure"] == STRUCTURE


def test_an_ordering_only_dependency_still_contributes_its_metrics():
    """`dep0` is a real edge that ran a real stage, and the day a campaign adds one to reach
    a metric, this is what has to see it."""
    features = _features_of(_affdelta(), {
        "dep0": _upstream("boltz_predict", {"complex_plddt": 0.751, "ligand_iptm": 0.42}),
    })
    assert features["chain_metrics"]["boltz_predict"]["complex_plddt"] == 0.751


def test_a_non_numeric_metric_is_left_out_rather_than_coerced():
    """A string metric is not a feature; the featuriser then refuses it by name, which is
    where that refusal belongs -- a second copy of the column list here would be a second
    thing to keep in step."""
    features = _features_of(_affdelta(), {
        "structure": _upstream("filter_shape", {"shape_complementarity": 0.69,
                                                "sc_selector_mode": "two_sided"}),
    })
    assert features["chain_metrics"]["filter_shape"] == {"shape_complementarity": 0.69}


def test_a_boolean_is_not_a_metric_even_though_python_says_it_is_a_number():
    features = _features_of(_affdelta(), {
        "structure": _upstream("rfd3_steered_design",
                               {"ss_fraction": 0.63, "conditioning_applied": True}),
    })
    assert features["chain_metrics"]["rfd3_steered_design"] == {"ss_fraction": 0.63}


def test_model_bs_features_carry_no_chain_metric():
    """B is the FK potential, called on backbone x-hat-0. A reward computed from a chain
    metric would be computed from a number that does not exist yet when B is called."""
    features = _features_of(_preorg(), {
        "structure": _upstream("fastrelax", {"interaction_energy": -26.4}),
    })
    assert set(features) == {"structure", "pocket_selection"}


def test_the_chain_metrics_the_graph_wires_today_are_one_stages_worth():
    """**Backlog item 79, asserted rather than described.**

    `compose/composer.py` wires a linear stage to the one before it, so `affdelta_score`
    reaches `preorg_score` and nothing else. Assembling from what arrived is correct and
    keeps being correct when the campaign declares more; what it cannot do today is fill
    `chain-metrics-1`, which is why `FEATURISER_FOR_MODEL["aff_delta"]` is still the
    stand-in. If this test starts failing because more stages arrive, that is the item
    closing.
    """
    from asteer.features import FEATURISER_FOR_MODEL

    features = _features_of(_affdelta(), {
        "structure": _upstream("preorg_score", {"preorg_rmsd": 1.21, "rotamer_entropy": 2.33}),
    })
    assert sorted(features["chain_metrics"]) == ["preorg_score"]
    assert FEATURISER_FOR_MODEL["aff_delta"] == "standin-1", (
        "item 79: Model C cannot be switched to chain-metrics-1 until the graph wires the "
        "stages whose metrics it names"
    )
