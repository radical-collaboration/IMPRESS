"""The reasoner registry, and the claims it makes about itself.

The point of these tests is that `MODELS`'s `status` column is load-bearing documentation.
`docs/` described four working control models while two of them had no LLM behind them, and
nothing contradicted it. A status field is only worth having if something checks it, so the
first test here fails a model whose status does not match what its halves actually do.
"""
from __future__ import annotations

import pytest

from impress_a.cli import POLICIES, SUBCOMMANDS, build_roles, main
from impress_a.core.pareto import Objective
from impress_a.policy import registry as reasoners
from impress_a.policy.planner import Planner
from impress_a.policy.planners import ThresholdPlanner
from impress_a.policy.specifier import Specifier
from impress_a.policy.specifiers import ThresholdSpecifier
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


def test_a_model_claiming_implemented_has_halves_that_do_something():
    """The assertion the status column exists for.

    It used to check that a model overrode `BasePolicy.decide`, which raised
    `NotImplementedError`. `decide` is gone (phase 11), so the check is against the halves: a
    model claiming `implemented` must build both, and neither may be `BaseSpecifier` or
    `BasePlanner`, whose `initial_spec` and `plan` raise `NotImplementedError` for exactly the
    reason the old base class did.
    """
    from impress_a.policy.planner import BasePlanner
    from impress_a.policy.specifier import BaseSpecifier

    for letter, m in reasoners.MODELS.items():
        if m.status != "implemented":
            continue
        options = reasoners.ReasonerOptions(stages=["mock_fold"],
                                            records=[] if letter == "replay" else None)
        spec_half, plan_half = m.specifier(options), m.planner(options)
        assert type(spec_half) is not BaseSpecifier, f"{letter}: specifier is the base class"
        assert type(plan_half) is not BasePlanner, f"{letter}: planner is the base class"
        assert type(spec_half).initial_spec is not BaseSpecifier.initial_spec, (
            f"{letter} claims status=implemented and its specifier does not override "
            f"initial_spec")


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
    assert POLICIES is reasoners.LETTERS
    assert set(POLICIES) == set(reasoners.MODELS)


def test_building_an_unknown_model_names_the_known_ones():
    with pytest.raises(KeyError) as e:
        reasoners.build_roles("Z")
    assert "Z" in str(e.value)
    for letter in reasoners.MODELS:
        assert letter in str(e.value)


@pytest.mark.parametrize("letter", ["A", "B", "C", "D", "null"])
def test_every_model_but_replay_builds_from_a_spec_alone(letter):
    pair = build_roles(letter, _spec(stages=["mock_generate", "mock_score"]))
    assert isinstance(pair.specifier, Specifier)
    assert isinstance(pair.planner, Planner)


def test_the_campaigns_chain_reaches_the_halves():
    """Without this, a real campaign validates real toolkits and then executes mocks."""
    stages = ["rfd3_design", "ligandmpnn_design"]
    for letter in ("A", "B", "C", "D"):
        pair = build_roles(letter, _spec(stages=stages), guard=False)
        assert pair.planner.stages == stages, (
            f"{letter}'s planner did not receive the campaign's stages")


def test_b_and_c_get_a_model_d_fallback_carrying_the_same_chain():
    """Degraded mode must not quietly narrow the campaign to the mock chain.

    Model B's halves fall back to model D's when the endpoint will not answer; model C's
    planner takes one only when `on_timeout="fallback"` is asked for, and the default is
    `stop` precisely so a silent fall-back cannot happen - so C is checked by the absence.
    """
    stages = ["rfd3_design", "ligandmpnn_design"]
    b = build_roles("B", _spec(stages=stages), guard=False)
    assert isinstance(b.specifier.fallback, ThresholdSpecifier)
    assert isinstance(b.planner.fallback, ThresholdPlanner)
    assert b.planner.fallback.stages == stages

    c = build_roles("C", _spec(stages=stages), guard=False)
    assert c.planner.on_timeout == "stop"
    assert c.planner.fallback is None, (
        "a model-D planner must not be in arm C's object graph unless asked for: a "
        "fallen-back C arm is byte-for-byte a D campaign")


def test_replay_refuses_without_records_instead_of_raising_typeerror():
    """`--model replay` with no `--replay-from` is an operator error, reported as one.

    `build_policy` used to call `cls()`, so it died on a positional argument named `records`
    that no flag set. Both halves refuse by name now.
    """
    with pytest.raises(ValueError, match="replay-from"):
        build_roles("replay", _spec())


def test_replay_builds_when_records_are_supplied():
    """Two record sets, because the halves read two executor-written files.

    `specs.jsonl` and `stages.jsonl`, not the `decisions.jsonl` each model wrote for itself -
    which is why a campaign run by a model that kept no notes can still be replayed.
    """
    specs = [{"event": "initial", "generation": 1, "aims": [], "objectives": []}]
    stages = [{"event": "deployed", "stage": "s1", "mappings": []}]
    pair = build_roles("replay", _spec(), guard=False,
                       spec_records=specs, stage_records=stages)
    assert pair.specifier.records == specs
    assert pair.planner.records == stages


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


