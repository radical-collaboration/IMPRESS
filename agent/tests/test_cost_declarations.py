"""Item 21: every declaration at ≥2.25× worst observed, and what that costs the chains (EI.14).

**Why 2.25× and not a round number.** Wall time varies **3.2×** between identical runs on this
hardware (backlog A11/E2, `docs/impress-a/limitations.md`), and the declared figure feeds gate 5
and the trust interlock's 10%-of-available cap — both of which **refuse graphs**. So a figure
below measurement does not merely mis-report: it silently truncates a chain, which is on record
upstream (`rfd3_design`'s own spec: a declared 0.25 against a measured 0.0405 summed past the
cap and "got boltz_predict truncated off the chain"). Over-declaring wastes headroom;
under-declaring removes a stage without saying so. The asymmetry is why the rule errs high.

**The worst-observed figures live in this file, with their sources, and that is deliberate.**
They are in prose in each spec's comments and in two SKILL.md tables, and a test that parsed
prose would fail on a reworded sentence rather than on a wrong number. Here they are data, each
with its citation, and the assertion is arithmetic. If a figure here is wrong, the fix is to
change it *and* say where the new number came from.

**The labels chain is refused by its own interlock, and this file asserts that as expected
behaviour** so nobody later reads it as a bug and "fixes" it by under-declaring — which is the
other documented failure and the worse one.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
TOOLKITS = REPO / "toolkits"

#: The interlock's defaults, which this project does not change (`compose/interlock.py:50`,
#: `:51`). Repeated here because the arithmetic below is meaningless without them and because
#: a change upstream should break this file rather than pass quietly.
PROVISIONAL_BUDGET_FRACTION = 0.10
PROMOTE_AFTER = 3

#: The per-round GPU-hour envelope the source spec budgets (§5.5).
ENVELOPE_LOW, ENVELOPE_HIGH = 96.0, 192.0

#: tool -> (worst observed, unit, declared, where the worst-observed figure comes from).
#:
#: A `None` worst-observed means **nothing has been measured**, which is a different statement
#: from "it is cheap" and is asserted differently below: an unmeasured tool may declare a small
#: figure, but it must be flagged in its own spec as unverified, because item 21's ratio cannot
#: be checked against a measurement that does not exist.
DECLARATIONS: dict[str, tuple[float | None, str, float, str]] = {
    "asteer_labels/md_label": (
        3.6, "gpu_hours", 8.1,
        "source spec §5.5: ~2-3.6 GPU-h per design at 30 ns total (item 20)"),
    "asteer_labels/abfe_label": (
        8.0, "gpu_hours", 18.0,
        "source spec §5.5: ~3-8 GPU-h per ligand (item 20)"),
    "asteer_design/rfd3_steered_design": (
        None, "gpu_hours", 1.5,
        ("never run; 8 particles x 4 passes against rfd3_design's measured 0.0405 h/pass is "
         "~1.3 GPU-h, but the batch is one invocation rather than 32 and that is the part "
         "the arithmetic cannot predict")),
    "asteer_design/liganchor_propose": (
        None, "cpu_hours", 0.01, "never run; parses a text file"),
    "asteer_design/preorg_score": (
        None, "cpu_hours", 0.01, "never run; one stream round trip"),
    "asteer_design/affdelta_score": (
        None, "cpu_hours", 0.01, "never run; one stream round trip"),
}

#: The design chain as a campaign would compose it, and the labels chain as decision L1 split
#: it. Named here so the arithmetic below is about chains rather than about tools.
DESIGN_CHAIN = ("asteer_design/liganchor_propose", "asteer_design/rfd3_steered_design",
                "asteer_design/preorg_score", "asteer_design/affdelta_score")
LABELS_CHAIN = ("asteer_labels/md_label", "asteer_labels/abfe_label")


def _spec(path: str) -> dict:
    toolkit, tool = path.split("/")
    return yaml.safe_load((TOOLKITS / toolkit / "tools" / tool / "spec.yaml").read_text())


def _declared(path: str, unit: str) -> float:
    return float(_spec(path)["cost_model"]["cost"].get(unit, 0.0))


def _chain_cost(chain: tuple[str, ...], unit: str) -> float:
    return round(sum(_declared(p, unit) for p in chain), 6)


# ---------------------------------------------------------------------------
# the declarations themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(DECLARATIONS))
def test_each_declaration_matches_what_this_file_records(path):
    """The spec and the record agree. A drift in either is a finding, not a rounding."""
    _worst, unit, declared, _source = DECLARATIONS[path]
    assert _declared(path, unit) == pytest.approx(declared), (
        f"{path}'s spec declares {_declared(path, unit)} {unit} where this file records "
        f"{declared}. One of the two is wrong and neither should be changed without saying "
        "where the number came from."
    )


@pytest.mark.parametrize("path", sorted(DECLARATIONS))
def test_a_measured_tool_declares_at_least_two_and_a_quarter_times_its_worst(path):
    """Item 21's rule, where there is a measurement to apply it to."""
    worst, unit, declared, source = DECLARATIONS[path]
    if worst is None:
        pytest.skip(f"{path} has never been measured: {source}")
    ratio = declared / worst
    assert ratio >= 2.25, (
        f"{path} declares {declared} {unit} against a worst observed {worst} ({source}), a "
        f"ratio of {ratio:.2f}. Below 2.25 the declaration can fall under measurement, and a "
        "declared figure below measurement silently truncates a chain rather than reporting "
        "anything -- which is on record upstream for rfd3_design."
    )


