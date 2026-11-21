"""Six QC gates registered into impress-a from outside its checkout (item 15, EI.7).

**`test_the_registration_survives_a_cold_interpreter` is the one that matters.** Everything else
here is arithmetic over synthetic payloads; the registration is the only thing that can be wrong
in a way the rest of the suite would hide, because by the time any other test runs this module has
already imported `asteer.impress`. The guarantee is asserted in a fresh interpreter, twice: once
that importing the package registers all six, and once that *not* importing it leaves them absent
— the second being what makes the first mean something.

Each gate's test is written from the failure it exists for rather than from its code, which is
also why the payloads are the shapes real tools produce.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")

import asteer.impress  # noqa: E402,F401  -- the registration under test
from asteer.impress.gates import GATE_IDS, check_from_pipeline  # noqa: E402

from impress_a.core.qc import GateOutcome  # noqa: E402
from impress_a.tools import gates as impress_gates  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def run(gate_id: str, out: dict, params: dict | None = None):
    """Through `gates.get`, not the function directly: the registry lookup is half the point."""
    return impress_gates.get(gate_id)(out, params or {})


def passed(result) -> bool:
    return result.outcome is GateOutcome.PASS


# ---------------------------------------------------------------------------
# the registration, which is the only part that can fail silently
# ---------------------------------------------------------------------------


def test_the_registration_survives_a_cold_interpreter():
    """A gate exists only once the module defining it has been imported.

    And two things resolve ids without forgiving a miss: `Registry._load_toolkit` calls
    `gates.get()` per declared gate and a `KeyError` disables the **whole toolkit**
    (all-or-nothing, one line in `errors`, no refusal); and `compose/validate.py` never consults
    the registry at all, so an unknown id is not caught at compose time and fails in
    `post_process` — after the task has run and been billed.
    """
    code = (
        "import asteer.impress;"
        "from impress_a.tools import gates;"
        f"print(all(g in gates.known() for g in {list(GATE_IDS)!r}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.strip() == "True", "importing asteer.impress did not register the gates"


def test_without_that_import_the_gates_are_absent():
    """What makes the test above mean something.

    If the gates were somehow registered by importing `impress_a` alone, the guarantee would be
    vacuous and nobody would notice when it stopped holding.
    """
    code = (
        "from impress_a.tools import gates;"
        f"print(any(g in gates.known() for g in {list(GATE_IDS)!r}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr[-1500:]
    assert out.stdout.strip() == "False", (
        "impress-a already knows these ids, so this project's registration proves nothing"
    )


def test_all_six_are_registered_and_none_collides_with_a_built_in():
    """Six ids, and a name clash would silently replace someone else's gate.

    `@gate` assigns into a dict, so registering an existing id overwrites it with no warning —
    a built-in `metrics_reported` quietly becoming ours is the kind of thing that would be found
    by a confused bug report months later.
    """
    assert len(GATE_IDS) == 6
    builtin = {"output_present", "count_matches_request", "metrics_reported",
               "metric_in_range", "has_secondary_structure"}
    assert not set(GATE_IDS) & builtin, "a gate id collides with a built-in and replaced it"
    for gate_id in GATE_IDS:
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
    for gate_id in GATE_IDS:
        result = run(gate_id, {"metrics": {}}, {"requested": 1, "metrics": ["x"]})
        assert result.role == "integrity", f"{gate_id} defaults to {result.role}"


# ---------------------------------------------------------------------------
# The constraint is tighter than the plan said, and it is measured here
# ---------------------------------------------------------------------------


#: The renamed probe tool, which exists only inside the copied toolkit tree.
PROBE_ID = "probe_liganchor_propose"


def _cold_load(root: Path, **env: str) -> list[str]:
    """`(tools matching PROBE_ID, whether an unknown-gate error was reported)`.

    A fresh interpreter with only `PYTHONPATH=src`, so nothing this process imported can be
    mistaken for something the stock registry resolves on its own.

    **The probe tool is renamed in the copy (2026-11-21).** `load(root)` also searches the
    DEFAULT root, which since H4 is this checkout's own `toolkits/` -- so counting a shipped id
    would count the shipped copy and never reach zero, whatever the tmp toolkit did. The id
    below exists only in the copy.
    """
    code = (
        "from impress_a.tools.registry import Registry;"
        f"r = Registry().load({str(root)!r});"
        f"print(sum(1 for t in r.ids() if t.startswith({PROBE_ID!r})),"
        "      any('unknown QC gate' in e for e in r.errors))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO,
                         env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin", **env})
    assert out.returncode == 0, out.stderr[-1200:]
    return out.stdout.split()


@pytest.fixture
def toolkits_declaring_a_gate_of_ours(tmp_path) -> Path:
    """A copy of our toolkits with `conditioning_applied` declared on one real spec.

    A copy and not the shipped tree, because the shipped tree is what
    `test_a_shipped_spec_declares_only_gates_its_launch_path_can_resolve` governs.
    """
    import shutil

    root = tmp_path / "toolkits"
    shutil.copytree(REPO / "toolkits", root)
    # Renamed so the id cannot collide with the shipped one at the default root (see _cold_load).
    tool = root / "mock_asd" / "tools" / "mock_liganchor_propose"
    tool.rename(tool.with_name(PROBE_ID))
    spec = tool.with_name(PROBE_ID) / "spec.yaml"
    spec.write_text(spec.read_text().replace(
        "id: mock_liganchor_propose", f"id: {PROBE_ID}").replace(
        "qc_gates:\n  - {id: output_present, params: {key: result}}",
        "qc_gates:\n  - {id: output_present, params: {key: result}}\n"
        "  - {id: conditioning_applied, role: integrity, params: {}}",
    ))
    return root


def test_a_spec_declaring_one_of_these_gates_still_loses_its_whole_toolkit_with_no_hook(
        toolkits_declaring_a_gate_of_ours: Path):
    """The finding, and it corrects item 15's own statement of the risk.

    The plan said external registration works *"provided the `asteer` gate module is imported
    before `evaluate()` runs"*. The real condition is **before `Registry.load()` runs**, which is
    much earlier — and the consequence is not one gate failing but the **whole toolkit
    registering nothing**, because `_load_toolkit` resolves every declared gate id up front and
    is all-or-nothing. One line in `reg.errors`, no refusal anywhere.

    This half is unchanged by item 39's hook and has to stay measured: the hook is opt-in, so a
    stock `impress-a run` that does not set the variable still loses the toolkit exactly like
    this. It is the reason the variable's absence must be loud in whatever launches us.
    """
    assert _cold_load(toolkits_declaring_a_gate_of_ours) == ["0", "True"]


def test_the_gate_modules_hook_makes_that_same_spec_load(
        toolkits_declaring_a_gate_of_ours: Path):
    """Item 39, from this side: the same cold load, one environment variable different.

    `IMPRESS_A_GATE_MODULES` landed upstream in IMPRESS `6fc103b` — a path-separated list of
    dotted module names imported by `Registry.load()` before any gate id is resolved. This is
    the acceptance test for it measured against *our* six gates and *our* toolkit, which is the
    thing the hook was asked for; upstream's own tests use a fixture toolkit of their own.
    """
    if not hasattr(impress_gates, "GATE_MODULES_ENV"):
        pytest.skip("this impress-a predates the IMPRESS_A_GATE_MODULES hook (item 39)")
    got = _cold_load(toolkits_declaring_a_gate_of_ours,
                     IMPRESS_A_GATE_MODULES="asteer.impress.gates")
    assert got == ["1", "False"], (
        "the hook is present but a spec declaring one of our gates still did not load"
    )


def test_a_shipped_spec_declares_only_gates_its_launch_path_can_resolve():
    """**Relaxed deliberately when item 39 landed, and replaced rather than deleted.**

    It used to assert that every gate id we ship is one the *stock* registry knows, because the
    alternative was a toolkit that silently disappeared. The hook removes the reason for that
    ban: a spec may now declare one of our six. What it does not remove is the obligation, since
    the hook is opt-in — a run that forgets the variable gets the vanished toolkit above.

    So the rule is now two-part: a gate id is either stock or one of ours, and a toolkit that
    declares one of ours must say so in the `Pitfalls` section of its `SKILL.md` — the section
    `REQUIRED_SKILL_SECTIONS` already forces to exist, and the text an operator or an agent
    reads before running the toolkit. Nothing shipped declares one yet, so the second half is
    waiting rather than idle; it fires on the commit that adds the first.
    """
    import yaml

    stock = {"output_present", "count_matches_request", "metrics_reported",
             "metric_in_range", "has_secondary_structure"}
    allowed = stock | set(GATE_IDS)
    for spec_path in sorted((REPO / "toolkits").glob("*/tools/*/spec.yaml")):
        declared = {g["id"] for g in yaml.safe_load(spec_path.read_text())["qc_gates"]}
        assert declared <= allowed, (
            f"{spec_path.relative_to(REPO)} declares {sorted(declared - allowed)}, which no "
            "registry can resolve -- its whole toolkit would register nothing"
        )
        if declared & set(GATE_IDS):
            skill = (spec_path.parents[2] / "SKILL.md").read_text()
            pitfalls = skill.partition("## Pitfalls")[2]
            assert "IMPRESS_A_GATE_MODULES" in pitfalls, (
                f"{spec_path.relative_to(REPO)} declares {sorted(declared & set(GATE_IDS))}, so "
                "every launch of this toolkit needs IMPRESS_A_GATE_MODULES=asteer.impress.gates; "
                "its SKILL.md Pitfalls section must say so"
            )
