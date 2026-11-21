"""FK Tier 1 and the input spec it renders (item 12b, EI.9).

**Three things here are worth a reviewer's time and none of them is the arithmetic.**
`asteer.fk` already owns the arithmetic and `tests/test_fk.py` pins it against hand-computed
references; what this file checks is that the loop *uses* it correctly and that the rendering
does not lose the instruction on the way out.

1. **`length` is dropped whenever `partial_t` is set.** RFD3's validator rejects the
   combination, the project's own committed input carries both, and three of three pipelines in
   a sibling example crashed on it (job `21928556`). The drop is reported as a metric rather
   than done silently.
2. **The history reaches the potential.** Three of the four potentials are folds over the
   trajectory, so a loop that passed `None` would make `MAX`, `SUM` and `DIFFERENCE` silently
   behave as `IMMEDIATE` — steering on the wrong quantity while reporting plausible weights.
   `test_the_history_reaches_the_potential` is what rules that out, and it is the subtlest
   failure available in this file.
3. **Conditioning is counted into the rendered JSON, and zero is refused before the task
   bills.** This is the half of item 26 that is checkable without a GPU.

**What this file cannot check, and says so where it matters:** whether RFD3 honours
`select_buried`/`select_exposed` at all. M0 measured that `select_hotspots` resolves and is then
dropped by `build()`; it did not test these two. They are the documented, enumerated keys that
this project's own target identity already uses, which is better evidence and not proof. That
question is M2's.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from asteer.contracts import FKConfig, PotentialKind  # noqa: E402
from asteer.impress import mock_asd  # noqa: E402

from impress_a.core.qc import GateOutcome  # noqa: E402
from impress_a.tools import asteer_design_agents as rs  # noqa: E402
from impress_a.tools import gates as impress_gates  # noqa: E402
from impress_a.tools.agent import TaskRequest  # noqa: E402
from impress_a.tools.asteer_design_agents import (  # noqa: E402
    ANCHOR_SPEC_SCHEMA,
    anchor_spec_from_params,
)
from impress_a.tools.spec import ToolSpec  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "toolkits" / "asteer_design"
MOCK = REPO / "toolkits" / "mock_asd"

#: The project's own committed RFD3 input, from the sibling IMPRESS checkout. Used rather than
#: a fixture because its two awkward properties are the ones under test: it carries
#: `partial.input` **and** `length`, which RFD3 rejects together, and its ligand is the literal
#: `A:R`. A fixture would have been written without either.
ALR_JSON = (REPO.parent / "IMPRESS" / "agent" / "campaigns" / "data" / "alr"
            / "ALR_binder_design.json")
ALR_PARAMS = (REPO.parent / "IMPRESS" / "agent" / "campaigns" / "data" / "alr" / "ALR.params")
needs_alr = pytest.mark.skipif(not (ALR_JSON.exists() and ALR_PARAMS.exists()),
                               reason="the IMPRESS checkout is not beside us")


def _spec(toolkit: Path, tool: str) -> ToolSpec:
    return ToolSpec(**yaml.safe_load((toolkit / "tools" / tool / "spec.yaml").read_text()))


def _anchor(**kw) -> dict:
    return anchor_spec_from_params(ALR_PARAMS, **kw).as_artifact()


def _template() -> dict:
    return json.loads(ALR_JSON.read_text())


def _upstream(anchor: dict) -> dict:
    """`TaskRequest.inputs` as a wired upstream task actually fills it.

    Two levels, and both matter. `inputs` is keyed by **this tool's own input port**, and the
    value is the UPSTREAM TASK'S WHOLE PAYLOAD -- so the artifact sits at
    `inputs[port]["outputs"][upstream_port]`. Passing the bare artifact as `inputs[port]` is
    what a single-stage test gets away with and a real graph does not, which is how both
    agents' accessor was wrong until the mock campaign grew a second stage. These tests build
    the real shape so they cannot get away with it either.
    """
    return {"anchor_spec": {"outputs": {"anchor_spec": {"value": anchor}}}}


def _fake_denoise(tags: list[str] | None = None):
    """A denoiser that records how it was called, since the call pattern is the loop's shape."""
    calls: list[dict] = []

    def denoise(*, n, partial_t, seeds):
        calls.append({"n": n, "partial_t": partial_t,
                      "seeds": None if seeds is None else list(seeds)})
        gen = len(calls) - 1
        return [f"g{gen}-p{i}" for i in range(n)]

    denoise.calls = calls  # type: ignore[attr-defined]
    return denoise


# ---------------------------------------------------------------------------
# the pinned trap
# ---------------------------------------------------------------------------


@needs_alr
def test_length_is_dropped_whenever_partial_t_is_set_and_the_drop_is_reported():
    """The trap `tests/test_real_toolkits.py` pins upstream, honoured and made visible.

    RFD3's validator: *"Length argument must not be provided during partial diffusion"* --
    length is inferred from the input structure in that mode. Job `21928556`: three of three
    pipelines that reached guided feedback crashed on their first attempt. Backlog C8.
    """
    template = _template()
    assert "length" in template["partial"], (
        "the premise changed: the committed input no longer carries `length`, so this test is "
        "asserting something about a file that no longer poses the problem"
    )
    spec, counts = rs.render_input_spec(template, _anchor(), partial_t=0.4)
    assert "length" not in spec["partial"]
    assert counts["length_dropped"] == 1, "the drop must be reported, not silent"
    # And the template itself is untouched: a renderer that mutated target identity in place
    # would corrupt the next particle's input.
    assert "length" in template["partial"]


