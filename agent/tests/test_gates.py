"""Six QC gates, built in to impress-a since 2026-11-21 (item 15, EI.7, moved by H6).

**They were registered from OUTSIDE this checkout until H6**, by importing
`asteer.impress.gates` for its decorator side effects — and the test that mattered most in
this file was the one asserting that import happened in a fresh interpreter, because the
registration was the only thing that could fail in a way the rest of the suite would hide.
That whole class of failure is gone: the six are defined in `impress_a/tools/gates.py` beside
the other five, so there is nothing to import for effect, nothing to set
`$IMPRESS_A_GATE_MODULES` to, and nothing a stock `impress-a run` can forget. The three
registration tests are rewritten below rather than deleted, because what they were protecting
against is worth a reader knowing about.

Each gate's test is written from the failure it exists for rather than from its code, which is
also why the payloads are the shapes real tools produce.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

from asteer.conditioning import check_from_pipeline  # noqa: E402

from impress_a.core.qc import GateOutcome  # noqa: E402
from impress_a.tools import gates as impress_gates  # noqa: E402
from impress_a.tools.gates import ASD_GATE_IDS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def run(gate_id: str, out: dict, params: dict | None = None):
    """Through `gates.get`, not the function directly: the registry lookup is half the point."""
    return impress_gates.get(gate_id)(out, params or {})


def passed(result) -> bool:
    return result.outcome is GateOutcome.PASS


# ---------------------------------------------------------------------------
# the registration, which is the only part that can fail silently
# ---------------------------------------------------------------------------


def test_the_six_are_known_to_a_cold_interpreter_that_imports_nothing_else():
    """What H6 bought, asserted the same way the thing it replaced was.

    Before H6 this test imported `asteer.impress` first and checked the six appeared; its
    companion checked they were *absent* without that import, which is what made the first
    one mean anything. Both are now one test: importing `impress_a.tools.gates` alone is
    enough, from a fresh interpreter, with no `$IMPRESS_A_GATE_MODULES` and no `asteer` on
    the path at all.

    Why it is still worth a subprocess: a gate exists only once the module defining it has
    run, and two things resolve ids without forgiving a miss. `Registry._load_toolkit` calls
    `gates.get()` per declared gate and a `KeyError` disables the **whole toolkit** —
    all-or-nothing, one line in `errors`, no refusal anywhere. And `compose/validate.py`
    never consults the registry, so an unknown id is not caught at compose time and fails in
    `post_process`, after the task has run and been billed. Being built in is what makes
    both unreachable for these six; nothing else does.
    """
    code = ("from impress_a.tools import gates;"
            f"print(all(g in gates.known() for g in {list(ASD_GATE_IDS)!r}))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.strip() == "True", (
        "the six are not built in: H6 moved them here precisely so that importing "
        "impress_a.tools.gates is sufficient"
    )


def test_all_six_are_registered_and_none_collides_with_one_that_was_here_first():
    """Six ids, and a name clash would silently replace another gate.

    `@gate` assigns into a dict, so registering an existing id overwrites it with no warning.
    That hazard did not go away when these moved in — it got closer, because the five they
    now sit beside are in the same file. A built-in `metrics_reported` quietly becoming ours
    is the kind of thing found by a confused bug report months later.
    """
    assert len(ASD_GATE_IDS) == 6
    older = {"output_present", "count_matches_request", "metrics_reported",
             "metric_in_range", "has_secondary_structure"}
    assert not set(ASD_GATE_IDS) & older, "a gate id collides with one that was here first"
    assert older <= set(impress_gates.known()), "H6 displaced a gate that was here first"
    for gate_id in ASD_GATE_IDS:
        assert impress_gates.get(gate_id) is not None


# ---------------------------------------------------------------------------
# one test per gate, written from the failure it exists for
# ---------------------------------------------------------------------------


def test_ligand_present_in_complex_catches_the_boltz_failure():
    """The documented case: Boltz run with no ligand chain, `ligand_iptm` papered over as 0.0.

    A complex with no ligand is a prediction of the wrong system, not a weak binder — every
    other number on the node describes something nobody asked about.
    """
    assert passed(run("ligand_present_in_complex", {"metrics": {"n_ligand_atoms": 30}}))
    assert not passed(run("ligand_present_in_complex", {"metrics": {"n_ligand_atoms": 0}}))
    assert not passed(run("ligand_present_in_complex", {"metrics": {}})), (
        "an absent count read as present"
    )


def test_chain_break_declines_to_guess_when_the_metric_is_missing():
    """Consecutive Cα atoms sit at 3.8 Å, so 4.5 is a break rather than a strained bond.

    The missing-metric case is the interesting one: *not reported* is not *fine*. A gate that
    passed on absence would make a broken backbone indistinguishable from an unmeasured one, and
    a broken backbone scores well on anything that averages over residues.
    """
    assert passed(run("chain_break", {"metrics": {"max_ca_gap_angstrom": 3.9}}))
    assert not passed(run("chain_break", {"metrics": {"max_ca_gap_angstrom": 7.2}}))
    absent = run("chain_break", {"metrics": {}})
    assert not passed(absent)
    assert "not reported" in absent.detail


def test_contig_length_needs_a_request_to_check_against():
    """A contig is a request, not a preference, so tolerance defaults to 0.

    And a gate with no `requested` param fails rather than passing: it cannot check a request
    nobody declared, and saying so is better than reporting a pass it did not earn.
    """
    out = {"metrics": {"contig_length": 120}}
    assert passed(run("contig_length", out, {"requested": 120}))
    assert not passed(run("contig_length", out, {"requested": 128}))
    assert passed(run("contig_length", out, {"requested": 122, "tolerance": 2}))
    assert not passed(run("contig_length", out)), "no request, yet it passed"


def test_surrogate_version_present_is_the_attribution_gate():
    """CON-5, and integrity-role for the reason in the docstring.

    A score with no model version is not a weak result — it is a result nobody can attribute,
    and per decision 0013 only integrity failures demote a pattern, so treating this as
    acceptance would let a chain accumulate trust on numbers whose provenance is gone.
    """
    attributed = {"metrics": {"dg_corrected": -9.1},
                  "model_versions": {"dg_corrected": "affdelta@v3"}}
    assert passed(run("surrogate_version_present", attributed, {"metrics": ["dg_corrected"]}))

    stripped = {"metrics": {"dg_corrected": -9.1}, "model_versions": {}}
    result = run("surrogate_version_present", stripped, {"metrics": ["dg_corrected"]})
    assert not passed(result)
    assert "accumulate trust" in result.detail

    # A metric the tool did not report is `metrics_reported`'s business, not this gate's.
    assert passed(run("surrogate_version_present", {"metrics": {}},
                      {"metrics": ["dg_corrected"]}))


def test_calibration_in_range_is_the_one_acceptance_gate_and_collapse_is_the_danger():
    """A σ outside range means the model needs recalibrating, not that the run broke.

    Collapse is the dangerous direction: item 14 ranks on the **lower confidence bound** of C's
    ΔG, so a σ near zero turns an LCB into a posterior mean and the ranking silently stops
    accounting for uncertainty — with 10–20 ATM labels recalibrating a GP rather than fitting it,
    an over-confident model is more damaging than an uncertain one.
    """
    assert passed(run("calibration_in_range", {"metrics": {"sigma_dg": 0.8}}))
    collapsed = run("calibration_in_range", {"metrics": {"sigma_dg": 0.0001}})
    assert not passed(collapsed)
    assert "collapsed" in collapsed.detail
    assert not passed(run("calibration_in_range", {"metrics": {"sigma_dg": 40.0}}))


def test_conditioning_applied_catches_a_run_conditioned_on_nothing():
    """Item 29's gate, against M0's measured failure (job 24155612).

    RFD3 resolves a ligand `select_hotspots`, `build()` drops the annotation, zeros are
    supplied, and the design **completes and reports success**. Item 26 answers that instance in
    the `rfd3` wrapper; this answers the class.
    """
    ok = {"metrics": {"conditioning_requested": 6, "conditioning_applied": 6}}
    assert passed(run("conditioning_applied", ok))

    dropped = {"metrics": {"conditioning_requested": 6, "conditioning_applied": 0}}
    result = run("conditioning_applied", dropped)
    assert not passed(result)
    assert "conditioned on nothing" in result.detail


def test_the_unsteered_control_arm_passes_the_conditioning_gate():
    """Nothing requested means nothing dropped, and the control **must** pass.

    M2 runs an unsteered `rfd3_design` arm at the same N as the steered one, and it is the
    control the steered arm is read against. A control that failed QC would make the comparison
    unreadable, which is a worse outcome than the gate missing a case.
    """
    assert passed(run("conditioning_applied",
                      {"metrics": {"conditioning_requested": 0, "conditioning_applied": 0}}))


def test_a_tool_that_declares_the_gate_and_reports_no_counts_fails_closed():
    """The alternative reads as "nothing was asked for", which is the silent success the gate
    exists to catch. Failing closed names the wiring that is missing instead."""
    result = run("conditioning_applied", {"metrics": {}})
    assert not passed(result)
    assert "asteer.conditioning" in result.detail


def test_the_counts_the_gate_reads_come_from_one_shared_implementation():
    """`check_from_pipeline` is the only sanctioned producer, so the gate and the tool cannot
    drift: the gate's contract is two metric names and this is what fills them.

    It also inherits `asteer.conditioning`'s narrow rule — only a per-entry numeric array
    counts, never the request echoed back — which is the trap the probe fell into once.
    """
    pipeline = {"features": {"is_atom_level_hotspot": [1, 1, 0, 0, 0, 0]},
                "specification": {"select_hotspots": {"A:R": "S1,O5"}}}
    metrics = check_from_pipeline(pipeline, requested=6)
    assert metrics == {"conditioning_requested": 6.0, "conditioning_applied": 2.0}
    assert passed(run("conditioning_applied", {"metrics": metrics}))

    echoed_only = {"specification": {"select_hotspots": {"A:R": "S1,O5,O7,O8,S2,O6"}},
                   "features": {"is_atom_level_hotspot": [0, 0, 0, 0, 0, 0]}}
    assert check_from_pipeline(echoed_only, requested=6)["conditioning_applied"] == 0.0
    assert not passed(run("conditioning_applied",
                          {"metrics": check_from_pipeline(echoed_only, requested=6)}))


def test_every_gate_defaults_to_integrity_when_a_spec_omits_the_role():
    """`GateResult.role` defaults to `integrity`, the conservative reading, and `gates.evaluate`
    stamps the spec's role over it. So a spec that wants `acceptance` has to say so — which is
    the right default, because the expensive mistake is a tool failure counted as a weak
    design."""
    for gate_id in ASD_GATE_IDS:
        result = run(gate_id, {"metrics": {}}, {"requested": 1, "metrics": ["x"]})
        assert result.role == "integrity", f"{gate_id} defaults to {result.role}"


# ---------------------------------------------------------------------------
# Retired at H6, 2026-11-21: two tests of a constraint these gates no longer have
#
# `test_a_spec_declaring_one_of_these_gates_still_loses_its_whole_toolkit_with_no_hook` and
# `test_the_gate_modules_hook_makes_that_same_spec_load` measured the two arms of
# `$IMPRESS_A_GATE_MODULES` against a copy of these toolkits: without the hook a spec
# declaring `conditioning_applied` lost its whole toolkit, with it the toolkit loaded. Both
# premises are false now that the six are built in -- the spec loads either way.
#
# They are not replaced here. The hook is still impress-a's feature and still matters for a
# gate that really does live outside this package; `tests/test_gate_modules.py` covers it on
# a synthetic tree that does not depend on who ships which gate, which is where a test of an
# extension point belongs. These two covered it by accident of being its only user.
#
# What the retired pair found is worth keeping in writing, because it corrected the plan that
# predicted it: external registration was said to work "provided the gate module is imported
# before evaluate() runs", and the real condition was **before Registry.load() runs**, which
# is much earlier -- and the cost of missing it was not one gate failing but the whole
# toolkit registering nothing, all-or-nothing, with one line in `reg.errors` and no refusal.
# That is the hazard H6 removes for these six by making them unremarkable.
# ---------------------------------------------------------------------------


def test_a_shipped_spec_declares_only_gates_the_registry_can_resolve():
    """**Relaxed twice and replaced rather than deleted both times.**

    It began by asserting that every gate id we ship is one the *stock* registry knows,
    because the alternative was a toolkit that silently disappeared. Item 39's hook removed
    the reason for that ban but not the obligation, since the hook is opt-in, so the rule
    became two-part: a gate id is stock or one of ours, and a toolkit declaring one of ours
    must name `IMPRESS_A_GATE_MODULES` in its `SKILL.md` Pitfalls.

    **H6 removed the obligation as well (2026-11-21).** The six are built in, so there is no
    variable for a launch to forget and the second half has no subject -- it was waiting on
    "the commit that adds the first such spec", and that commit will never come. What is left
    is the original check, which is the one that was always doing the work: every gate id a
    shipped spec declares must be one the registry can resolve, or its whole toolkit
    registers nothing.
    """
    import yaml

    known = set(impress_gates.known())
    assert set(ASD_GATE_IDS) <= known, "the six are no longer built in; H6 has been undone"
    for spec_path in sorted((REPO / "toolkits").glob("*/tools/*/spec.yaml")):
        declared = {g["id"] for g in yaml.safe_load(spec_path.read_text())["qc_gates"]}
        assert declared <= known, (
            f"{spec_path.relative_to(REPO)} declares {sorted(declared - known)}, which no "
            "registry can resolve -- its whole toolkit would register nothing"
        )
