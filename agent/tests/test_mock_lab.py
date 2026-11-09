"""The mock knob lab: `analysis/mock_lab.py` + `analysis/mock_figures.py`.

A sweep harness is a measuring instrument, so what this file pins is the places where it
could report a plausible number that is not the one the campaigns produced:

* **Isolation.** Every cell runs under its own run root, trust ledger and seed salt. The
  trust ledger is the one that bites: it is cross-run state, so a shared one makes a cell's
  interlock a function of which cells ran before it, and the sweep becomes a function of its
  own iteration order rather than of the knob.
* **Reading the record, not guessing at it.** An aborted campaign leaves NO `terminated`
  record and a `campaign_ended` one that says `reason: completed`, so the collector has to
  derive the abort from the exit code. A harness that trusted the provenance text would
  report the one arm that failed as finished (backlog G15).
* **Arithmetic that is easy to get subtly wrong.** Busy time is a union of intervals, not a
  sum of durations, or it double-counts the moment `workers > 1` overlaps two tasks. A
  rejected cycle has no execution, and its phases are None rather than 0.0, because a zero
  there reads as "admitted instantly".
* **The figures draw.** Not what they look like - that is a human's job - but that every one
  of them renders from a collected lab without raising, because a figure script that only
  runs against the author's own directory is one nobody else can use.

Only ONE real campaign is launched here (`test_one_cell_runs_end_to_end`). Everything else
works from synthetic provenance, so the file stays inside the local tier's second budget.
"""
from __future__ import annotations

import json
import pathlib

import pytest
import yaml

from impress_a.analysis.mock_lab import (
    ARMS,
    SWEEPS,
    Cell,
    _abort_reason,
    _gate_names,
    _merge,
    _phases,
    _union_busy,
    _write_csv,
    cells,
    collect,
    read_table,
    run_cell,
)

BASE = pathlib.Path("campaigns/mock-small-molecule-binding.yaml")


# -- cell construction --------------------------------------------------------------------

def test_merge_is_recursive_so_a_sweep_keeps_the_other_tools_parameters():
    """A flat update would drop every tool the override does not mention, and the cell would
    quietly run a differently-parameterised chain than the campaign declares."""
    base = {"params": {"mock_rfd3_design": {"difficulty": 0.25, "diffusion_steps": 50},
                       "mock_mpnn_design": {"temperature": 0.2}},
            "replicas": 1}
    out = _merge(base, {"params": {"mock_rfd3_design": {"difficulty": 0.85}}, "replicas": 8})
    assert out["params"]["mock_rfd3_design"] == {"difficulty": 0.85, "diffusion_steps": 50}
    assert out["params"]["mock_mpnn_design"] == {"temperature": 0.2}
    assert out["replicas"] == 8
    assert base["params"]["mock_rfd3_design"]["difficulty"] == 0.25, "mutated its input"


def test_the_arms_are_not_repeated_and_every_sweep_point_is():
    """The arms are what a person runs by hand and what the deck shows, so each is one
    reproducible campaign; the ensembles come from the sweeps, where repeats buy something."""
    out = cells(repeats=3)
    arms = [c for c in out if c.kind == "arm"]
    assert sorted(c.arm for c in arms) == sorted(ARMS)
    for knob, (_, values) in SWEEPS.items():
        got = [c for c in out if c.knob == knob]
        assert len(got) == len(values) * 3
        assert sorted({c.value for c in got}) == sorted(float(v) for v in values)


def test_every_cell_has_its_own_name_and_its_own_salt():
    """Two cells sharing a salt draw the same lineages, so a repeat would add rows without
    adding evidence - and a shared name would have them overwrite each other's run root."""
    out = cells(repeats=3)
    assert len({c.cell for c in out}) == len(out)
    assert len({c.salt for c in out}) == len(out)


def test_only_selects_arms_sweeps_or_one_name():
    assert {c.arm for c in cells(1, ["arms"])} == set(ARMS)
    assert all(c.kind == "sweep" for c in cells(1, ["sweeps"]))
    assert {c.knob for c in cells(1, ["difficulty"])} == {"difficulty"}
    assert [c.arm for c in cells(1, ["baseline"])] == ["baseline"]


# -- reading the record -------------------------------------------------------------------