@needs_alr
def test_length_survives_when_partial_t_is_not_set():
    """From-scratch diffusion needs its contig; the drop is conditional, not a cleanup."""
    spec, counts = rs.render_input_spec(_template(), _anchor(), partial_t=None)
    assert spec["partial"]["length"] == "70-170"
    assert counts["length_dropped"] == 0


# ---------------------------------------------------------------------------
# the rendering, and what it conditions on
# ---------------------------------------------------------------------------


@needs_alr
def test_the_burial_channel_renders_to_the_documented_keys():
    """`select_buried`/`select_exposed`, not the CFG trio. Both are in the enumerated key list
    and in this project's own committed input; the CFG keys are in neither."""
    spec, counts = rs.render_input_spec(_template(), _anchor(max_anchor_atoms=99),
                                        partial_t=0.4, buried_threshold=0.3)
    block = spec["partial"]
    assert "A:R" in block["select_buried"]
    assert "A:R" in block["select_exposed"]
    named = (block["select_buried"]["A:R"].split(",")
             + block["select_exposed"]["A:R"].split(","))
    assert counts["conditioning_applied"] == len(named) == counts["conditioning_requested"]
    assert "use_classifier_free_guidance" not in block, "the CFG channel is opt-in"
    assert "cfg_features" not in block


@needs_alr
def test_the_cfg_channel_is_opt_in_because_its_keys_are_unverified():
    """Off by default: the source spec spells `active donor` two ways and settling it needs the
    container. A wrong key is item 26 -- a run conditioned on nothing that reports success."""
    spec, _ = rs.render_input_spec(_template(), _anchor(), partial_t=0.4,
                                   emit_cfg_features=True)
    block = spec["partial"]
    assert block["use_classifier_free_guidance"] is True
    assert set(block["cfg_features"]) == {"active_donor", "active_acceptor",
                                          "ref_atomwise_rasa"}
    # The verified keys are still written: the CFG channel is additional, never a replacement.
    assert "select_buried" in block


@needs_alr
def test_every_requested_atom_reaches_one_of_the_two_lists():
    """The threshold partitions; it never discards. An atom in neither list is an atom Model A
    asked to condition on that silently did not."""
    anchor = _anchor(max_anchor_atoms=99)
    for threshold in (0.0, 0.2, 0.3, 0.5, 1.0):
        spec, counts = rs.render_input_spec(_template(), anchor, partial_t=0.4,
                                           buried_threshold=threshold)
        block = spec["partial"]
        placed = set()
        for key in ("select_buried", "select_exposed"):
            if key in block:
                placed |= set(block[key]["A:R"].split(","))
        assert placed == set(anchor["engaged_atoms"]), (
            f"threshold {threshold}: the rendered lists are {sorted(placed)}, which is not "
            "Model A's anchor set. The first cut failed this at 0.0 and 1.0, where one side "
            "is empty and the template's own hand-written list survived underneath."
        )
        assert counts["conditioning_applied"] == counts["conditioning_requested"]
        assert counts["template_lists_overridden"] == 2, (
            "the committed input carries both lists, and both must be replaced"
        )


@needs_alr
def test_a_ligand_mismatch_is_refused_rather_than_conditioning_the_wrong_residue():
    """`A:R` versus `ALR` is the documented way to get this wrong."""
    template = _template()
    template["partial"]["ligand"] = "ALR"
    with pytest.raises(rs.SteeringRefused, match="colon in A:R"):
        rs.render_input_spec(template, _anchor(), partial_t=0.4)


@needs_alr
def test_an_unknown_anchor_schema_is_refused():
    anchor = _anchor()
    anchor["schema"] = "something.else/9"
    with pytest.raises(rs.SteeringRefused, match="schema"):
        rs.render_input_spec(_template(), anchor, partial_t=0.4)
    assert ANCHOR_SPEC_SCHEMA == "asteer.anchor_spec/1"


@needs_alr
def test_a_template_without_a_partial_block_is_refused():
    with pytest.raises(rs.SteeringRefused, match="no 'partial' block"):
        rs.render_input_spec({"from_scratch": {"ligand": "A:R"}}, _anchor(), partial_t=0.4)


# ---------------------------------------------------------------------------
# the loop
# ---------------------------------------------------------------------------


def _config(**kw) -> FKConfig:
    return FKConfig(n_particles=kw.pop("n_particles", 8), seed=kw.pop("seed", 7),
                    ess_collapse_threshold=kw.pop("ess_collapse_threshold", 2.0), **kw)