@pytest.mark.parametrize("path", sorted(DECLARATIONS))
def test_an_unmeasured_tool_says_so_in_its_own_spec(path):
    """A small figure with no measurement behind it must be labelled, not merely small.

    `cost_measured` is what retires the label (item 23), and until then a reader of the spec
    has to be able to tell a derived figure from a measured one. Item 21's ratio cannot be
    checked against a measurement that does not exist, so the label is the only guard there is.
    """
    worst, _unit, _declared, _source = DECLARATIONS[path]
    if worst is not None:
        pytest.skip(f"{path} has a measured figure behind it")
    toolkit, tool = path.split("/")
    text = (TOOLKITS / toolkit / "tools" / tool / "spec.yaml").read_text().lower()
    assert "unverified" in text or "never run" in text or "re-derive" in text, (
        f"{path} declares a cost with no measurement behind it and its spec does not say so"
    )


def test_no_tool_declares_a_cost_of_zero():
    """Zero is free, and nothing here is. A zero cost makes gate 5 and the ledger blind to a
    stage, which is the same end state as under-declaring with none of the warning signs."""
    for path in sorted(DECLARATIONS):
        cost = _spec(path)["cost_model"]["cost"]
        assert cost, f"{path} declares an empty cost"
        assert all(float(v) > 0 for v in cost.values()), f"{path} declares a zero cost: {cost}"


def test_no_tool_bills_a_resource_it_does_not_ask_for():
    """A GPU-hour figure on a tool declaring no GPU bills the ledger for a device the task
    never held -- the mistake EI.8 found on the liganchor twin."""
    for path in sorted(DECLARATIONS):
        spec = _spec(path)
        gpus = int((spec.get("resources") or {}).get("gpus", 0))
        if "gpu_hours" in spec["cost_model"]["cost"]:
            assert gpus >= 1, f"{path} bills gpu_hours and declares gpus: {gpus}"


# ---------------------------------------------------------------------------
# what the declarations cost the two chains
# ---------------------------------------------------------------------------


def test_the_design_chain_fits_inside_the_untrusted_cap():
    """So it promotes the ordinary way: three consecutive clean runs, no assertion."""
    gpu = _chain_cost(DESIGN_CHAIN, "gpu_hours")
    needs = gpu / PROVISIONAL_BUDGET_FRACTION
    assert gpu == pytest.approx(1.5), f"the design chain declares {gpu} GPU-h"
    assert needs <= ENVELOPE_LOW, (
        f"the design chain needs {needs} GPU-h available to clear the "
        f"{PROVISIONAL_BUDGET_FRACTION:.0%} "
        f"cap, against an envelope of {ENVELOPE_LOW}-{ENVELOPE_HIGH}"
    )


def test_the_labels_chain_is_refused_by_its_own_interlock_and_that_is_expected():
    """**Asserted as expected behaviour, so nobody reads it as a bug.**

    An honestly declared labels chain needs 261 GPU-h available to clear a 10% cap, against a
    96-192 per-round envelope. It is refused, three times, which is exactly the failure
    impress-a already has on record (`plans/backlog.md:239`: "against the untrusted-pattern cap
    of 0.60 -- 10% of a 6.0 budget -- the chain was refused three times").

    The fix is **not** to shrink the declarations. Under-declaring to fit a cap is the other
    documented failure and it removes a stage silently. The fix is
    `impress-a trust --assert --reason "<job id>"`, whose evidence is named in item 21's plan
    section and does not exist until M2. This test exists so that the day someone meets the
    refusal, the repository already says it was predicted and says what to do instead.
    """
    chain = _chain_cost(LABELS_CHAIN, "gpu_hours")
    needs = chain / PROVISIONAL_BUDGET_FRACTION
    assert chain == pytest.approx(26.1)
    assert needs == pytest.approx(261.0)
    assert needs > ENVELOPE_HIGH, (
        "the labels chain now fits the envelope, so the assert path may no longer be needed -- "
        "which is a change to item 21's whole argument and wants saying out loud"
    )


def test_md_label_alone_fits_and_abfe_label_alone_does_not():
    """Decision L1's third justification, in arithmetic.

    Splitting the chain is what makes *one* of the two promotable the ordinary way. A single
    two-stage chain would have needed the assertion for both halves.
    """
    md = _declared("asteer_labels/md_label", "gpu_hours") / PROVISIONAL_BUDGET_FRACTION
    abfe = _declared("asteer_labels/abfe_label", "gpu_hours") / PROVISIONAL_BUDGET_FRACTION
    assert md == pytest.approx(81.0) and md <= ENVELOPE_LOW
    assert abfe == pytest.approx(180.0) and abfe > ENVELOPE_LOW
    assert abfe <= ENVELOPE_HIGH, (
        "abfe_label alone no longer fits even the high end of the envelope, which changes "
        "what the assertion is being asked to cover"
    )