def test_union_busy_does_not_double_count_overlapping_tasks():
    """`workers: 4` overlaps tasks, so summing durations over-reports; and `wall - sum` can
    go negative, which then renders as negative overhead."""
    assert _union_busy([(0.0, 1.0), (0.5, 2.0)]) == pytest.approx(2.0)
    assert _union_busy([(0.0, 1.0), (2.0, 3.0)]) == pytest.approx(2.0)
    assert _union_busy([(0.0, 1.0), (0.2, 0.3)]) == pytest.approx(1.0)
    assert _union_busy([]) == 0.0


def test_gate_names_reads_both_shapes_provenance_writes():
    """A node's failed gates are full `GateResult` dicts; a task's are bare names."""
    assert _gate_names(["has_secondary_structure"]) == ["has_secondary_structure"]
    assert _gate_names([{"gate": "metric_in_range[ss_fraction]", "role": "acceptance"}]) == [
        "metric_in_range[ss_fraction]"]
    assert _gate_names([]) == []


def test_abort_reason_takes_the_last_exception_line(tmp_path):
    """A traceback chains: the innermost raise prints first and the one that left the process
    prints last, so the first match is the wrong one."""
    log = tmp_path / "cell.log"
    log.write_text("Traceback (most recent call last):\n"
                   "ValueError: an inner cause\n"
                   "impress_a.runtime.executor.CampaignAborted: 3 consecutive all-failed "
                   "runs\n")
    assert _abort_reason(log) == "aborted: 3 consecutive all-failed runs"
    assert "no log" in _abort_reason(tmp_path / "missing.log")


def test_read_table_keeps_an_absent_metric_as_none_not_zero(tmp_path):
    """A tool that could not read a metric OMITS it (the `metrics_reported` invariant), and a
    harness that turned that absence into 0.0 would turn "the tool broke" into "the design is
    weak" - the exact substitution that invariant exists to prevent."""
    path = tmp_path / "t.csv"
    _write_csv(path, [{"a": 1, "b": 0.5, "c": "x", "d": True},
                      {"a": 2, "c": "y"}])
    rows = read_table(path)
    assert rows[0] == {"a": 1, "b": 0.5, "c": "x", "d": True}
    assert rows[1]["b"] is None and rows[1]["d"] is None
    assert rows[1]["a"] == 2


# -- the per-cycle phase breakdown ---------------------------------------------------------

def _record(ts: str, **kw):
    return dict(kw, ts=f"2026-01-01T00:00:{ts}+00:00")


def test_phases_cover_the_cycle_and_separate_the_tools_from_the_waiting():
    keys = {"cell": "c", "kind": "arm", "arm": "baseline", "knob": "", "value": 0.0,
            "rep": 0, "salt": "s"}
    rows = _phases(
        keys,
        camp=[_record("00")],
        graphs=[_record("01", run="r0001", graph="g1", cycle=0)],
        stages=[_record("02", run="r0001", event="deployed")],
        task_rows=[{"run": "r0001",
                    "started_at": "2026-01-01T00:00:04+00:00",
                    "finished_at": "2026-01-01T00:00:05+00:00"},
                   {"run": "r0001",
                    "started_at": "2026-01-01T00:00:04+00:00",
                    "finished_at": "2026-01-01T00:00:06+00:00"}],
        results=[_record("08", run="r0001")],
        trans=[_record("10", event="terminated", reason="done")])
    (row,) = rows
    assert row["plan"] == 1.0 and row["admit"] == 1.0 and row["dispatch"] == 2.0
    assert row["execute"] == 2.0 and row["absorb"] == 2.0
    # Two tasks, each a second or two long, but overlapping - so the tools held 2s of the
    # 2s window, not 3s of it.
    assert row["busy"] == 2.0 and row["exec_wait"] == 0.0
    assert row["cycle_s"] == pytest.approx(8.0)
    assert row["teardown"] == 2.0, "the time after the last result belongs to the campaign"


def test_a_rejected_cycle_reports_none_after_admit_rather_than_zero():
    """A rejected graph never deployed and never ran, and a 0.0 in those columns would read
    as "the gates admitted it instantly" and average into every rate."""
    keys = {"cell": "c", "kind": "arm", "arm": "baseline", "knob": "", "value": 0.0,
            "rep": 0, "salt": "s"}
    (row,) = _phases(keys, camp=[_record("00")],
                     graphs=[_record("01", run="r0001", graph="g1", cycle=0,
                                     rejected={"gate": "interlock", "reason": "capped"})],
                     stages=[], task_rows=[], results=[], trans=[])
    assert row["rejected_gate"] == "interlock"
    assert row["dispatch"] is None and row["execute"] is None and row["absorb"] is None
    assert row["admit"] is None, "nothing deployed, so there is no admit interval either"


