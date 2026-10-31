"""The reasoner registry, and the claims it makes about itself.

The point of these tests is that `MODELS`'s `status` column is load-bearing documentation.
`docs/` described four working control models while two of them had no LLM behind them, and
nothing contradicted it. A status field is only worth having if something checks it, so the
first test here fails a model that claims `implemented` while still inheriting
`BasePolicy`'s `NotImplementedError`.
"""
from __future__ import annotations

import pytest
from impress_a.cli import POLICIES, SUBCOMMANDS, build_policy, main
from impress_a.core.pareto import Objective
from impress_a.policy import registry as reasoners
from impress_a.policy.base import BasePolicy
from impress_a.policy.explicit import ReplayPolicy, ThresholdPolicy
from impress_a.runtime.executor import CampaignSpec

STATUSES = ("implemented", "partial", "stub")


def _spec(**kw) -> CampaignSpec:
    return CampaignSpec(campaign_id="t-registry", goal="g",
                        objectives=[Objective(name="x", direction="maximize")], **kw)


def test_every_model_declares_a_known_status_and_mode():
    for letter, m in reasoners.MODELS.items():
        assert m.letter == letter, f"{letter}: letter disagrees with its key"
        assert m.status in STATUSES, f"{letter}: unknown status {m.status!r}"
        assert m.mode in ("autonomous", "headless"), f"{letter}: bad mode {m.mode!r}"
        assert m.llm_shape in ("none", "per-node", "single-call", "external")
        assert m.llm_calls >= 0


def test_a_model_claiming_implemented_actually_implements_decide():
    """The assertion the status column exists for.

    `BasePolicy.decide` raises `NotImplementedError`. A model that never overrode it is a
    stub whatever its row says, and this is what stops the row drifting away from the code.
    """
    for letter, m in reasoners.MODELS.items():
        if m.status != "implemented":
            continue
        assert m.cls.decide is not BasePolicy.decide, (
            f"{letter} claims status=implemented but does not override decide()")


def test_models_that_are_not_implemented_say_why():
    """A `partial` with no note is a gap nobody can act on."""
    for letter, m in reasoners.MODELS.items():
        if m.status != "implemented":
            assert m.note, (
                f"{letter}: status={m.status} with no note saying what is missing")


def test_no_model_claims_an_llm_call_it_cannot_make():
    """`llm_calls` is what runs TODAY, not what the specification asks for.

    No live client is constructed anywhere in the package, so every count must be 0. When
    one is wired, this test is the thing that has to be changed deliberately - which is the
    point: the count should not be able to rise by accident.
    """
    for letter, m in reasoners.MODELS.items():
        assert m.llm_calls == 0, (
            f"{letter} claims {m.llm_calls} llm calls/cycle; if a live client was wired, "
            "update this test and docs/reference/control-models.md together")


def test_cli_policies_is_derived_from_the_registry():
    assert POLICIES is reasoners.CLASSES
    assert set(POLICIES) == set(reasoners.MODELS)


def test_build_rejects_an_unknown_model_and_names_the_known_ones():
    with pytest.raises(KeyError) as e:
        reasoners.build("Z")
    assert "Z" in str(e.value)
    for letter in reasoners.MODELS:
        assert letter in str(e.value)


@pytest.mark.parametrize("letter", ["A", "B", "C", "D", "null"])
def test_every_model_but_replay_builds_from_a_spec_alone(letter):
    pol = build_policy(letter, _spec(stages=["mock_generate", "mock_score"]))
    assert hasattr(pol, "decide")


def test_the_campaigns_chain_reaches_the_policy():
    """Without this, a real campaign validates real toolkits and then executes mocks."""
    stages = ["rfd3_design", "ligandmpnn_design"]
    for letter in ("A", "D"):
        pol = build_policy(letter, _spec(stages=stages), guard=False)
        assert pol.stages == stages, f"{letter} did not receive the campaign's stages"


def test_b_and_c_get_a_model_d_fallback_carrying_the_same_chain():
    """Degraded mode must not quietly narrow the campaign to the mock chain."""
    stages = ["rfd3_design", "ligandmpnn_design"]
    for letter in ("B", "C"):
        pol = build_policy(letter, _spec(stages=stages), guard=False)
        assert isinstance(pol.fallback, ThresholdPolicy)
        assert pol.fallback.stages == stages


def test_replay_refuses_without_records_instead_of_raising_typeerror():
    """`build_policy` used to call `cls()`, so `--model replay` died on a positional arg.

    The failure a user saw named `records`, a parameter no flag set.
    """
    with pytest.raises(ValueError, match="replay-from"):
        build_policy("replay", _spec())


def test_replay_builds_when_records_are_supplied():
    records = [{"decision": {"kind": "stop", "reason": "done"}}]
    pol = build_policy("replay", _spec(), guard=False, records=records)
    assert isinstance(pol, ReplayPolicy)
    assert pol.records == records


def test_run_reports_a_clear_failure_for_replay_without_a_source(tmp_path, caplog):
    """End to end through `main`, because the TypeError happened before the campaign."""
    spec = tmp_path / "c.yaml"
    spec.write_text(
        "campaign_id: t\ngoal: g\nbackend: concurrent\n"
        "objectives:\n  - {name: x, direction: maximize}\n")
    assert main(["run", str(spec), "--model", "replay"]) == 1
    assert "cannot build control model replay" in caplog.text


def test_models_subcommand_prints_every_model(capsys):
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    for letter in reasoners.MODELS:
        assert letter in out
    # The status column is the reason this command exists.
    assert "partial" in out


def test_the_parser_accepts_every_declared_subcommand():
    """`SUBCOMMANDS` is read by `slides/api/run_model.py`; a name that is not real would
    put a subcommand in the deck that does not exist."""
    for name in SUBCOMMANDS:
        with pytest.raises(SystemExit) as e:
            main([name, "--help"])
        assert e.value.code == 0, f"{name} is declared but the parser rejects it"