def test_the_loop_denoises_once_from_scratch_then_once_per_restart():
    denoise = _fake_denoise()
    run = rs.tier1(_config(), denoise=denoise, score=lambda p: 0.5,
                   n_restarts=3, partial_t=0.4)
    assert len(denoise.calls) == 4, "one from-scratch pass plus one per restart"
    assert denoise.calls[0]["partial_t"] is None and denoise.calls[0]["seeds"] is None
    assert all(c["partial_t"] == 0.4 for c in denoise.calls[1:])
    assert all(len(c["seeds"]) == 8 for c in denoise.calls[1:])
    assert len(run.steps) == 3
    # One reward vector per event plus the terminal one, which is what reward_terminal reads.
    assert len(run.rewards) == 4


def test_survivors_are_the_resampled_indices_and_nothing_else():
    denoise = _fake_denoise()
    rewards = iter([0.1, 0.9, 0.1, 0.1])

    run = rs.tier1(_config(n_particles=4, seed=3), denoise=denoise,
                   score=lambda p: next(rewards, 0.5), n_restarts=1, partial_t=0.4)
    expected = [f"g0-p{i}" for i in run.steps[0].indices]
    assert denoise.calls[1]["seeds"] == expected, (
        "the second pass must be seeded by exactly the particles FK chose, in its order"
    )


def test_the_history_reaches_the_potential():
    """The subtlest failure available here, and it is silent.

    `DIFFERENCE`, `MAX` and `SUM` are folds over the trajectory. A loop that passed no history
    would make all three behave as `IMMEDIATE` while still producing plausible weights, so the
    run would steer on the wrong quantity and nothing would say so. This compares a potential
    that needs the history against one that does not, on the same reward sequence.
    """
    # Rewards fall after the first event, so MAX (best-so-far) and IMMEDIATE (current) must
    # disagree by the second event.
    sequence = [0.9, 0.1, 0.1, 0.1] + [0.2, 0.3, 0.4, 0.5] + [0.2, 0.3, 0.4, 0.5]

    def run_with(kind):
        rewards = iter(sequence)
        return rs.tier1(_config(n_particles=4, seed=11, potential=kind),
                        denoise=_fake_denoise(), score=lambda p: next(rewards, 0.0),
                        n_restarts=2, partial_t=0.4)

    immediate = run_with(PotentialKind.IMMEDIATE)
    maximum = run_with(PotentialKind.MAX)
    assert immediate.steps[1].weights != maximum.steps[1].weights, (
        "MAX and IMMEDIATE produced identical weights at the second event, which means the "
        "history is not reaching rewards_for and three of the four potentials are inert"
    )
    # And the opt-out still runs: a loop that raised with `carry_history=False` would make the
    # flag unusable, and MAX-without-history is a legitimate thing to ask for deliberately.
    without = rs.tier1(
        _config(n_particles=4, seed=11, potential=PotentialKind.MAX),
        denoise=_fake_denoise(),
        score=lambda p: 0.5, n_restarts=1, partial_t=0.4,
        carry_history=False,
    )
    assert without.steps[0].weights != ()


def test_resampling_is_reproducible_under_a_fixed_seed():
    def go():
        rewards = iter([0.1, 0.4, 0.9, 0.2] * 4)
        return rs.tier1(_config(n_particles=4, seed=99), denoise=_fake_denoise(),
                        score=lambda p: next(rewards, 0.5), n_restarts=3, partial_t=0.4)

    first, second = go(), go()
    assert [s.indices for s in first.steps] == [s.indices for s in second.steps]
    assert first.ess_mean == second.ess_mean


def test_unequal_rewards_lower_ess_and_equal_rewards_leave_it_at_n():
    flat = rs.tier1(_config(n_particles=8, seed=5), denoise=_fake_denoise(),
                    score=lambda p: 0.5, n_restarts=2, partial_t=0.4)
    assert flat.ess_mean == pytest.approx(8.0), (
        "equal rewards are uniform weights, so ESS is the whole population -- and that is the "
        "inert case M2 reads"
    )
    sharp_rewards = iter([5.0] + [0.0] * 7 + [5.0] + [0.0] * 7 + [5.0] + [0.0] * 7)
    sharp = rs.tier1(_config(n_particles=8, seed=5), denoise=_fake_denoise(),
                     score=lambda p: next(sharp_rewards, 0.0), n_restarts=2, partial_t=0.4)
    assert sharp.ess_mean < flat.ess_mean
    assert sharp.collapsed, "ESS of ~1 against a threshold of 2 must raise the collapse signal"


def test_n_resamples_counts_events_that_changed_the_population():
    """Counting every event would overstate how much steering happened, and that number is
    exactly what the inertness check reads."""
    flat = rs.tier1(_config(n_particles=8, seed=5), denoise=_fake_denoise(),
                    score=lambda p: 0.5, n_restarts=3, partial_t=0.4)
    assert len(flat.steps) == 3
    assert flat.n_resamples == 0, "uniform weights keep every parent exactly once"
    assert flat.particle_diversity == pytest.approx(1.0)


def test_a_pass_with_no_restart_is_refused_because_that_is_the_control_arm():
    with pytest.raises(rs.SteeringRefused, match="unsteered arm"):
        rs.tier1(_config(), denoise=_fake_denoise(), score=lambda p: 0.5,
                 n_restarts=0, partial_t=0.4)


