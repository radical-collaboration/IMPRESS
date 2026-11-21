"""Model A's emitter (item 12a, EI.8).

**Two tests carry most of the value and neither is about arithmetic.**

`test_no_code_path_emits_select_hotspots` is the one this episode exists for. RFD3's own
documentation points at `select_hotspots`, M0 measured that the key resolves and is then
dropped by `build()`, and the resulting run completes and reports success conditioned on zeros
(items 26, 29). So the hazard is a *documented* feature that silently does nothing, and the
only defence against the next person adding it back is a test that fails when they do.

`test_a_donor_comes_from_the_bond_graph_not_the_type_table` is the one that makes the chemistry
trustworthy. `ALR.params` declares two `OH` oxygens and exactly one polar hydrogen, so by
Rosetta's own definition of a donor -- a heavy atom bearing one -- it has one donor, not two.
An atom-type table alone would have reported two. The test runs that difference on the
project's real ligand rather than on a fixture, because a fixture would have been written from
the same assumption as the code.

The rest pins the resname's colon (a verified RFD3 workaround that looks like a typo), the
entropy definition at both ends of its range, the refusals, and twin parity.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")


from impress_a.core.qc import GateOutcome  # noqa: E402
from impress_a.tools import asteer_design_agents as liganchor  # noqa: E402
from impress_a.tools import gates as impress_gates  # noqa: E402
from impress_a.tools import mock_asd_agents as mock_asd  # noqa: E402
from impress_a.tools.agent import TaskRequest  # noqa: E402
from impress_a.tools.spec import ToolSpec  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "toolkits" / "asteer_design"
MOCK = REPO / "toolkits" / "mock"

#: The project's own ligand, from the IMPRESS checkout beside this one. Used rather than a
#: fixture of our own on purpose: a fixture would carry the same assumptions as the parser, and
#: the interesting properties of this file (the `A:R` resname, one polar hydrogen for two
#: hydroxyls) are exactly the ones nobody would think to write into a fixture.
#:
#: Located relative to this repo rather than absolutely, so the path carries no username and
#: the tests skip rather than fail wherever the sibling checkout is not there.
ALR = REPO.parent / "IMPRESS" / "agent" / "campaigns" / "data" / "alr" / "ALR.params"
alr_only = pytest.mark.skipif(not ALR.exists(), reason="the IMPRESS checkout is not beside us")


def _spec(toolkit: Path, tool: str) -> ToolSpec:
    return ToolSpec(**yaml.safe_load((toolkit / "tools" / tool / "spec.yaml").read_text()))


def _run(agent, params: dict | None = None) -> dict:
    req = TaskRequest(tool=agent.spec.id, params=dict(params or {}), node_id="n0001")
    return asyncio.run(agent.run(req, agent.parameterize(req)))


def _real(params: dict | None = None) -> dict:
    agent = liganchor.LigAnchorProposeAgent(spec=_spec(DESIGN, "liganchor_propose"))
    return _run(agent, {"ligand_params_path": str(ALR), **(params or {})})


# ---------------------------------------------------------------------------
# the dead branch stays dead
# ---------------------------------------------------------------------------


def test_no_code_path_emits_select_hotspots():
    """The hazard is a documented feature that silently does nothing. Asserted over the source.

    M0, job `24155612`: `select_hotspots={"A:R": "S1,O5,O7,O8,S2,O6"}` resolves and annotates
    all six atoms, `build()` drops the annotation, and `feats.is_atom_level_hotspot` reaches
    the network as all zeros while the run completes and reports success.
    `infer_ori_strategy: "hotspots"` cannot build at all. A grep is crude and it is the only
    check that still works when someone adds the key in a path no payload test covers.
    """
    # Read through the IMPORTED module rather than a repo-relative path: the source that
    # matters is the one that actually runs, and a path guess stops being true the moment the
    # module moves repos (H4, and again in H7, which is when this line last changed).
    import impress_a.tools.asteer_design_agents
    import impress_a.tools.mock_asd_agents
    for mod in (impress_a.tools.asteer_design_agents, impress_a.tools.mock_asd_agents):
        module = Path(mod.__file__).name
        source = Path(mod.__file__).read_text()
        emitted = [line for line in source.splitlines()
                   if "select_hotspots" in line and not line.lstrip().startswith("#")
                   and "`select_hotspots`" not in line]
        assert not emitted, (
            f"{module} mentions select_hotspots outside a comment: {emitted}. The key resolves "
            "and is then dropped, so the run is conditioned on nothing and still reports "
            "success (items 26, 29)."
        )


@alr_only
def test_the_emitted_artifact_declares_the_channel_it_used():
    """A stored artifact must say which channel conditioned the design, not imply it."""
    out = _real()
    artifact = out["outputs"]["anchor_spec"]
    assert artifact["use_classifier_free_guidance"] is True
    assert set(artifact["cfg_features"]) == {"active_donor", "active_acceptor",
                                             "ref_atomwise_rasa"}
    assert "select_hotspots" not in json.dumps(artifact)
    assert artifact["schema"] == liganchor.ANCHOR_SPEC_SCHEMA, (
        "a consumer needs to be able to refuse a payload from a version it does not know"
    )


# ---------------------------------------------------------------------------
# the chemistry, measured on the real ligand
# ---------------------------------------------------------------------------


@alr_only
def test_a_donor_comes_from_the_bond_graph_not_the_type_table():
    """The difference between reading the file and reciting a table, on the real ligand.

    `ALR.params` has two `OH` oxygens (O3, O4) and one `Hpol` (H41, bonded to O4). Rosetta's
    definition of a donor is a heavy atom bearing a polar hydrogen, so this ligand has exactly
    one donor. A type table that called every `OH` a donor would have reported two, and the
    CFG channel would have claimed an H-bond donor that the file does not describe.
    """
    ligand = liganchor.parse_params(ALR)
    assert sorted(ligand.polar_hydrogens) == ["O4"]
    hydroxyls = sorted(a.name for a in ligand.atoms if a.atom_type == "OH")
    assert hydroxyls == ["O3", "O4"], "the premise of this test changed with the file"
    assert ligand.is_donor("O4") and not ligand.is_donor("O3")
    # Both are still acceptors: acceptor status is the table's job, donor status the graph's.
    assert ligand.is_acceptor("O3") and ligand.is_acceptor("O4")


@alr_only
def test_the_resname_keeps_its_colon():
    """`A:R`, not `ALR`. It looks like a typo and it is a verified RFD3 workaround.

    RFD3 misresolves the bare three-letter code; the colon is deliberate and is recorded in
    `IMPRESS/agent/toolkits/rfd3/SKILL.md`. M0's spike had to use this spelling or it would
    have tested the wrong thing. Anything that "cleans up" the resname breaks the run in a way
    that looks like a chemistry problem.
    """
    assert liganchor.parse_params(ALR).resname == "A:R"
    assert _real()["outputs"]["anchor_spec"]["ligand_resname"] == "A:R"


@alr_only
def test_only_donors_and_acceptors_are_anchored():
    """The sulfurs are not anchored, and M0's hand-written hotspot list included them.

    The spike asked for `S1,O5,O7,O8,S2,O6`. Rosetta's standard atom set gives thioether
    sulfur no ACCEPTOR flag, and in this ligand the `S` atoms are sulfonate sulfurs whose
    acceptors are the `OOC` oxygens bonded to them. So a hand-written list and a derived one
    disagree, and the derived one is the defensible half.
    """
    spec = liganchor.anchor_spec_from_params(ALR, max_anchor_atoms=32)
    assert spec.engaged_atoms, "nothing was anchored at all"
    assert not [a for a in spec.engaged_atoms if a.startswith("S")]
    ligand = liganchor.parse_params(ALR)
    for name in spec.engaged_atoms:
        assert ligand.is_donor(name) or ligand.is_acceptor(name)


@alr_only
def test_the_anchor_set_is_capped_and_deterministic():
    first = liganchor.anchor_spec_from_params(ALR, max_anchor_atoms=6)
    second = liganchor.anchor_spec_from_params(ALR, max_anchor_atoms=6)
    assert first.engaged_atoms == second.engaged_atoms, (
        "a selection that moves between runs cannot be what a regression test compares against"
    )
    assert first.n_engaged_atoms == 6
    assert liganchor.anchor_spec_from_params(ALR, max_anchor_atoms=99).n_engaged_atoms == 10, (
        "the cap is a ceiling, not a target: this ligand has ten anchorable atoms"
    )


@alr_only
def test_the_burial_target_runs_from_buried_to_exposed_over_charge():
    spec = liganchor.anchor_spec_from_params(
        ALR, max_anchor_atoms=99, buried_target_rasa=0.1, exposed_target_rasa=0.5)
    rasa = spec.features["ref_atomwise_rasa"]
    assert min(rasa.values()) == pytest.approx(0.1)
    assert max(rasa.values()) == pytest.approx(0.5)
    ligand = liganchor.parse_params(ALR)
    charges = {a.name: abs(a.charge) for a in ligand.atoms}
    most = max(rasa, key=lambda n: charges[n])
    assert rasa[most] == pytest.approx(0.1), "the most charged atom must be the most buried"


# ---------------------------------------------------------------------------
# anchor_entropy, at both ends
# ---------------------------------------------------------------------------


def test_entropy_is_zero_for_a_single_atom_rather_than_one_or_undefined():
    """`log(1)` is zero, so the ratio is undefined; 1.0 would call the most concentrated set
    maximally spread, and a crash would make a legitimate ligand unprocessable."""
    spec = liganchor.AnchorSpec(
        resname="A:R", engaged_atoms=("O4",),
        features={"active_donor": {"O4": 1.0}, "active_acceptor": {"O4": 1.0},
                  "ref_atomwise_rasa": {"O4": 0.15}},
        cfg_scale=1.5, cfg_t_max=1.0)
    assert spec.anchor_entropy == 0.0
    assert spec.n_engaged_atoms == 1


def test_entropy_is_one_for_an_evenly_weighted_set_and_falls_when_one_atom_dominates():
    even = liganchor.AnchorSpec(
        resname="X", engaged_atoms=("A", "B", "C", "D"),
        features={"active_donor": {}, "active_acceptor": {n: 1.0 for n in "ABCD"},
                  "ref_atomwise_rasa": {}},
        cfg_scale=1.5, cfg_t_max=1.0)
    assert even.anchor_entropy == pytest.approx(1.0)

    lopsided = liganchor.AnchorSpec(
        resname="X", engaged_atoms=("A", "B", "C", "D"),
        features={"active_donor": {"A": 1.0}, "active_acceptor": {n: 1.0 for n in "ABCD"},
                  "ref_atomwise_rasa": {}},
        cfg_scale=1.5, cfg_t_max=1.0)
    assert lopsided.anchor_entropy < even.anchor_entropy, (
        "an atom counting double concentrates the anchoring, so entropy must fall"
    )


# ---------------------------------------------------------------------------
# the refusals
# ---------------------------------------------------------------------------


def test_an_unknown_atom_type_refuses_and_names_it(tmp_path):
    """The alternative is treating it as apolar, which shrinks the anchor set silently."""
    path = tmp_path / "weird.params"
    path.write_text("NAME XYZ\nATOM  Q1  Zz   X   -0.5\nATOM  O1  OOC  X   -0.6\n")
    with pytest.raises(liganchor.UnknownAtomType, match="Zz"):
        liganchor.parse_params(path)


def test_a_ligand_with_no_polar_atoms_refuses_and_says_it_is_the_molecule(tmp_path):
    path = tmp_path / "alkane.params"
    path.write_text("NAME HEX\nATOM  C1  CH3  X   -0.1\nATOM  C2  CH2  X   -0.1\n")
    with pytest.raises(liganchor.LigandParseError, match="about the molecule"):
        liganchor.anchor_spec_from_params(path)


def test_a_params_file_with_no_name_record_refuses(tmp_path):
    path = tmp_path / "anon.params"
    path.write_text("ATOM  O1  OOC  X   -0.6\n")
    with pytest.raises(liganchor.LigandParseError, match="no NAME record"):
        liganchor.parse_params(path)


def test_the_missing_root_input_is_refused_by_the_agent():
    """A root, and `compose/validate.py:79`-`:81` waves an unsatisfied root input through."""
    agent = liganchor.LigAnchorProposeAgent(spec=_spec(DESIGN, "liganchor_propose"))
    with pytest.raises(liganchor.LigandParseError, match="no `ligand_params_path`"):
        _run(agent)


def test_two_feature_keys_are_refused_because_that_would_drop_a_channel():
    agent = liganchor.LigAnchorProposeAgent(spec=_spec(DESIGN, "liganchor_propose"))
    with pytest.raises(liganchor.LigandParseError, match="exactly three"):
        _run(agent, {"ligand_params_path": str(ALR),
                     "cfg_feature_keys": "active_donor,active_acceptor"})


@alr_only
def test_the_feature_keys_are_data_so_a_campaign_can_correct_the_spelling():
    """The source spec writes `active donor` with a space in two places and `active_donor` in
    others, and neither is verifiable off-cluster. A wrong key is item 26 again, so the fix has
    to be a campaign edit rather than a release."""
    out = _real({"cfg_feature_keys": "active donor,active_acceptor,ref_atomwise_rasa"})
    assert "active donor" in out["outputs"]["anchor_spec"]["cfg_features"]


# ---------------------------------------------------------------------------
# gates, the twin, and the toolkit
# ---------------------------------------------------------------------------


@alr_only
def test_the_real_tool_passes_every_gate_its_spec_declares():
    agent = liganchor.LigAnchorProposeAgent(spec=_spec(DESIGN, "liganchor_propose"))
    out = _run(agent, {"ligand_params_path": str(ALR)})
    qc = impress_gates.evaluate(agent.spec, out)
    assert [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL] == []


@alr_only
def test_a_one_atom_anchor_set_fails_acceptance_not_integrity():
    """Decision 0013: the tool worked and the molecule is the problem, so trust must not drop."""
    agent = liganchor.LigAnchorProposeAgent(spec=_spec(DESIGN, "liganchor_propose"))
    out = _run(agent, {"ligand_params_path": str(ALR), "max_anchor_atoms": 1})
    qc = impress_gates.evaluate(agent.spec, out)
    failed = [g for g in qc.gates if g.outcome is GateOutcome.FAIL]
    assert [g.gate for g in failed] == ["metric_in_range[n_engaged_atoms]"]
    assert failed[0].role == "acceptance"


def test_the_twin_goes_through_the_real_anchor_spec():
    """So a twin cannot emit a payload shape or a metric definition the real tool would not."""
    agent = mock_asd.MockLigAnchorProposeAgent(spec=_spec(MOCK, "mock_liganchor_propose"))
    out = _run(agent, {"max_anchor_atoms": 6})
    artifact = out["outputs"]["anchor_spec"]
    assert artifact["schema"] == liganchor.ANCHOR_SPEC_SCHEMA
    assert artifact["ligand_resname"] == "A:R"
    assert set(artifact["cfg_features"]) == {"active_donor", "active_acceptor",
                                             "ref_atomwise_rasa"}
    qc = impress_gates.evaluate(agent.spec, out)
    assert [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL] == []


def test_the_twin_and_the_real_spec_agree_on_parameters_ports_and_pattern():
    """A twin with different parameter names lets a campaign YAML pass the twin and fail the
    tool; a twin with a different pattern exercises a different dispatch path."""
    real, twin = _spec(DESIGN, "liganchor_propose"), _spec(MOCK, "mock_liganchor_propose")
    assert set(real.parameters) <= set(twin.parameters), (
        f"the twin is missing {sorted(set(real.parameters) - set(twin.parameters))}"
    )
    assert set(real.outputs) == set(twin.outputs)
    assert real.pattern == twin.pattern
    assert real.resources.gpus == twin.resources.gpus == 0, (
        "this tool parses a text file; a declared GPU would double-count the device in CON-3"
    )
    assert twin.toolkit == "mock" and twin.id != real.id


def test_the_known_bad_fixture_really_fails_the_gate_it_names():
    spec = _spec(DESIGN, "liganchor_propose")
    fixtures = sorted((DESIGN / "tools" / "liganchor_propose" / "tests").glob("*.bad.json"))
    assert fixtures
    for path in fixtures:
        payload = json.loads(path.read_text())
        assert payload["why"].strip()
        qc = impress_gates.evaluate(spec, payload["output"])
        failed = {g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL}
        assert failed, f"{path.name} is filed as known-bad and passes every gate"
        # An EXACT set of the LABELS `evaluate` emits, not a prefix match against gate ids.
        # Changed 2026-11-21 when these fixtures arrived in this checkout: a `metric_in_range`
        # result is labelled with its metric, and a prefix match cannot tell two such gates on
        # one tool apart -- `rfd3_steered_design` has exactly two, an integrity one on
        # `conditioning_applied` and an acceptance one on `n_resamples`, with one fixture each.
        # `tests/test_gate_fixtures.py` is the harness that caught it and this agrees with it.
        assert failed == set(payload["failing_gates"]), (
            f"{path.name}: failing gates were {sorted(failed)}"
        )
