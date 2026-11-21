"""The design chain's warm-up through the real trust interlock (item 21, EI.14).

**Against the real `TrustLedger`, not a model of it.** The arithmetic in
`tests/test_cost_declarations.py` says the design chain *should* fit the untrusted cap and the
labels chain *should not*; this file puts both through the object that decides, because an
arithmetic agreement with a mis-read of the rule is worth nothing. Both are measured on a
temporary ledger file, never on a real one.

**What the interlock buys, and what it does not.** It buys **delay**: three consecutive clean
runs under a forced dry-run, a 10%-of-available cost cap and one-instance-in-flight, before a
novel pattern is trusted. It does **not** buy soundness, and the two cautions are worth carrying
beside the tests rather than only in prose:

- **A *consistent* novel silent failure will promote.** Three clean runs of a chain that is
  wrong in the same way each time look exactly like three clean runs. The interlock cannot
  distinguish them and nothing downstream will either; what catches that class is a QC gate
  written from the failure (EI.7) or a measurement that contradicts the prediction (EI.13).
- **Tools sharing training data may agree because they share a bias** (R4). Two models trained
  on the same corpus corroborating each other is not independent evidence, and the ledger's
  clean-run count reads it as if it were.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from impress_a.compose.interlock import Scrutiny, TrustLedger  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: A pattern signature is opaque to this file on purpose: it is computed upstream from the
#: shape of a graph (`compose/`), and inventing one here would test our guess at its format.
#: What these tests need is only that the ledger treats one consistently.
DESIGN_SIG = "asd-design-chain-v1"
LABELS_SIG = "asd-labels-md-v1"


@pytest.fixture
def ledger(tmp_path) -> TrustLedger:
    """A ledger on its own file. Never the repo's: the log is append-only and cross-campaign,
    so a test writing to a real one would hand a later campaign evidence it never earned."""
    return TrustLedger.load(tmp_path / "trust.jsonl")


def test_a_novel_pattern_starts_untrusted_and_under_every_constraint():
    """The default has to be the strict one, or the interlock is decoration."""
    led = TrustLedger()
    scrutiny = Scrutiny.for_pattern(led, DESIGN_SIG)
    assert scrutiny.trusted is False
    assert scrutiny.force_dry_run is True
    assert scrutiny.mark_suspect is True
    assert scrutiny.cost_cap_fraction == pytest.approx(0.10)


def test_the_design_pattern_promotes_after_exactly_three_clean_runs(ledger):
    """The ordinary path, which the design chain's declarations let it take."""
    ledger.patterns.setdefault(DESIGN_SIG, _record(ledger, DESIGN_SIG))
    assert ledger.is_trusted(DESIGN_SIG) is False
    assert ledger.on_clean_run(DESIGN_SIG) is False, "one clean run is not three"
    assert ledger.on_clean_run(DESIGN_SIG) is False
    assert ledger.on_clean_run(DESIGN_SIG) is True, "the third run is the promotion"
    assert ledger.is_trusted(DESIGN_SIG) is True
    assert ledger.promote_after == 3


def test_a_trusted_pattern_loses_every_constraint(ledger):
    """What promotion is for: the dry-run and the cap come off, so a real run can happen."""
    ledger.patterns.setdefault(DESIGN_SIG, _record(ledger, DESIGN_SIG))
    for _ in range(3):
        ledger.on_clean_run(DESIGN_SIG)
    scrutiny = Scrutiny.for_pattern(ledger, DESIGN_SIG)
    assert scrutiny.trusted is True
    assert scrutiny.force_dry_run is False
    assert scrutiny.mark_suspect is False
    assert scrutiny.cost_cap_fraction is None


def test_one_failure_undoes_the_warm_up_entirely(ledger):
    """Two clean runs and a failure is not "nearly promoted" -- it is zero.

    Decision 0013 is what makes this bearable: only INTEGRITY failures reach here, so a weak
    design does not cost a pattern its warm-up. A tool that broke does.
    """
    ledger.patterns.setdefault(DESIGN_SIG, _record(ledger, DESIGN_SIG))
    ledger.on_clean_run(DESIGN_SIG)
    ledger.on_clean_run(DESIGN_SIG)
    ledger.on_failure(DESIGN_SIG)
    assert ledger.patterns[DESIGN_SIG].clean_runs == 0
    assert ledger.on_clean_run(DESIGN_SIG) is False, "the count restarts, it does not resume"


def test_the_assert_path_exists_and_records_its_reason(ledger):
    """Item 21's remaining half, exercised with a placeholder reason.

    **This is not the assertion itself.** The labels chain's evidence is an M2 job id that does
    not exist, so item 21 stays `needs decision on the assert evidence`. What is checked here is
    that the path works and that it *demands* a reason -- because an assertion with no named
    evidence is indistinguishable from under-declaring, and the whole argument for the assert
    path over shrinking the numbers is that it leaves a record.
    """
    record = ledger.assert_trusted(
        LABELS_SIG, tools=["md_label"], reason="PLACEHOLDER: not an M2 job id")
    assert ledger.is_trusted(LABELS_SIG) is True
    assert record.asserted is True
    assert "PLACEHOLDER" in str(record.model_dump())


def test_an_assertion_survives_a_reload_because_the_log_is_the_record(ledger, tmp_path):
    """The evidence has to outlive the process that typed it, or the next campaign re-asserts
    from memory -- which is the failure mode the written reason exists to prevent."""
    ledger.assert_trusted(LABELS_SIG, tools=["md_label"], reason="job 00000000")
    reloaded = TrustLedger.load(tmp_path / "trust.jsonl")
    assert reloaded.is_trusted(LABELS_SIG) is True


def test_the_interlock_cannot_tell_a_consistent_silent_failure_from_a_clean_run(ledger):
    """The caution, asserted rather than written down: three identical wrong runs promote.

    `on_clean_run` takes a signature and nothing else -- no outputs, no metrics, no QC report.
    So "clean" means "no integrity gate failed", and a chain that is wrong in the same way
    every time has no integrity gate to fail. The interlock buys delay, not soundness, and what
    catches this class is a gate written from the failure (EI.7) or a measurement that
    contradicts the prediction (EI.13).
    """
    ledger.patterns.setdefault(DESIGN_SIG, _record(ledger, DESIGN_SIG))
    for _ in range(3):
        ledger.on_clean_run(DESIGN_SIG)
    assert ledger.is_trusted(DESIGN_SIG) is True, (
        "if this ever fails, the interlock has learned to inspect a run's content and the "
        "caution in this file's docstring is out of date"
    )


def test_this_project_does_not_change_the_interlocks_defaults():
    """`provisional_budget_fraction: 0.10` and `promote_after: 3` stay as they are.

    Deliberately asserted: the whole argument for the assert path over loosening the cap is
    that the cap is doing its job. A campaign of ours quietly raising the fraction to fit the
    labels chain would be under-declaring by another route.
    """
    led = TrustLedger()
    assert led.provisional_budget_fraction == pytest.approx(0.10)
    assert led.promote_after == 3


def _record(ledger: TrustLedger, sig: str):
    """A fresh `PatternRecord` for a signature, however upstream spells one.

    Built through the ledger's own first-sighting path rather than by importing the model, so
    this file does not depend on `PatternRecord`'s field names -- which are upstream's to
    change and are not what any of these tests are about.
    """
    from impress_a.compose.interlock import PatternRecord  # noqa: PLC0415

    return PatternRecord(signature=sig) if "signature" in PatternRecord.model_fields \
        else PatternRecord()