def test_a_denoiser_returning_the_wrong_population_size_is_refused():
    """Resampling a population of a different size than the weights were computed for
    mis-pairs them silently."""
    def short(*, n, partial_t, seeds):
        return ["only-one"]

    with pytest.raises(rs.SteeringRefused, match="not the 8"):
        rs.tier1(_config(), denoise=short, score=lambda p: 0.5, n_restarts=1, partial_t=0.4)


# ---------------------------------------------------------------------------
# the agent, the twin and the gates
# ---------------------------------------------------------------------------


@needs_alr
def test_the_real_agent_renders_before_it_refuses_so_the_message_is_useful():
    """It cannot diffuse off-cluster, and it says what *did* work before saying so."""
    agent = rs.RFD3SteeredDesignAgent(spec=_spec(DESIGN, "rfd3_steered_design"))
    req = TaskRequest(tool="rfd3_steered_design",
                      params={"input_spec_path": str(ALR_JSON)},
                      inputs=_upstream(_anchor()),
                      input_ports={"anchor_spec": "anchor_spec"}, node_id="n1")
    with pytest.raises(rs.SteeringRefused) as exc:
        asyncio.run(agent.run(req, agent.parameterize(req)))
    message = str(exc.value)
    assert "FOUNDRY_SIF_PATH" in message
    assert "mock_rfd3_steered_design" in message
    assert "atoms conditioned" in message
    assert "length` dropped" in message


@needs_alr
def test_an_unwired_anchor_spec_is_refused_by_both_the_tool_and_the_twin():
    """Nothing upstream checks it: `compose/validate.py:79`-`:81` is a literal `pass`."""
    for cls, toolkit, tool in (
        (rs.RFD3SteeredDesignAgent, DESIGN, "rfd3_steered_design"),
        (mock_asd.MockRFD3SteeredDesignAgent, MOCK, "mock_rfd3_steered_design"),
    ):
        agent = cls(spec=_spec(toolkit, tool))
        req = TaskRequest(tool=tool, params={"input_spec_path": str(ALR_JSON)}, node_id="n1")
        with pytest.raises(rs.SteeringRefused, match="anchor_spec"):
            asyncio.run(agent.run(req, agent.parameterize(req)))


@needs_alr
def test_the_twin_runs_the_real_loop_and_the_real_rendering():
    """Only the denoiser and the scorer are faked, so the twin exercises every off-cluster line.

    A twin that reimplemented the loop would be testing a second implementation of CON-8's
    arithmetic, which is what `asteer.fk` exists to prevent.
    """
    agent = mock_asd.MockRFD3SteeredDesignAgent(spec=_spec(MOCK, "mock_rfd3_steered_design"))
    req = TaskRequest(tool="mock_rfd3_steered_design",
                      params={"input_spec_path": str(ALR_JSON), "reward_spread": 0.8},
                      inputs=_upstream(_anchor()),
                      input_ports={"anchor_spec": "anchor_spec"}, node_id="n1")
    out = asyncio.run(agent.run(req, agent.parameterize(req)))
    assert out["metrics"]["conditioning_applied"] == out["metrics"]["conditioning_requested"]
    assert out["metrics"]["length_dropped"] == 1.0
    assert "length" not in out["rendered_input_spec"]["partial"]
    assert "select_buried" in out["rendered_input_spec"]["partial"]
    qc = impress_gates.evaluate(agent.spec, out)
    assert [g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL] == []


@needs_alr
def test_the_twins_reward_spread_dial_reaches_ess_through_the_real_arithmetic():
    """There is no `force_collapse` flag: the collapse has to come out of the arithmetic, or
    it proves nothing about the arithmetic."""
    agent = mock_asd.MockRFD3SteeredDesignAgent(spec=_spec(MOCK, "mock_rfd3_steered_design"))

    def ess_for(spread: float) -> float:
        req = TaskRequest(tool="mock_rfd3_steered_design",
                          params={"input_spec_path": str(ALR_JSON),
                                  "reward_spread": spread, "seed": 4},
                          inputs=_upstream(_anchor()),
                          input_ports={"anchor_spec": "anchor_spec"}, node_id="n1")
        return asyncio.run(agent.run(req, agent.parameterize(req)))["metrics"]["ess_mean"]

    assert ess_for(3.0) < ess_for(0.01), (
        "unequal rewards must sharpen the weights and lower ESS; if they do not, the dial is "
        "not reaching asteer.fk"
    )


def test_the_twin_diverges_from_the_tool_only_on_the_pattern_and_the_device():
    """The one deliberate twin divergence in the project, pinned so it stays the only one.

    The real tool is P1 with a GPU because it drives RFD3's denoiser; the twin returns seeded
    draws. A twin declaring `gpus: 1` would make a laptop campaign request a device nothing
    uses, and on a GPU-less node the task is accepted and never placed.
    """
    real, twin = _spec(DESIGN, "rfd3_steered_design"), _spec(MOCK, "mock_rfd3_steered_design")
    assert (real.pattern.value, real.resources.gpus) == ("P1", 1)
    assert (twin.pattern.value, twin.resources.gpus) == ("P2", 0)
    assert set(real.parameters) <= set(twin.parameters), (
        f"the twin is missing {sorted(set(real.parameters) - set(twin.parameters))}"
    )
    assert set(real.inputs) == set(twin.inputs)
    assert set(real.outputs) == set(twin.outputs)
    assert set(real.metrics) <= set(twin.metrics)
    assert twin.toolkit == "mock" and twin.id != real.id


