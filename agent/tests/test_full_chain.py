"""The whole design chain on twins, nine stages, anchor set to corrected ΔG (item 7, EI.25).

**Item 7 has said since it was written that it closes "at M1, when the whole chain runs on
twins", and M1 went green with the chain at two stages of nine.** The two scoring twins EI.10
shipped had never been in a campaign at all — so the one defect class a multi-stage campaign
exists to catch had never been looked for on the half of the chain that reads a *structure*.
EI.9 found exactly that defect on the other half, in **both** of its agents, and a unit test
that passed the artifact directly had agreed with both of them.

**What this file asserts that a unit test cannot.** Every test here needs a campaign: the
composer wiring `structure` from one stage's outputs to the next stage's inputs, the planner
deciding which stages to plan at all, and the acceptance gates of five tools that are not
ours. None of that has a unit-test shape.

**Three findings came out of writing it, and two were mistakes in this file's own first
draft** — both recorded in `campaigns/asd-smb-mock.yaml` beside the values they produced:

1. **The chain is nine stages, not seven.** The first draft bridged `Backbone` to `Complex`
   with `mpnn_design → packmin → boltz_predict` and skipped `fastrelax` and `filter_shape`.
   `filter_shape` is what reports `shape_complementarity`, which the boltz twin *inherits* —
   absent, it falls to a default and `complex_plddt` landed 0.749 against its own 0.75 bar. A
   chain shortened for convenience changed a quality metric, not the runtime.
2. **`batch_size` and `diffusion_samples` are ensemble widths, not speed dials.** Set to 2
   "because this is an interface gate, not a search", they cost about 0.09 of pLDDT between
   them. The twins' defaults are calibrated *together*; `mock_smb_agents.py`'s own docstring
   says so.
3. **Our steered designer reported no `ss_fraction`**, which is the metric `mock_mpnn_design`
   inherits at the head of the chain — so it took its 0.5 default where a real `rfd3_design`
   would hand it ~0.60, and every downstream margin was smaller than impress-a's own mock
   chain's. That was backlog item 43, **fixed in EI.31**: the head now reports `0.59` and
   `complex_plddt` lands `0.858` against its `0.75` bar, where it landed `0.813` here. The
   assertions that were loose enough to pass either way are now written against the margin.

**It must not run on Delta.** Same reason as M1's own table: the whole value is that it passes
with no GPU, no Dragon and no LLM, and the campaign *declares* two P1 GPU stages while using
no device.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import yaml

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")
pytest.importorskip("radical.asyncflow", reason="radical.asyncflow is not installed")

from impress_a.cli import build_roles, load_spec  # noqa: E402
from impress_a.manager import CampaignManager  # noqa: E402
from impress_a.tools.registry import Registry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CAMPAIGN = REPO / "campaigns" / "asd-smb-mock.yaml"
TOOLKITS = REPO / "toolkits"

#: The chain, in order, and which repo each stage's twin comes from. Written out rather than
#: read from the YAML: a test that derived the expected chain from the file under test would
#: pass against any chain at all, including the two-stage one this episode exists to replace.
CHAIN = (
    ("mock_liganchor_propose", "ours"),
    ("mock_rfd3_steered_design", "ours"),
    ("mock_mpnn_design", "impress-a"),
    ("mock_packmin", "impress-a"),
    ("mock_fastrelax", "impress-a"),
    ("mock_filter_shape", "impress-a"),
    ("mock_boltz_predict", "impress-a"),
    ("mock_preorg_score", "ours"),
    ("mock_affdelta_score", "ours"),
)

#: Metrics only the scoring half can produce. Their presence is the difference between this
#: chain and the two-stage one, and `dg_lcb` is the deepest metric in the chain — naming it in
#: `objectives:` is what pulls every stage into the plan (item 42).
SCORED = ("preorg_rmsd", "rotamer_entropy", "ligand_rmsf", "induced_fit_risk", "sigma_preorg",
          "dg_corrected", "sigma_dg", "dg_lcb")


def _declared_metrics(tool_id: str) -> list[str]:
    """What a twin's own spec says it reports, read through the registry.

    Through the registry rather than by globbing for a `spec.yaml`, because five of the nine
    twins live in impress-a's checkout and finding them by path would hard-code where that
    checkout is. `Registry.search_paths()` already answers that question — it appends
    `parents[3]/toolkits` relative to its own module — and using it means this test resolves
    the chain exactly as the campaign does.
    """
    return list(Registry().load().get(tool_id).metrics)


async def _run(path: Path, *, model: str = "D"):
    """One campaign, on the registry `$IMPRESS_A_TOOLKITS` builds, from the repo root.

    **The env var is restored, and leaving it set is a real defect rather than untidiness.**
    `search_paths()` returns `explicit` *and* everything in `$IMPRESS_A_TOOLKITS`, so a later
    test calling `Registry().load()` with the variable still pointing at the same
    directory gets that root **twice**, and the second pass over it reports `duplicate tool
    id` with one line in `reg.errors` and no refusal. **Corrected 2026-11-21 (H1):** this
    said the duplicate *disabled the whole toolkit*, and it does not — `_load_toolkit` calls
    `self.specs.update(staged)` on the first pass, so those ids are already registered and
    survive; measured, the doubled root leaves 30 specs and three errors. The leak is still a
    defect, for a smaller reason: `test_gate6_pair.py`'s fixture asserts `reg.errors == []`,
    which is item 32's whole subject, so a leaked variable fails it.
    `tests/test_vocabulary_refusal.py::test_a_root_searched_twice_costs_load_errors_and_not_its_tools`
    is the measurement. `tests/test_three_campaigns.py` leaks the same variable and the suite only
    passed because `test_gate6_pair.py` sorts before `test_three_campaigns.py` and after
    `test_full_chain.py`; adding this file is what surfaced it, and both now restore.
    """
    cwd = Path.cwd()
    os.chdir(REPO)
    try:
        spec = load_spec(str(path))
        mgr = CampaignManager(spec, build_roles(model, spec, True), Registry().load())
        return await mgr.run()
    finally:
        os.chdir(cwd)


def _properties(result) -> dict[str, str]:
    """metric name -> the tool that reported it, over every node in the tree.

    Keyed by name because the question each test asks is *which stage produced this number*,
    and `PropertySource.name` is the only place the answer is recorded.
    """
    out: dict[str, str] = {}
    for node in result.tree.nodes.values():
        for name, prop in (getattr(node, "properties", {}) or {}).items():
            source = getattr(prop, "source", None)
            out[name] = getattr(source, "name", "") or ""
    return out


@pytest.fixture(scope="module")
def run():
    """The chain, once. Module-scoped: nine stages of seeded draws twice over asserts nothing
    the first run did not."""
    return asyncio.run(_run(CAMPAIGN))


@pytest.fixture(scope="module")
def props(run):
    return _properties(run)


# ---------------------------------------------------------------------------
# the chain itself
# ---------------------------------------------------------------------------


def test_every_one_of_the_nine_stages_ran(run):
    """Item 7's condition, counted on the one signal that is one-per-stage.

    **The obvious assertion does not work, and finding out why was worth the detour.** Asking
    which tool is the `source` of each node property misses `mock_packmin` entirely: its only
    declared metric is `total_score`, `mock_fastrelax` declares the same name downstream, and
    the tree holds **one** `Property` per name — so packmin's value is overwritten by the
    stage after it and the node carries no trace of packmin at all. See
    `test_three_metric_names_are_produced_twice_and_the_later_stage_wins`.

    `output_present` is the signal that survives that: every one of the nine specs declares it,
    it is evaluated in each stage's own `post_process`, and the `QCReport` keeps every result
    rather than collapsing by name. Nine of them means nine stages ran their gates.
    """
    gates = [g.gate for g in run.front[0].qc.gates] if run.front else []
    assert gates, "no QC report to read"
    assert gates.count("output_present") == len(CHAIN), (
        f"{gates.count('output_present')} stages reported an output, expected {len(CHAIN)}"
    )

    declared = sum(len(Registry().load().get(tool).qc_gates) for tool, _ in CHAIN)
    assert len(gates) == declared, (
        f"the node carries {len(gates)} gate results against {declared} declared across the "
        "nine specs -- a stage's gates went missing, or one ran twice"
    )


def test_five_of_the_nine_twins_are_impress_as_and_this_episode_wrote_none(run):
    """**The finding: the chain needed no new twin.**

    The steered designer emits `backbone: Backbone` and both scorers take
    `structure: Complex`, so the bridge looked like work. impress-a already ships every stage
    of it. Asserted by WHICH MODULE implements each twin, because the claim is about authorship
    rather than about resolution: a twin of ours quietly added to the chain would satisfy it and
    silently falsify this episode's reason for being cheap.

    This read the staging DIRECTORY until H9 (2026-11-21), when `toolkits/mock_asd/` merged into
    `toolkits/mock/` and the filesystem stopped carrying the distinction. The `entry:` module is
    the better signal anyway: it names what implements a twin rather than where its spec was
    filed, and it is what a reader checks when they want to know whose code runs.
    """
    ours = {
        path.parent.name
        for path in (TOOLKITS / "mock" / "tools").glob("*/spec.yaml")
        if "mock_asd_agents" in yaml.safe_load(path.read_text())["entry"]
    }
    for tool, origin in CHAIN:
        if origin == "ours":
            assert tool in ours, f"{tool} is not in this repo's toolkit"
        else:
            assert tool not in ours, (
                f"{tool} is now in this repo's toolkit -- the chain was supposed to reuse "
                "impress-a's, and a local copy would drift from it silently"
            )
    assert sum(1 for _, origin in CHAIN if origin == "impress-a") == 5


def test_the_campaign_reaches_its_own_stop_condition(run):
    """Not merely "did not crash". Nine stages of twins, each with its own acceptance gates,
    and the design chain still reaches a stop reason of its own."""
    assert run.stop_reason == "every spec objective satisfied", run.stop_reason
    assert run.cycles >= 1


def test_the_front_is_not_empty_because_the_twins_own_bars_are_cleared(run):
    """**The assertion this file's first draft failed**, and the reason it is here rather than
    in a comment.

    Nine stages all ran, every one reported, no task failed — and the front was EMPTY, because
    `complex_plddt` came out 0.749 against `mock_boltz_predict`'s own 0.75 acceptance bar.
    "Every stage ran" and "any design was accepted" are different claims, and a chain can
    satisfy the first while answering the second with nothing. The fixes were both in the
    campaign file (the missing `filter_shape` stage and two ensemble widths cut to 2), never in
    the bar: a surrogate with an easier bar than the real campaign teaches the wrong thing
    about when a design passes.
    """
    assert run.front, (
        "the chain ran end to end and accepted nothing. Check `complex_plddt` against "
        "mock_boltz_predict's 0.75 acceptance gate and `shape_complementarity` against "
        "mock_filter_shape's 0.55 before changing either -- the twins' defaults are "
        "calibrated together and are expected to pass."
    )


def test_the_scored_metrics_are_present_which_the_two_stage_chain_could_not_show(props):
    """The half of the chain that reads a structure, exercised for the first time.

    Every name here comes from `mock_preorg_score` or `mock_affdelta_score`. Before EI.25 none
    of them could appear in any campaign, because neither twin was in one — which is also why
    `inputs[port]` being the upstream task's whole payload rather than the artifact was never
    checked on this side of the chain.
    """
    for metric in SCORED:
        assert metric in props, f"{metric} is missing; the scoring stages did not report"
    assert props["induced_fit_risk"] == "mock_preorg_score"
    assert props["dg_lcb"] == "mock_affdelta_score"


#: metric -> the stages that declare it, where more than one does. Measured over the nine
#: specs, not guessed: `total_score` is packmin's *pre-relax* energy and fastrelax's
#: *post-relax* one, and the two `ensemble_*` pairs describe two different ensembles.
SHADOWED = {
    "ensemble_size": ("mock_mpnn_design", "mock_boltz_predict"),
    "ensemble_paired": ("mock_mpnn_design", "mock_boltz_predict"),
    "total_score": ("mock_packmin", "mock_fastrelax"),
}


def test_each_stage_reports_every_metric_its_own_spec_declares(props):
    """Declared is not reported, and the gap is this project's recurring failure class.

    `metrics_reported` is a per-tool QC gate, so a tool omitting one of its own metrics fails
    its gate — but only for the metrics *that gate* names, and no gate checks the full declared
    list. This does, over all nine specs at once, with the three shadowed names excused
    explicitly rather than by a loose comparison.
    """
    gaps: list[str] = []
    for tool, _ in CHAIN:
        for metric in _declared_metrics(tool):
            if metric in SHADOWED:
                continue
            if props.get(metric) != tool:
                gaps.append(f"{tool}.{metric} -> {props.get(metric, 'absent')!r}")
    assert not gaps, f"declared but not reported by their own tool: {gaps}"


def test_three_metric_names_are_produced_twice_and_the_later_stage_wins(props):
    """**A nine-stage chain has metric-name collisions, and the tree keeps one value per
    name** — which nothing in a two-stage chain could have shown.

    This is upstream's intended behaviour on both sides: `_inherit` "takes the LAST upstream
    that reported it so a chain reports its most recent estimate, which is what superseding
    means here", and `CampaignTree` likewise holds one `Property` per name. So the surviving
    value is the downstream stage's and the upstream one is **gone from the record** — not
    merely shadowed in a view.

    It is asserted rather than noted because of what it costs a reader: `total_score` on a node
    is fastrelax's post-relax energy, and packmin's pre-relax energy, which is the input
    fastrelax's own `_quality()` inverts, is not recoverable from the tree. Anyone reading
    `total_score` as "the chain's energy" is reading one of two numbers with that name. If this
    test ever fails, either a spec stopped declaring a name or the tree started keeping both,
    and both change what a campaign's record means.
    """
    for metric, producers in SHADOWED.items():
        assert props.get(metric) == producers[-1], (
            f"{metric} is attributed to {props.get(metric)!r}, not to the last stage that "
            f"declares it ({producers[-1]}); declared by {producers}"
        )
        for earlier in producers[:-1]:
            assert props.get(metric) != earlier, f"{metric} kept {earlier}'s value"


def test_the_chain_carries_quality_hand_to_hand_across_both_repos(props):
    """The property that makes nine stages worth running rather than nine tools worth mocking.

    impress-a's twins pass a quality signal down the chain from immediate upstream only
    (`mock_smb_agents.py`: "ss_fraction becomes a confidence, the confidence becomes an energy,
    the energy becomes a shape score, and the shape score becomes a pLDDT"). So these six
    numbers are not independent draws, and a chain whose middle was reordered or shortened
    would move the last of them -- which is how this file's first draft was caught.

    **`ss_fraction` is the first link and it was missing until EI.31**: the quotation above
    starts at a metric the chain's own head did not report, so `mock_mpnn_design` inherited
    nothing and took its default. The chain was a product of slopes with its first slope
    absent, which is a thing this test asserted the shape of without noticing.
    """
    for metric, tool in (("ss_fraction", "mock_rfd3_steered_design"),
                         ("overall_confidence", "mock_mpnn_design"),
                         ("total_score", "mock_fastrelax"),
                         ("interaction_energy", "mock_fastrelax"),
                         ("shape_complementarity", "mock_filter_shape"),
                         ("complex_plddt", "mock_boltz_predict")):
        assert props.get(metric) == tool, f"{metric} came from {props.get(metric)!r}"


# ---------------------------------------------------------------------------
# what the chain refuses, and what it does not
# ---------------------------------------------------------------------------


def _stage_events(result) -> list[dict]:
    """`stages.jsonl` for one campaign run, as dicts.

    Read from disk rather than from the result, because the shortfall EI.26 records is a
    provenance event and nothing in `CampaignResult` carries it -- which is the point: it has
    to survive the process, not merely be visible inside it.
    """
    import json

    path = (REPO / "campaigns" / "_runs" / result.campaign_id / "provenance" / "stages.jsonl")
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _variant(tmp_path: Path, **edits: object) -> Path:
    """The campaign with `stages:` and/or `objectives:` replaced, in a temp directory.

    `input_spec_path` becomes absolute, because impress-a resolves a relative one against the
    **campaign file's own directory** -- the one-character mistake that cost EI.9 four runs
    and opened item 41. Measured here rather than assumed: an absolute path works.
    """
    doc = yaml.safe_load(CAMPAIGN.read_text())
    doc["params"]["mock_rfd3_steered_design"]["input_spec_path"] = str(
        REPO / "campaigns" / "data" / "alr" / "ALR_binder_design.json")
    doc.update(edits)
    path = tmp_path / "variant.yaml"
    path.write_text(yaml.safe_dump(doc))
    return path


def test_a_stage_no_objective_reaches_is_no_longer_planned_silently(tmp_path):
    """**Backlog item 42, pinned here and fixed upstream in EI.26 (`2d79f75`).**

    Under `--model D` the explicit specifier transcribes `objectives:` and the planner plans
    toward them, so dropping the two objectives that name the scoring metrics drops the stages
    that produce them -- while `stages:` still names all nine. The campaign reports `every spec
    objective satisfied` and every task it *did* run succeeds.

    **Two of the three assertions below are unchanged and the third is the fix.** The planner
    still chooses the sub-chain, because that is upstream's own documented behaviour -- *"
    selection by output type, not by position in a declared list"* -- and EI.26's first draft
    refused it and had to be withdrawn. What changed is that it is no longer silent: the
    campaign writes `stages_not_planned` to `stages.jsonl` naming every dropped stage, and
    warns. So the assertion that used to read "nothing anywhere says five stages were skipped"
    now reads the record that says so.

    Written against provenance rather than a log record on purpose: provenance is what is left
    after an allocation ends, and item 41's four runs were spent reading logs.
    """
    doc = yaml.safe_load(CAMPAIGN.read_text())
    kept = [o for o in doc["objectives"] if o["name"] not in ("induced_fit_risk", "dg_lcb")]
    assert len(kept) == len(doc["objectives"]) - 2, "the two scoring objectives are gone"

    result = asyncio.run(_run(_variant(tmp_path, objectives=kept)))
    props = _properties(result)

    assert result.stop_reason == "every spec objective satisfied", (
        f"the sub-chain was refused rather than reported: {result.stop_reason}. EI.26 "
        "deliberately did not refuse it -- see `_declared_stages_not_planned` upstream"
    )
    dropped_from_the_tree = [m for m in SCORED if m in props]
    assert not dropped_from_the_tree, (
        f"the scoring stages ran without an objective naming them: {dropped_from_the_tree}"
    )
    assert "complex_plddt" not in props, (
        "the bridge ran too, so the planner is not stopping at the deepest named metric and "
        "item 42's shape has changed"
    )

    # The fix: it is in the record now, by name.
    events = [e for e in _stage_events(result) if e.get("event") == "stages_not_planned"]
    assert events, (
        "nothing anywhere says the stages were skipped -- which is item 42 exactly, and was "
        "this test's assertion until upstream `2d79f75`"
    )
    detail = events[0]["detail"]
    assert set(detail["not_planned"]) == {
        "mock_mpnn_design", "mock_packmin", "mock_fastrelax", "mock_filter_shape",
        "mock_boltz_predict", "mock_preorg_score", "mock_affdelta_score"}, detail
    assert detail["declared"] == [tool for tool, _ in CHAIN]
    assert sorted(detail["planned"]) == ["mock_liganchor_propose",
                                         "mock_rfd3_steered_design"], detail


def test_the_chain_without_its_bridge_refuses_instead_of_scoring_an_empty_input(tmp_path):
    """The typed edge, and the refusal that is the *right* answer to an incomplete chain.

    `mock_rfd3_steered_design` emits `backbone: Backbone`; both scorers take
    `structure: Complex`. With the five bridging stages gone the composer finds no output whose
    type unifies with `structure`, wires the port to nothing, and the scorer raises rather than
    scoring an absent design -- the same refusal the real client makes. A twin that returned a
    plausible score here would feed the FK potential a number that looks like evidence.
    """
    bridge = {"mock_mpnn_design", "mock_packmin", "mock_fastrelax",
              "mock_filter_shape", "mock_boltz_predict"}
    stages = [s for s, _ in CHAIN if s not in bridge]
    assert len(stages) == 4, stages

    with pytest.raises(Exception) as caught:  # noqa: PT011 -- the type is upstream's to choose
        asyncio.run(_run(_variant(tmp_path, stages=stages)))

    # **This assertion flipped with EI.27, and that is what it is here for.** Until
    # `d8d1e80` upstream, an operator saw `CampaignAborted: 3 consecutive all-failed runs` and
    # nothing else -- not the stage, not the reason -- which is backlog item 41, hit here a
    # second time from a different cause. The abort now carries the first failing task, its
    # tool and its message, so the chain's own refusal is readable from the abort rather than
    # only from a per-cycle INFO line. Three claims, because "it says more" is not a check:
    abort = str(caught.value)
    assert "consecutive failed runs" in abort, abort
    assert "mock_preorg_score" in abort, (
        f"the abort does not name the tool that failed: {abort}"
    )
    assert "is wired but empty" in abort, (
        f"the abort does not carry the scorer's own refusal: {abort}"
    )
    # And not the consequence: `mock_affdelta_score` fails too, as a dependency failure, and
    # naming it would send a reader to the stage after the one that broke.
    assert "DependencyFailureError" not in abort, abort


def test_the_campaigns_model_version_is_what_the_attribution_reports(tmp_path):
    """CON-5 traced from the YAML to the payload EI.7's gate reads.

    Both scoring twins carry a mock-only `model_version` so a campaign can move the version and
    watch attribution follow. The campaign sets 7, not the default 0, deliberately: a test
    asserting attribution against a default cannot tell a carried version from a missing one.
    `model_versions` does not reach the design tree -- it is in the raw payload, which is where
    `surrogate_version_present` looks -- so this reads the payload directly.
    """
    from impress_a.tools.mock_asd_agents import MockAffDeltaScoreAgent, MockPreorgScoreAgent

    doc = yaml.safe_load(CAMPAIGN.read_text())
    for tool, agent_cls, model in (("mock_preorg_score", MockPreorgScoreAgent, "pocket_preorg"),
                                   ("mock_affdelta_score", MockAffDeltaScoreAgent,
                                    "aff_delta")):
        params = dict(doc["params"][tool])
        assert params["model_version"] == 7, f"{tool} no longer sets a non-default version"
        payload = _invoke(agent_cls, tool, params)
        versions = set(payload["model_versions"].values())
        assert versions == {f"{model}@v7"}, f"{tool} reported {versions}"
        assert payload["model_versions"].keys() == payload["metrics"].keys(), (
            "a scored metric with no version is what surrogate_version_present refuses"
        )


def _invoke(agent_cls, tool_id: str, params: dict) -> dict:
    """One twin, outside a campaign, with a `structure` port wired as the composer wires it.

    `input_ports` is set rather than left to be inferred: `input_ref` falls back to "the only
    output" when no upstream port was recorded, and relying on that fallback would test the
    fallback instead of the wiring EI.9's defect was about.
    """
    from impress_a.tools.agent import TaskRequest

    agent = agent_cls(Registry().load().get(tool_id))
    req = TaskRequest(tool=tool_id, node_id="n0001",
                      inputs={"structure": {"outputs": {"structure": "complex"}}},
                      input_ports={"structure": "structure"})
    return asyncio.run(agent.run(req, params))


def test_the_whole_thing_needs_no_gpu_no_dragon_and_no_llm(run):
    """Why this belongs in M1 rather than M2, asserted rather than claimed -- and it holds
    even though the campaign DECLARES two P1 stages asking for `gpus: 1`. Gate 4 checks that
    ask against the file's declared `site:`, not against the machine; the twins never open a
    device."""
    import sys

    heavy = {"torch", "dragon", "vllm", "transformers"}
    assert {m.split(".")[0] for m in sys.modules} & heavy == set()


def test_the_head_of_the_chain_hands_down_a_real_margin_not_a_default(run, props):
    """Item 43's measured cost, asserted as a margin rather than as a pass (EI.31).

    `test_the_front_is_not_empty...` passed at `complex_plddt` 0.813 and would pass at 0.751,
    so "the chain clears its bars" could not tell a calibrated chain from one whose first slope
    was missing. The numbers are EI.25's and EI.31's own measurements on this campaign:

    | | EI.25 | EI.31 |
    |---|---|---|
    | `ss_fraction` at the head | *not reported* -> 0.5 default | 0.59 |
    | `complex_plddt` on the front | 0.813 | 0.858 |

    Bounded above as well as below on purpose. A margin that grew past about 0.95 would mean
    the head got easier rather than honest, and `_soft_cap` exists upstream because a front
    whose members all sit at their ceiling cannot be ordered by the objectives the campaign
    cares most about.
    """
    assert props["ss_fraction"] == "mock_rfd3_steered_design"
    front = run.front[0]
    plddt = front.properties["complex_plddt"].value
    ss = front.properties["ss_fraction"].value

    assert 0.55 <= ss <= 0.65, (
        f"the head reported ss_fraction {ss}; mock_rfd3_design's calibrated value is ~0.60 and "
        "the twins' defaults are chosen together"
    )
    assert 0.82 <= plddt <= 0.95, (
        f"complex_plddt is {plddt}. EI.25 measured 0.813 with the head silent and EI.31 "
        "measured 0.858 with it reporting; outside this band the chain was recalibrated and "
        "the comparison in this docstring no longer holds"
    )


def test_the_planner_cannot_turn_the_chains_difficulty_down(run):
    """**Measured in EI.31, and it is the same failure class one more time.**

    `difficulty` was added to `mock_rfd3_steered_design` without `operator_only`. The
    refinement path escalated it to about 0.45 at cycle 1, the node came back with
    `ss_fraction` 0.481 against the new 0.5 acceptance bar, and it was dropped from the front:
    a *refined* design worse than its parent, by a knob the planner turned. Upstream marks its
    own copy `operator_only` and says why -- "a model asked to satisfy the objectives, and told
    there is a 0.0-to-1.0 knob called 'how hard this campaign is', turns it down".

    Asserted on the spec rather than on the run, because a run only shows it when the planner
    happens to reach for that knob, and the campaign that first showed it was not written to.
    """
    spec = Registry().load().get("mock_rfd3_steered_design")
    assert spec.parameters["difficulty"].operator_only, (
        "difficulty is tunable again; the planner will choose the experiment's own condition"
    )
    assert not spec.parameters["reward_spread"].operator_only, (
        "reward_spread is a property of the fake scorer, not of the target, and no objective "
        "moves with it -- marking it would be cargo-culting this fix"
    )
    # And the chain's own head is at the default, which is what the margins above assume.
    assert run.front[0].properties["ss_fraction"].value > 0.5
