"""Known-bad fixtures: every real tool's QC gates, run against output that should fail.

`docs/reference/authoring-tools.md` requires each tool to carry known-BAD outputs under
`toolkits/<tk>/tools/<id>/tests/`, on the grounds that *a gate that has never seen the
output it was written to catch is an assertion, not a test*. Until this file existed, no
toolkit carried any (backlog B2), so every real toolkit's QC was exactly that assertion:
`mock_noodle` was the only thing in the repo that lied, and it lied only to the mock tier.

What a green run here proves: for each real tool, its **declared** gates FAIL on a payload
that records a failure actually reachable in its adapter, and PASS on a plausible good
one. Gates take `(raw_output_dict, params)`, so this needs no artifact on disk, no
science stack and no backend - `gemmi` and `pyrosetta` are not installed in the dev venv
and nothing here imports them.

What it deliberately does NOT prove: that the *artifact* contract holds (that is
`_as_artifacts`, covered in `test_real_toolkits.py` - every fixture's `outputs` is `{}`),
and nothing whatever about whether the real binaries behave this way. These payloads are
transcribed from the adapters' own branches, not observed from a run; backlog A1 is still
open. Where a fixture pins behaviour that is itself a defect, its `why` says so.

Fixture format - `<name>.bad.json` / `<name>.good.json`, three keys:

    {"why": "...", "failing_gates": ["output_present"], "output": {...}}

The **filename suffix is authoritative**, never a field inside the file: a typo'd
`"expect": "pass"` would be silently wrong, a wrong suffix cannot be. Tool-native
artifacts (a real FASTA, a real out_dir listing) live under `tests/raw/`, which the
loader never globs.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from impress_a.core.qc import GateOutcome, QCReport, QCVerdict
from impress_a.tools import gates
from impress_a.tools.registry import Registry


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


def _tool_dirs() -> dict[str, pathlib.Path]:
    """tool id -> its directory, over every root `Registry.search_paths()` will use.

    Derived from the registry's own roots rather than `tests/../toolkits` so that
    $IMPRESS_A_TOOLKITS and a non-editable install see exactly what the registry sees.
    """
    return {p.parent.name: p.parent
            for root in Registry.search_paths()
            for p in sorted(root.glob("*/tools/*/spec.yaml"))}


def _fixtures() -> list[tuple[str, pathlib.Path, bool]]:
    """(tool_id, path, must_fail) for every fixture file. Two globs, so `raw/` is safe."""
    out = []
    for tool_id, d in sorted(_tool_dirs().items()):
        for path in sorted(d.glob("tests/*.bad.json")):
            out.append((tool_id, path, True))
        for path in sorted(d.glob("tests/*.good.json")):
            out.append((tool_id, path, False))
    return out


def _run_spec_gates(spec, payload: dict) -> QCReport:
    """Exactly what `TaskAgent.post_process` does to build a QCReport, minus artifacts."""
    qc = QCReport()
    for g in spec.qc_gates:
        qc.add(gates.get(g.id)(payload, g.params))
    return qc


@pytest.mark.parametrize("tool_id,path,must_fail", _fixtures(),
                         ids=lambda v: v.name if isinstance(v, pathlib.Path) else None)
def test_gate_fixture(reg, tool_id, path, must_fail):
    """Each recorded output gets the verdict its filename claims, from the real gates."""
    doc = json.loads(path.read_text())
    assert doc["why"].strip(), \
        f"{path.name}: a fixture that does not say what it records is an assertion"

    report = _run_spec_gates(reg.get(tool_id), doc["output"])
    failed = {r.gate for r in report.gates if r.outcome is GateOutcome.FAIL}

    if must_fail:
        assert report.verdict is QCVerdict.FAIL, f"{path.name}: expected FAIL"
        assert not report.eligible_for_front, "a FAIL node must never be rankable"
        if "failing_gates" in doc:
            # An exact set: a fixture must not claim to demonstrate one gate while
            # actually tripping another.
            assert failed == set(doc["failing_gates"]), \
                f"{path.name}: failing gates were {sorted(failed)}"
    else:
        assert report.verdict is QCVerdict.PASS, \
            f"{path.name}: expected PASS, these gates failed: {sorted(failed)}"
        assert report.eligible_for_front


async def test_a_known_bad_fixture_fails_qc_through_post_process(reg):
    """The fixtures are checked against the same path a campaign uses, not a parallel one.

    `_run_spec_gates` mirrors `TaskAgent.post_process`; this runs the real thing once to
    prove the mirror is faithful. `empty_out_dir.bad.json` is used because its `outputs`
    is `{}`, so `_as_artifacts` is a no-op and no file has to exist on disk.
    """
    from impress_a.tools.agent import TaskRequest

    path = _tool_dirs()["rfd3_design"] / "tests" / "empty_out_dir.bad.json"
    payload = json.loads(path.read_text())["output"]

    agent = reg.agent_for("rfd3_design")(reg.get("rfd3_design"))
    result = await agent.post_process(TaskRequest(tool="rfd3_design"), payload)

    assert result.qc.verdict is QCVerdict.FAIL
    assert not result.qc.eligible_for_front


async def test_the_noodle_fixture_matches_what_the_noodle_agent_produces(reg):
    """The one fixture that can be cross-checked against the code that produces it.

    `mock_noodle` manufactures a constant known-bad output, so its fixture can be pinned
    to the agent directly and cannot drift from the thing it documents.
    """
    from impress_a.tools.agent import TaskRequest

    agent = reg.agent_for("mock_noodle")(reg.get("mock_noodle"))
    raw = await agent.run(TaskRequest(tool="mock_noodle"), {"num_designs": 2})

    path = _tool_dirs()["mock_noodle"] / "tests" / "noodle.bad.json"
    recorded = json.loads(path.read_text())["output"]
    assert raw["metrics"] == recorded["metrics"]
    assert raw["result"] == recorded["result"] and raw["count"] == recorded["count"]


def test_ligandmpnn_confidence_header_parsing():
    """A parser failure is currently reported as a low-confidence design (backlog F4).

    `_CONF_RE` is module-level and needs nothing installed, so it is the one tool-native
    artifact in the repo that is testable today - every other extraction path is inline
    in a `run()` body. When the regex does not match, the loop at
    `ligandmpnn_agents.py:74-78` leaves `overall = ligand = 0.0` and the agent reports a
    confident-looking zero. This test pins that: it is a bug report, not an endorsement.
    See `unparsed_confidence_header.bad.json`.
    """
    from impress_a.tools import ligandmpnn_agents

    raw = _tool_dirs()["ligandmpnn_design"] / "tests" / "raw"
    good = ligandmpnn_agents._CONF_RE.search((raw / "parsed_header.fa").read_text())
    assert good and good.groups() == ("0.6421", "0.5817")

    bad = ligandmpnn_agents._CONF_RE.search((raw / "unparsed_header.fa").read_text())
    assert bad is None, "if this ever matches, the 0.0/0.0 fallback fixture is stale"


def test_count_matches_request_catches_a_fabricated_count():
    """Backlog B3's first test: the gate is implemented and referenced by no spec.

    `FastRelaxAgent` was, until recently, fabricating exactly the count this gate would
    have caught. Its payload is inline rather than a fixture file because it is bad by a
    gate its tool does not declare, which would break the `.bad`/`.good` contract.
    """
    assert "count_matches_request" in gates.known()
    fn = gates.get("count_matches_request")

    assert fn({"count": 4}, {"expected": 1}).outcome is GateOutcome.FAIL
    assert fn({"count": 1}, {"expected": 1}).outcome is GateOutcome.PASS
    # No `expected` means the gate abstains - which is why wiring it up needs a param,
    # not just an entry in a spec's gate list.
    assert fn({"count": 4}, {}).outcome is GateOutcome.PASS


def test_every_real_tool_carries_a_known_bad_fixture(reg):
    """The decay guard, as a rule rather than a list of today's tools.

    The `mock` toolkit is exempt: its agents manufacture their known-bad output in code,
    and `test_campaign.py::test_lying_tool_is_caught_by_qc` already asserts a whole
    campaign catches it. The real tools have no such manufactured failure, which is
    exactly what backlog B2 complains about - so a new real tool with gates and no
    fixture fails here.
    """
    dirs = _tool_dirs()
    missing = [t for t in reg.ids()
               if reg.get(t).qc_gates and reg.get(t).toolkit != "mock"
               and not list(dirs[t].glob("tests/*.bad.json"))]
    assert missing == [], f"no known-bad fixture for: {missing}"


def test_no_orphan_or_unsuffixed_fixtures():
    """A renamed tool must not leave fixtures behind, and `raw/` must stay out of band."""
    dirs = _tool_dirs()
    roots = {r for root in Registry.search_paths() for r in [root]}

    orphans = [str(p) for root in roots for p in root.glob("*/tools/*/tests")
               if p.parent.name not in dirs]
    assert orphans == [], f"fixtures for tools that do not exist: {orphans}"

    unsuffixed = [str(p) for d in dirs.values() for p in d.glob("tests/*.json")
                  if not p.name.endswith((".bad.json", ".good.json"))]
    assert unsuffixed == [], \
        f"a fixture's suffix is authoritative; tool-native files belong in raw/: {unsuffixed}"


def test_the_registry_registers_every_tool_directory_on_disk(reg):
    """`impress-a tools` listing fewer tools than exist on disk is the SHAPE of a failure.

    Loading is validating and it is all-or-nothing: an unknown gate id, a default outside
    its own range or a SKILL.md missing a section disables a WHOLE toolkit and registers
    nothing, never a partial set. That shows up as a shorter list, which is easy to miss
    by eye. Derived from disk, never a constant - CLAUDE.md warns that a magic number in
    a test is often a bug report, and this particular count has already drifted in prose.
    """
    on_disk = sorted(_tool_dirs())
    assert reg.ids() == on_disk
    assert reg.errors == []


def test_a_tool_directory_is_named_for_its_spec_id():
    """The documented layout is `tools/<tool_id>/spec.yaml`, and nothing enforced it.

    The fixture loader above resolves a tool to its directory by name, so a spec whose
    `id` disagrees with its directory would silently get no fixtures.
    """
    import yaml

    mismatched = []
    for root in Registry.search_paths():
        for p in sorted(root.glob("*/tools/*/spec.yaml")):
            spec_id = yaml.safe_load(p.read_text())["id"]
            if spec_id != p.parent.name:
                mismatched.append(f"{p.parent.name}/ declares id {spec_id!r}")
    assert mismatched == []


def test_every_tool_declares_the_metrics_it_reports():
    """`ToolSpec.metrics` is what tells the executor whether a graph can measure anything.

    It exists because inferring the set from `metric_in_range` gate params does not work: a
    tool that emits a metric without gating on it reads as producing nothing. The first
    version did infer it, and warned on `mock-stabilize` that the graph could not produce
    ddg, iptm or sc_rmsd - while that same run returned a four-node front carrying exactly
    those three. A warning that fires on a healthy campaign is noise, and noise is how the
    real case gets ignored.

    So: every non-P6 tool must declare at least one metric, and every metric any gate names
    must appear in the declaration. The second half is the one that catches drift - a gate
    referring to a metric the tool no longer reports is a tool whose QC silently stopped
    applying.
    """
    from impress_a.tools.spec import Pattern

    reg = Registry().load()
    assert not reg.errors, reg.errors

    undeclared, ungated = [], []
    for tid in reg.ids():
        spec = reg.get(tid)
        if spec.pattern is Pattern.P6:
            continue
        if not spec.metrics:
            undeclared.append(tid)
        gated = {g.params.get("metric") for g in spec.qc_gates if g.params.get("metric")}
        if missing := gated - set(spec.metrics):
            ungated.append(f"{tid} gates on {sorted(missing)} but does not declare it")

    assert not undeclared, \
        f"these tools declare no metrics, so any graph using them looks unable to " \
        f"measure anything: {undeclared}"
    assert not ungated, "; ".join(ungated)