def test_conditioning_applied_is_an_integrity_gate_and_n_resamples_an_acceptance_one():
    """Decision 0013, and the two fixtures are the two halves made concrete.

    A lost instruction is a broken wiring, so the pattern's trust must take the hit. Steering
    that did nothing is a tuning mistake, so it must not -- demoting trust for a retune would
    then refuse the retune.
    """
    spec = _spec(DESIGN, "rfd3_steered_design")
    roles = {}
    for gate in spec.qc_gates:
        if gate.id == "metric_in_range":
            roles[gate.params["metric"]] = gate.role
    assert roles["conditioning_applied"] == "integrity"
    assert roles["n_resamples"] == "acceptance"


def test_each_known_bad_fixture_really_fails_the_gate_it_names():
    spec = _spec(DESIGN, "rfd3_steered_design")
    fixtures = sorted((DESIGN / "tools" / "rfd3_steered_design" / "tests").glob("*.bad.json"))
    assert len(fixtures) == 2, "one fixture per gate role, which is the distinction that matters"
    for path in fixtures:
        payload = json.loads(path.read_text())
        assert payload["why"].strip()
        qc = impress_gates.evaluate(spec, payload["output"])
        failed = {g.gate for g in qc.gates if g.outcome is GateOutcome.FAIL}
        assert failed, f"{path.name} is filed as known-bad and passes every gate"
        # An EXACT set of emitted labels, not a prefix match (2026-11-21). This tool is the
        # reason the distinction is not pedantry: it declares TWO `metric_in_range` gates, one
        # integrity on `conditioning_applied` and one acceptance on `n_resamples`, with one
        # fixture for each -- and a prefix match would have let either fixture satisfy either
        # gate, which is exactly the pair this file exists to keep apart.
        assert failed == set(payload["failing_gates"]), (
            f"{path.name}: failing gates were {sorted(failed)}"
        )


def test_the_two_fixtures_fail_in_different_roles():
    """The pair exists to make the integrity/acceptance split checkable, not to add coverage."""
    spec = _spec(DESIGN, "rfd3_steered_design")
    roles = {}
    for name in ("unconditioned_run", "inert_steering"):
        payload = json.loads(
            (DESIGN / "tools" / "rfd3_steered_design" / "tests" / f"{name}.bad.json").read_text())
        qc = impress_gates.evaluate(spec, payload["output"])
        roles[name] = {g.role for g in qc.gates if g.outcome is GateOutcome.FAIL}
    assert roles["unconditioned_run"] == {"integrity"}
    assert roles["inert_steering"] == {"acceptance"}


@needs_alr
def test_the_renderer_never_mutates_the_target_identity_it_was_given():
    template = _template()
    before = copy.deepcopy(template)
    rs.render_input_spec(template, _anchor(), partial_t=0.4, emit_cfg_features=True)
    assert template == before, (
        "a renderer that edited target identity in place would corrupt the next particle's "
        "input, and the loop renders once per pass"
    )


# ---------------------------------------------------------------------------
# the tier knob (EI.17)
# ---------------------------------------------------------------------------


@needs_alr
def test_tier_two_writes_the_sampler_key_into_the_input_spec():
    """Tier 2 is selected in the input spec, never on the CLI.

    `inference_sampler.kind` is what RFD3 reads to pick a sampler out of
    `ConditionalDiffusionSampler._registry` (item 3, job `24155612`), and the registry **falls
    back silently on an unknown key** -- so a campaign asking for tier 2 against an
    unregistered sampler would run the stock sampler and report success having steered nothing.
    Writing the key from one constant is half the guard.
    """
    from asteer.fk_sampler import SAMPLER_KIND

    spec, counts = rs.render_input_spec(_template(), _anchor(), partial_t=0.4, tier=2)
    assert spec["partial"]["inference_sampler"] == {"kind": SAMPLER_KIND}
    assert counts["tier"] == 2


@needs_alr
def test_tier_one_removes_a_sampler_key_a_template_left_behind():
    """A template reused from a tier-2 run must not silently steer a tier-1 one."""
    template = _template()
    template["partial"]["inference_sampler"] = {"kind": "left_over"}
    spec, counts = rs.render_input_spec(template, _anchor(), partial_t=0.4, tier=1)
    assert "inference_sampler" not in spec["partial"]
    assert counts["tier"] == 1


@needs_alr
def test_both_specs_declare_the_tier_knob_with_the_same_bounds():
    real, twin = _spec(DESIGN, "rfd3_steered_design"), _spec(MOCK, "mock_rfd3_steered_design")
    assert real.parameters["tier"].default == twin.parameters["tier"].default == 1
    assert (real.parameters["tier"].min, real.parameters["tier"].max) == (1, 2)