# -- one real cell, end to end --------------------------------------------------------------

@pytest.fixture(scope="module")
def one_cell(tmp_path_factory):
    """One real campaign, through the same `impress-a run` subprocess the lab uses.

    Cut down to a single cycle of a single lineage: what is under test is the wiring - the
    run root, the trust directory, the salt, the spec written out and the provenance read
    back - not the campaign, which `tests/test_mock_smb.py` already pins.
    """
    out = tmp_path_factory.mktemp("lab")
    cell = Cell(cell="probe", kind="arm", arm="baseline", knob="", value=0.0,
                salt="probe-salt", rep=0,
                overrides={"replicas": 1, "max_cycles": 1, "target_front": 99,
                           "stagnation_limit": 99})
    base = yaml.safe_load(BASE.read_text())
    rec = run_cell(cell, base, out)
    manifest = {"ts": "", "disclaimer": "", "base_spec": str(BASE),
                "objectives": {o["name"]: o for o in base["objectives"]},
                "cells": [rec]}
    (out / "manifest.json").write_text(json.dumps(manifest))
    return out, rec


def test_one_cell_runs_end_to_end(one_cell):
    out, rec = one_cell
    assert rec["exit_code"] == 0, (out / "logs" / "probe.log").read_text()
    spec = yaml.safe_load((out / "specs" / "probe.yaml").read_text())
    assert spec["campaign_id"] == "probe" and spec["max_cycles"] == 1
    # The override merged INTO the campaign rather than replacing it.
    assert spec["stages"][0] == "mock_rfd3_design" and len(spec["stages"]) == 6
    assert (pathlib.Path(rec["run_dir"]) / "provenance" / "results.jsonl").exists()


def test_the_cell_writes_its_trust_ledger_inside_the_lab(one_cell):
    """Not into `campaigns/_runs/_trust`, which every other campaign on the machine shares.
    A sweep that promoted a pattern there would change the interlock for runs that have
    nothing to do with it, and for cells that run after it in the same sweep."""
    out, _ = one_cell
    assert (out / "trust" / "probe").exists()
    assert (out / "runs" / "probe").exists()


def test_collect_writes_every_table_and_keeps_the_chain_order(one_cell):
    out, _ = one_cell
    tables = collect(out)
    lineages = read_table(tables["lineages"])
    tasks = read_table(tables["tasks"])
    camps = read_table(tables["campaigns"])
    phases = read_table(tables["phases"])

    assert len(lineages) == 1, "one lineage, one cycle"
    # The node row carries the WHOLE chain's metrics merged, which is what makes it the
    # design-level ensemble rather than a per-stage reading.
    for metric in ("ss_fraction", "overall_confidence", "total_score",
                   "shape_complementarity", "complex_plddt", "ligand_iptm"):
        assert lineages[0][metric] is not None, metric

    assert [t["stage_index"] for t in tasks] == [0, 1, 2, 3, 4, 5]
    assert [t["tool"] for t in tasks][0] == "mock_rfd3_design"
    assert [t["tool"] for t in tasks][-1] == "mock_boltz_predict"

    (camp,) = camps
    assert camp["aborted"] is False and camp["cycles"] == 1
    assert camp["tasks"] == 6 and camp["decisions"] == 1
    assert camp["busy_s"] <= camp["wall_s"], "busy time cannot exceed the campaign"
    assert camp["overhead_s"] >= 0.0
    assert len(phases) == 1 and phases[0]["first_cycle"] is True


def test_every_figure_draws_from_a_collected_lab(one_cell):
    """Renders, rather than inspects: layout is a human's job and the skill says to open the
    PNG. What this catches is a figure that only runs against the author's own directory -
    an empty arm, a missing column, a knob with one point."""
    pytest.importorskip("matplotlib")
    from impress_a.analysis.mock_figures import draw_all
    out, _ = one_cell
    collect(out)
    written = draw_all(out)
    assert len(written) == 6
    for path in written:
        assert path.exists() and path.stat().st_size > 1000, path