# ---------------------------------------------------------------------------
# The two halves (phase 1 of plans/control-plane-refactor.md).
# ---------------------------------------------------------------------------

def test_every_model_supplies_both_halves():
    """One `--model` must yield a usable Specifier and a usable Planner.

    While the strangler is in place both are derived from the model's `ControlPolicy`, which is
    what makes `--control roles` a change of vocabulary rather than of behaviour. `replay` is
    excluded because it refuses to construct without records - deliberately, since a replay
    with none is a different campaign rather than a degraded one.
    """
    for letter in sorted(reasoners.MODELS):
        if letter == "replay":
            continue
        pair = reasoners.build_roles(letter)
        assert isinstance(pair.specifier, Specifier), f"{letter}: specifier half"
        assert isinstance(pair.planner, Planner), f"{letter}: planner half"
        assert pair.name == letter


def test_halves_mix_independently():
    """`--specifier X --planner Y` is reachable from the first day, not retrofitted.

    A pair that can only ever come from one row is not two interfaces; it is one with a seam
    drawn on it. Keeping the mixed form constructible is what will later make it measurable
    whether specification or planning is where a model earns its cost.
    """
    pair = reasoners.build_roles("A", "D")
    assert pair.name == "A/D"
    assert isinstance(pair.specifier, Specifier)
    assert isinstance(pair.planner, Planner)


def test_an_unknown_letter_names_the_known_ones():
    with pytest.raises(KeyError, match="unknown control model"):
        reasoners.build_roles("Z")


def test_policy_max_cycles_equals_the_spec():
    """A reasoner must not carry a stopping bound tighter than the campaign's (X1).

    `build_policy` withheld `max_cycles` on the reasoning that `CampaignManager._reasoner`
    already bounds the driver with it and bounding one thing from two places hides an
    off-by-one. The consequence was worse than the thing avoided: every model kept
    `ReasonerOptions.max_cycles`'s default of **6**, so a four-hour arm declaring
    `max_cycles: 200` would have decided six times in about twenty minutes, stopped itself,
    and reported a clean campaign having spent roughly 8% of its allocation.

    Checked on both arms that stop themselves this way - A reads `max_cycles` in
    `agentic.py` and D in `explicit.py` - and in both directions, because a spec asking for
    fewer cycles than the default must also be honoured.
    """
    # Read off `ReasonerOptions`, which is what the halves are built from - `build_roles`
    # is the adapter that fills it from the spec, and the bound reaching the options is the
    # whole of what X1 was about. A half that stops itself reads it from there.
    from impress_a.cli import _options_for

    for cycles in (3, 200):
        assert _options_for(_spec(max_cycles=cycles)).max_cycles == cycles


def test_the_front_target_comes_from_the_spec_when_it_declares_one():
    """`target_front` is a property of the Goal, not of the demo it was defaulted for.

    A policy stops at `len(pareto_front) >= target_front`, so the shipped 3 is a second
    silent cap on a campaign asked for ten designs - and unlike `max_cycles` nothing else
    bounds it. 0 (the default) keeps the model's own number, so no existing campaign moves.
    """
    from impress_a.cli import _options_for

    assert _options_for(_spec()).target_front == 3
    assert _options_for(_spec(target_front=10)).target_front == 10


def test_a_model_profile_reaches_model_as_four_nodes_and_not_only_model_bs_oracle(monkeypatch):
    """`--model-profile` must fill both seams, or it is inert for half the letters (H1).

    `_options_for` populated `oracle` alone, so a live client reached model B's single-call
    seam and model A's `reasoner` stayed `None`. `AgenticSpecifier`/`AgenticPlanner` read that
    slot, find nothing, and run the rule cascade - so `--model A --model-profile beam` was a
    rule-cascade arm wearing a live arm's name, with no error anywhere to say so. That is the
    exact failure the flag exists to prevent, arriving by the other door.

    One client in both slots rather than two, because no letter uses both shapes and a second
    would only be a second connection to the same endpoint. `OpenAICompatOracle` implements
    `policy/reasoning.NodeReasoner`, which is what makes one object serve both.
    """
    from impress_a import cli

    sentinel = object()
    monkeypatch.setattr(cli, "_client_for", lambda profile, spec: sentinel if profile else None)

    named = cli._options_for(_spec(), profile="beam")
    assert named.oracle is sentinel, "model B's oracle must come from the profile"
    assert named.reasoner is sentinel, \
        "model A's per-node seam must come from the same profile, not stay None"
    assert named.reasoner is named.oracle, "one client, both slots - not two connections"

    bare = cli._options_for(_spec())
    assert bare.oracle is None and bare.reasoner is None, \
        "no profile must leave both seams to the registry's deterministic stand-ins"


#: Every shipped model now supplies its own two halves. Kept as a list rather than an
#: "all of them" assertion so that adding a model is a decision about which it is: a new row
#: without halves would run the legacy `decide` cascade under `--control roles`, which is what
#: `DecideAsRoles` exists for and what phase 11 deletes.
DECLARES_HALVES = {"A", "B", "C", "D", "null", "replay"}