# ---------------------------------------------------------------------------
# RFD3's own backbone quality (item 43, EI.31)
# ---------------------------------------------------------------------------

#: The unsteered control arm's spec, in the sibling checkout. Read rather than transcribed:
#: the whole claim of item 43 is that the two arms are gated *the same*, and a transcribed
#: copy of upstream's numbers would keep agreeing after upstream changed them.
CONTROL_SPEC = (REPO.parent / "IMPRESS" / "agent" / "toolkits" / "rfd3" / "tools"
                / "rfd3_design" / "spec.yaml")
#: The project's own committed target scaffold — a real structure, which is what makes it
#: usable here. There is no synthetic PDB in this repo and a hand-written ideal helix would
#: test the fixture's geometry rather than the metric.
SCAFFOLD = (REPO.parent / "IMPRESS" / "agent" / "campaigns" / "data" / "alr" / "input_pdbs"
            / "scaffold-with-ALR.pdb")
needs_control = pytest.mark.skipif(not CONTROL_SPEC.exists(),
                                   reason="the IMPRESS checkout is not beside us")

#: The six `rfd3_design` declares about its own output, and the two of them that are gated.
#: Gated/ungated is the TIER split, not a confidence ranking — see the spec's own comment:
#: `ss_fraction` is computed from a written structure so both tiers can report it, while the
#: other four are read from a sidecar the in-process tier may never see.
BACKBONE_METRICS = ("ss_fraction", "num_models", "ca_deviation", "ligand_clashes",
                    "helix_fraction", "sheet_fraction")


def _twin_run(difficulty: float | None = None, **params) -> dict:
    """One twin run, **seeded**, and the seed is load-bearing rather than tidiness.

    `FKConfig.seed` defaults to `None` here and `fk.step` then builds a *fresh unseeded*
    generator (`fk/__init__.py:91`) — correct for production, and it leaves `n_resamples` a
    coin flip when the weights are near-uniform, which they are at the default
    `reward_spread: 0.3`. Measured across five processes: 2, 3, 1, 0, 2. With `seed: 4` it is 3
    every time. `n_resamples >= 1` is an *acceptance* gate, so without this the gate outcome
    these tests read is a draw. Backlog item 44, found here and not fixed here.
    """
    agent = mock_asd.MockRFD3SteeredDesignAgent(spec=_spec(MOCK, "mock_rfd3_steered_design"))
    merged = {"input_spec_path": str(ALR_JSON), "seed": 4, **params}
    if difficulty is not None:
        merged["difficulty"] = difficulty
    req = TaskRequest(tool="mock_rfd3_steered_design", params=merged,
                      inputs=_upstream(_anchor()),
                      input_ports={"anchor_spec": "anchor_spec"}, node_id="n1")
    return asyncio.run(agent.run(req, agent.parameterize(req)))


@needs_alr
@needs_control
def test_the_twin_reports_the_six_at_the_control_twins_own_calibration():
    """The twin's `ss_fraction` is `mock_rfd3_design`'s, which is what the chain is built on.

    **Asserted against upstream's own twin rather than against a number**, because the number
    is not ours: `mock_mpnn_design` inherits `ss_fraction` from its immediate upstream, the mock
    chain is a product of slopes, and EI.25 measured what a silent head costs — `complex_plddt`
    0.813 against a 0.75 bar where the calibrated chain reaches about 0.86. If upstream retunes
    its head, this fails and ours is retuned with it rather than drifting quietly.

    The comparison is at each twin's **own defaults**: upstream's expression carries a
    `diffusion_steps` term this tool has no parameter for, so parity means "the value the chain
    is calibrated around", not "the same formula".
    """
    from impress_a.tools.mock_smb_agents import MockRFD3DesignAgent

    out = _twin_run()
    for metric in BACKBONE_METRICS:
        assert metric in out["metrics"], f"the twin does not report {metric}"
    assert out["metrics"]["num_models"] == out["count"], (
        "num_models must be the population this pass produced, as it is for the real tool"
    )

    control_spec = ToolSpec(**yaml.safe_load(
        (REPO.parent / "IMPRESS" / "agent" / "toolkits" / "mock" / "tools"
         / "mock_rfd3_design" / "spec.yaml").read_text()))
    control = MockRFD3DesignAgent(spec=control_spec)
    creq = TaskRequest(tool="mock_rfd3_design", params={}, node_id="n1")
    cout = asyncio.run(control.run(creq, control.parameterize(creq)))

    ours, theirs = out["metrics"]["ss_fraction"], cout["metrics"]["ss_fraction"]
    assert abs(ours - theirs) <= 0.07, (
        f"the steered twin reports ss_fraction {ours} where mock_rfd3_design reports {theirs}; "
        "the two heads must hand mock_mpnn_design the same quality or the steered chain's "
        "margins are not impress-a's"
    )


@needs_alr
def test_the_difficulty_dial_reaches_both_gate_roles_on_one_metric():
    """Decision 0013 on our own tool for the first time: two gates, one metric, two roles.

    `has_secondary_structure` is "a 'the tool produced nothing usable' check, not a quality
    threshold" and is **integrity**; the 0.5 bar is **acceptance**. A dial that could only reach
    one of them would leave the other gate unexercised, which is how a gate that never fires
    gets mistaken for a gate that passes.
    """
    agent_spec = _spec(MOCK, "mock_rfd3_steered_design")

    def failures(difficulty: float) -> dict[str, set[str]]:
        out = _twin_run(difficulty)
        qc = impress_gates.evaluate(agent_spec, out)
        failed = [g for g in qc.gates if g.outcome is GateOutcome.FAIL]
        return {"roles": {g.role for g in failed}, "gates": {g.gate for g in failed}}

    assert failures(0.25)["gates"] == set(), (
        "the default must pass every gate. If `metric_in_range[n_resamples]` is the one "
        "failing, the run was unseeded -- see `_twin_run` and backlog item 44"
    )

    mid = failures(0.6)
    assert mid["roles"] == {"acceptance"}, (
        f"difficulty 0.6 should be an acceptance shortfall only, got {mid}"
    )

    hard = failures(0.9)
    assert "integrity" in hard["roles"], f"difficulty 0.9 should fail integrity, got {hard}"
    assert any(g.startswith("has_secondary_structure") for g in hard["gates"]), hard


@needs_alr
@needs_control
def test_the_steered_arm_declares_and_gates_what_the_control_arm_does():
    """Item 43 in one assertion: the two arms are read against each other at M2.

    An arm that cannot fail a check its control can fail is not a comparison — a steered run
    with no secondary-structure floor emits a noodle, reports every FK metric it declares,
    passes every gate it has and enters the campaign, while the unsteered arm at the same N is
    refused. Both specs are read, so the control arm changing a threshold is a failure here
    rather than a divergence nobody notices until the allocation is spent.
    """
    steered = _spec(DESIGN, "rfd3_steered_design")
    control = ToolSpec(**yaml.safe_load(CONTROL_SPEC.read_text()))

    assert set(control.metrics) == set(BACKBONE_METRICS), (
        f"the control arm's metric set moved: {sorted(set(control.metrics))}"
    )
    assert set(control.metrics) <= set(steered.metrics), (
        "the steered arm does not report what the control arm reports: "
        f"{sorted(set(control.metrics) - set(steered.metrics))}"
    )

    def gate_shape(spec) -> set[tuple]:
        shape = set()
        for g in spec.qc_gates:
            if g.id == "has_secondary_structure":
                shape.add((g.id, g.role, g.params["min_ss_fraction"]))
            elif g.id == "metric_in_range" and g.params.get("metric") == "ss_fraction":
                shape.add((g.id, g.role, g.params["min"]))
            elif g.id == "metrics_reported" and "ss_fraction" in g.params.get("metrics", []):
                shape.add((g.id, g.role, tuple(g.params["metrics"])))
        return shape

    assert gate_shape(control) == gate_shape(steered), (
        f"the two arms are filtered differently: control {sorted(gate_shape(control))} vs "
        f"steered {sorted(gate_shape(steered))}"
    )
    assert len(gate_shape(steered)) == 3, "all three of the control arm's gates must be there"


def test_only_sidecar_carrying_models_are_candidates(tmp_path):
    """Job 22536706's measured failure, which is why the rule is copied rather than loosened.

    RFD3 writes trajectories as `.cif.gz` too and `denoised` sorts **before** a design's own
    name, so `sorted(glob("*.cif.gz"))[0]` handed a 1.7 MB trajectory downstream as a 5.7 MB
    backbone and computed `ss_fraction` on the stack. The sidecar JSON is the discriminator:
    rfd3 writes one per design and none per trajectory.
    """
    (tmp_path / "zz_design_model_0.cif.gz").write_bytes(b"")
    (tmp_path / "zz_design_model_0.json").write_text("{}")
    (tmp_path / "aaa_denoised_model_0.cif.gz").write_bytes(b"")

    found = rs.candidate_models(tmp_path)
    assert [p.name for p in found] == ["zz_design_model_0.cif.gz"], (
        "the trajectory was picked up, or the design was not"
    )


def test_a_directory_of_strays_is_refused_rather_than_guessed_at(tmp_path):
    """Picking one would be a guess at which of them is a design."""
    (tmp_path / "aaa_denoised_model_0.cif.gz").write_bytes(b"")
    (tmp_path / "bbb_noisy_model_0.cif.gz").write_bytes(b"")

    with pytest.raises(rs.NoCandidateModels) as caught:
        rs.candidate_models(tmp_path)
    assert "sidecar" in str(caught.value) and "2 .cif.gz" in str(caught.value)

    with pytest.raises(rs.NoCandidateModels):
        rs.candidate_models(tmp_path / "does-not-exist")