def test_every_model_supplies_its_own_halves_rather_than_deriving_them():
    """`--control roles` must not quietly run a model's `decide` cascade.

    `cli.build_roles` derives a pair from `decide` only for a model that declares none, so
    which models declare them decides what `--model X --control roles` actually executes. A
    model that gained halves and was not added here would run them while its note still said
    otherwise; one that lost them would silently fall back to the legacy cascade under a flag
    that says it is not using it.
    """
    declared = {k for k, m in reasoners.MODELS.items()
                if m.specifier is not None and m.planner is not None}
    assert declared == DECLARES_HALVES, (
        f"models declaring halves changed to {sorted(declared)}; update DECLARES_HALVES and "
        f"the model's own `note`, which `impress-a models` prints")
    partial = {k for k, m in reasoners.MODELS.items()
               if (m.specifier is None) != (m.planner is None)}
    assert partial == set(), (
        f"{sorted(partial)} declare one half and not the other, which would pair a real half "
        f"with a legacy adapter - a combination nothing tests and nobody asked for")


def test_no_model_claims_a_live_client_it_has_not_been_given():
    """The status column is load-bearing documentation, so B must say what it is running.

    `docs/` described four working control models while two had no LLM behind them, and
    nothing contradicted it. Model B now has a live client, but nothing *attaches* one unless
    a profile names it, so `llm_calls` stays 0 and the note has to say which stand-in runs by
    default - otherwise a reader assumes the phase-9 split made B a live arm.
    """
    for letter, model in reasoners.MODELS.items():
        assert model.llm_calls == 0, (
            f"{letter} claims {model.llm_calls} LLM calls per cycle. Nothing in this "
            f"repository constructs a client without a `--model-profile`, so raise this only "
            f"when a default profile makes one")
    b = reasoners.MODELS["B"]
    assert "RehearsalOracle" in b.note, b.note
    assert "models.yaml" in b.note, "the note must say where a live profile comes from"


def test_model_c_is_built_to_stop_rather_than_to_fall_back():
    """The safe default has to be the one the CLI builds, not the one a class declares.

    `ExternalPlanner.__init__` defaulted to `stop` and `ReasonerOptions.on_timeout` defaulted
    to `fallback`, so every path that went through the registry - which is every path the CLI
    takes - built the dangerous one. Found by running it: `impress-a serve --model C` logged
    `external planner: no directive in 5.0s; on_timeout=fallback` and finished the campaign on
    model D's planner. An arm whose entire claim is that a third party steered it, silently
    steering itself, is byte-for-byte a model-D campaign and invisible in the result; the
    four-arm design names it as one of its two dangerous failure modes.
    """
    assert reasoners.ReasonerOptions().on_timeout == "stop"

    pair = reasoners.build_roles("C", options=reasoners.ReasonerOptions(stages=["mock_fold"]))
    assert pair.planner.on_timeout == "stop"
    assert pair.planner.fallback is None, \
        "a model-D planner must not even be in arm C's object graph unless asked for"

    asked = reasoners.build_roles("C", options=reasoners.ReasonerOptions(
        stages=["mock_fold"], on_timeout="fallback"))
    assert asked.planner.fallback is not None, "an operator who asks for one gets one"
    assert asked.planner.on_timeout == "fallback"

    # There is no legacy policy left to check (phase 11): `ExternalPolicy` went with the
    # `decide` contract, so the planner half above is the only place this default lives.


def test_no_shipped_half_argues_its_own_stop_condition():
    """Satisfaction is COMPUTED off the data registry, by every model that ships.

    `BaseSpecifier.satisfied` reads the rules against realized data and the Specifier gets no
    say, and the protocol does permit an override - `specifier.py` says so, and says such a
    Specifier "owes an explanation in provenance, because the campaign's stop condition is
    being argued rather than computed". No shipped half takes that offer, and
    `docs/reference/resolution.md` step 8 and `docs/reference/control-models.md` both rest on
    it: the asymmetry behind G14 and H11 is that satisfaction counts READINGS while the front
    counts ELIGIBLE nodes, and a half that redefined `satisfied` would add a third population
    neither document describes.

    So this is a statement about the shipped set, not about the protocol. A deliberate
    override should change this test and both pages together - which is the point of asserting
    it rather than writing it down.
    """
    # `spec_records` because `replay` refuses to be built without them, deliberately: a
    # replay with no records is a different campaign rather than a degraded one.
    options = reasoners.ReasonerOptions(stages=["mock_fold"], spec_records=[])
    for letter, model in reasoners.MODELS.items():
        half = model.specifier(options)
        owner = next((klass for klass in type(half).__mro__ if "satisfied" in vars(klass)),
                     None)
        assert owner is not None, f"{letter}: {type(half).__name__} has no `satisfied` at all"
        assert owner.__module__ in ("impress_a.policy.specifier",
                                    "impress_a.policy.wrappers"), (
            f"{letter}: {type(half).__name__} defines its own `satisfied` in "
            f"{owner.__module__} - it is arguing the campaign's stop condition rather than "
            f"computing it. Update docs/reference/resolution.md step 8 and "
            f"docs/reference/control-models.md with it, or drop the override")