def test_the_dotted_sidecar_key_is_read_whole_rather_than_descended_into(tmp_path):
    """The reuse this episode rests on, pinned at the one place it could silently stop working.

    `SIDECAR_KEYS` is **observed**, settled by jobs 23670171 and 23670891: `ligand_clashes` is
    the literal key `"n_clashing.ligand_clashes"` with no `n_clashing` object to descend into,
    and `ca_deviation` is `max_ca_deviation` — a *maximum*, the worst atom in the design rather
    than the typical one. Both were wrong in the first guess. This asserts our tool reads them
    through that table rather than re-deriving the names, so if upstream renames or drops it
    the loss is a test failure rather than four metrics quietly going missing from the steered
    arm's record.
    """
    from impress_a.tools.rfd3_agents import SIDECAR_KEYS, _sidecar_metrics

    assert SIDECAR_KEYS["ligand_clashes"][0] == "n_clashing.ligand_clashes"
    assert SIDECAR_KEYS["ca_deviation"][0] == "max_ca_deviation"

    cif = tmp_path / "d_model_0.cif.gz"
    cif.write_bytes(b"")
    (tmp_path / "d_model_0.json").write_text(json.dumps({"metrics": {
        "n_clashing.ligand_clashes": 2, "max_ca_deviation": 1.25,
        "helix_fraction": 0.41, "sheet_fraction": 0.2,
    }}))

    read = _sidecar_metrics(cif)
    assert read == {"ligand_clashes": 2.0, "ca_deviation": 1.25,
                    "helix_fraction": 0.41, "sheet_fraction": 0.2}, read


@pytest.mark.skipif(not SCAFFOLD.exists(), reason="the IMPRESS checkout is not beside us")
def test_ss_fraction_comes_from_a_written_structure_and_needs_no_sidecar():
    """Why `ss_fraction` is the metric both tiers can be gated on.

    It is computed from the PDB by a Ramachandran approximation — Biopython, no DSSP binary, no
    GPU, nothing rfd3 reported — so the in-process tier-2 driver can produce it from whatever
    it writes out, while the four sidecar metrics depend on a file the CLI writes and tier 2
    may never see. Measured on this project's own committed target scaffold rather than on a
    hand-written ideal helix, which would test the fixture's geometry instead.
    """
    pytest.importorskip("Bio", reason="Biopython is not installed in this environment")
    from impress_a.tools._pdbtools import secondary_structure_fraction

    ss = secondary_structure_fraction(SCAFFOLD)
    assert 0.5 <= ss <= 1.0, f"the committed scaffold scored {ss}"


def test_the_backbone_read_keeps_every_heavy_import_inside_its_function():
    """CON-4, and the module this episode touched is the one that gained three such imports.

    `backbone_metrics` needs Biopython and `gemmi`; `Registry.load()` and
    `Validator.dry_run()` must work in a venv with neither, which is upstream's own stated rule
    for `_pdbtools`. Run in a cold interpreter because an earlier test in this file may already
    have imported Biopython for its own reasons.
    """
    code = ("import sys, impress_a.tools.asteer_design_agents, asteer.impress.mock_asd; "
            "print(sorted({m.split('.')[0] for m in sys.modules} "
            "& {'Bio', 'gemmi', 'torch', 'numpy'}))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env={**os.environ, "PYTHONPATH": "src"})
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", f"the module pulled in {out.stdout.strip()}"


@needs_alr
def test_what_this_renderer_emits_is_accepted_by_upstreams_own_refusal():
    """Our rendered input spec, checked against upstream's discarded-key refusal (EI.29).

    `impress_a/tools/asteer_design_agents.py` says it in its first section header:
    **`select_hotspots` is never emitted, and that is the whole reason this module reads the way
    it does.** Item 26 is why —
    rfd3 resolves a ligand `select_hotspots`, `build()` drops the annotation, and the design
    runs to completion conditioned on nothing. So this renderer uses `select_buried` and
    `select_exposed`, which are honoured.

    Since IMPRESS `b1b0424` the wrapper refuses the discarded key rather than leaving a
    SKILL.md Pitfall to do the work, which makes that choice checkable from here instead of
    merely stated. If a later episode reaches for the CFG trio or anything else and emits a
    ligand hotspot by accident, this fails on a laptop rather than at M2.
    """
    upstream = pytest.importorskip(
        "impress_a.tools.rfd3_agents",
        reason="this checkout predates IMPRESS b1b0424")
    if not hasattr(upstream, "refuse_discarded_spec_keys"):
        pytest.skip("this IMPRESS checkout predates EI.29 (b1b0424)")

    spec, _counts = rs.render_input_spec(_template(), _anchor(), partial_t=0.4, tier=1)
    # `render_input_spec` returns the WHOLE file, keyed by entry -- the shape the refusal
    # walks, and the shape the agent writes. Asserted rather than assumed, because the first
    # draft of this test wrapped it a second time and the refusal then walked a dict whose one
    # entry had no `ligand`, which passes for the wrong reason.
    assert "partial" in spec and "ligand" in spec["partial"], spec

    upstream.refuse_discarded_spec_keys(spec, "rendered-by-asteer")

    entry = spec["partial"]
    assert "select_hotspots" not in entry, (
        "the renderer emitted the key rfd3 accepts and discards; see item 26"
    )
    assert {"select_buried", "select_exposed"} & set(entry), (
        "the honoured atom-level channel is what makes the refusal above affordable; which of "
        f"the two appears depends on `buried_threshold`, so either will do. Got: {sorted(entry)}"
    )
