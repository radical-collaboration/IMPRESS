"""The scoring harness, checked before it scores a real run.

Every figure a comparison publishes is exactly the code that must not be wrong, and the
sibling example's harness is the evidence: two of its bugs flattered multi-node arms and
neither was visible in the output. Both are regression tests here.

The fixtures are a synthetic run directory per arm, built from the same provenance shapes the
executor writes, with every published figure asserted against a hand-computed value.
"""
from __future__ import annotations

import json
import math

import pytest

from impress_a.analysis.compare_arms import (
    compare,
    load_arm,
    mde,
    one_variable_guard,
    score,
)
from impress_a.analysis.tiers import (
    Design,
    cluster,
    holm,
    identity,
    rate_ratio,
    tier_of,
)

CHAIN = ("rfd3_design", "ligandmpnn_design", "packmin", "fastrelax", "filter_shape",
         "boltz_predict")

#: A design that clears every T2 and T3 threshold. Each test perturbs one number.
PASSING = {"ss_fraction": 0.84, "total_score": -318.2, "fa_rep": 92.0,
           "interaction_energy": -14.6, "shape_complementarity": 0.67,
           "complex_plddt": 0.82, "ligand_iptm": 0.61}

#: Job 22692304's real metrics - this project's best run, `6/6 tasks ok`, admitted first
#: attempt with every stage passing its gates. It must land T1 and NOT T2: `fa_rep` 109.4
#: against 100, and `interaction_energy` was never computed at all.
JOB_22692304 = {"ss_fraction": 0.84, "total_score": -272.0, "fa_rep": 109.4,
                "shape_complementarity": 0.591, "complex_plddt": 0.507,
                "ligand_iptm": 0.752}


def _task(run, lineage, tool, metrics=None, qc="pass", started=0.0, finished=1.0,
          cost=None, measured=None, failed_gates=()):
    """One `tasks` provenance line, in the shape `_log_task_telemetry` writes."""
    from datetime import datetime, timezone

    def stamp(offset):
        return datetime.fromtimestamp(1_800_000_000 + offset, timezone.utc).isoformat()

    return {"run": run, "cycle": int(run[1:]), "task": f"{run}_{lineage}_{tool}",
            "tool": tool, "lineage": lineage, "metrics": metrics or {}, "qc": qc,
            "failed_gates": list(failed_gates),
            "cost_estimated": cost or {}, "cost_measured": measured or {},
            "started_at": stamp(started), "finished_at": stamp(finished),
            "wall_s": finished - started, "phases": {"run": finished - started}}


def _arm(tmp_path, name, *, designs, nodes=1, elapsed_h=4.0, gpus=4, model="D",
         git_sha="abc123", seed_salt="exp-1", campaign_path="campaigns/arms.yaml",
         prereg_sha="pre1", transitions=(), extra_tasks=(), sacct=True, sequences=None):
    """A synthetic arm directory. `designs` is `{(run, lineage): metrics}`."""
    root = tmp_path / name
    (root / "provenance").mkdir(parents=True)
    (root / "jobs").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "model": model, "nodes": nodes, "gpus_per_node": gpus, "git_sha": git_sha,
        "git_dirty": False, "seed_salt": seed_salt, "campaign_path": campaign_path,
        "prereg_sha": prereg_sha}))
    if sacct:
        (root / "sacct.json").write_text(json.dumps({
            "jobs": [{"allocation_nodes": nodes,
                      "time": {"elapsed": int(elapsed_h * 3600)}}]}))

    rows, ledger = [], []
    for i, ((run, lineage), metrics) in enumerate(sorted(designs.items())):
        for tool in CHAIN:
            rows.append(_task(run, lineage, tool,
                              metrics=metrics if tool == "boltz_predict" else {},
                              started=float(i * 100), finished=float(i * 100 + 60),
                              cost={"gpu_hours": 0.1}, measured={"gpu_hours": 0.03}))
        if sequences and (run, lineage) in sequences:
            fa = root / f"{run}_{lineage}.fa"
            fa.write_text(f">cand, overall_confidence=0.5\n{sequences[(run, lineage)]}\n")
            ledger.append({"job_id": run, "outcome": {
                "run_id": run,
                "tasks": [{"task_id": f"{run}_{lineage}_ligandmpnn_design",
                           "outputs": {"sequences": {"path": str(fa)}}}]}})
    rows.extend(extra_tasks)
    (root / "provenance" / "tasks.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    (root / "provenance" / "transitions.jsonl").write_text(
        "".join(json.dumps(t) + "\n" for t in transitions))
    (root / "jobs" / "ledger.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in ledger))
    return root


# ---------------------------------------------------------------------------
# 1. Every figure against a hand-computed value.
# ---------------------------------------------------------------------------

def test_every_published_figure_matches_a_hand_computed_value(tmp_path):
    """The whole harness on one arm, with each number worked out by hand in the comments."""
    designs = {("r0001", 0): PASSING, ("r0001", 1): PASSING,
               ("r0002", 0): JOB_22692304}
    root = _arm(tmp_path, "D", designs=designs, nodes=1, elapsed_h=4.0, gpus=4,
                sequences={("r0001", 0): "AAAA", ("r0001", 1): "CCCC",
                           ("r0002", 0): "GGGG"})
    f = score(load_arm(root), CHAIN)

    assert f.draws == 3, "three (run, lineage) pairs"
    assert f.t1 == 2, "22692304 never computed interaction_energy, so it is not even T1"
    assert f.exact_sequences == 2, (
        "AAAA and CCCC - the exact count is over the SAME population as the cluster count, "
        "which is what makes it the upper bound of that count. GGGG belongs to the design "
        "that is not even T1, and including it would make the two figures incomparable")
    assert f.t2 == 2 and f.t3 == 2, "the two passing designs clear both tiers"
    assert f.distinct_t2 == 2, "AAAA and CCCC are 0% identical, so two clusters"
    assert f.gpu_hours == 16.0, "1 node x 4 GPUs x 4 h, charging the whole node"
    assert f.gpu_hours_per_t2 == 8.0, "16 GPU-h / 2 distinct designs"
    assert f.t2_per_node_hour == 0.5, "2 designs / (1 node x 4 h)"
    assert f.cost_ratio["boltz_predict.gpu_hours"] == 0.3, "0.03 measured / 0.10 declared"
    assert f.mpnn_per_fold == 1.0, "one MPNN task per fold: no screening, which is the finding"
    assert f.mock_tasks == 0 and f.degraded_events == 0 and f.publishable


# ---------------------------------------------------------------------------
# 2 and 3. The sibling harness's two bugs, as regressions.
# ---------------------------------------------------------------------------

def test_an_arm_is_charged_for_every_node_it_held(tmp_path):
    """The sibling charged every arm for one node, understating a 2-node arm's cost by 2x.

    Always charge the model's node to the experiment. Two arms with IDENTICAL output, one on
    one node and one on two, must differ by exactly 2x in cost per design - and the two-node
    arm must look WORSE, which is the direction the bug reversed.
    """
    designs = {("r0001", 0): PASSING, ("r0001", 1): PASSING}
    seqs = {("r0001", 0): "AAAA", ("r0001", 1): "CCCC"}
    one = score(load_arm(_arm(tmp_path, "one", designs=designs, nodes=1, sequences=seqs)),
                CHAIN)
    two = score(load_arm(_arm(tmp_path, "two", designs=designs, nodes=2, sequences=seqs)),
                CHAIN)

    assert one.distinct_t2 == two.distinct_t2 == 2, "identical science"
    assert two.gpu_hours == 2 * one.gpu_hours
    assert two.gpu_hours_per_t2 == 2 * one.gpu_hours_per_t2, \
        "the arm that used twice the hardware for the same output must read twice the cost"
    assert two.t2_per_node_hour == one.t2_per_node_hour / 2


def test_a_tool_count_is_not_divided_by_a_hardcoded_pipeline_count(tmp_path):
    """The sibling divided rfd3 tasks by a hardcoded 4, reading 126.2/pipeline-h for 15.8.

    Seven rfd3 tasks is seven. Any per-pipeline figure has to come from the run's own width.
    """
    rows = [_task("r0001", i % 2, "rfd3_design") for i in range(7)]
    rows += [_task("r0001", 0, "boltz_predict", metrics=PASSING)]
    root = _arm(tmp_path, "arm", designs={}, extra_tasks=rows)
    arm = load_arm(root)

    rfd3 = sum(1 for r in arm.tasks if r.get("tool") == "rfd3_design")
    assert rfd3 == 7, f"seven tasks must read as seven, got {rfd3}"
    assert score(arm, CHAIN).mpnn_per_fold == 0.0, "no MPNN tasks, one fold: 0.0, not 1/4"


# ---------------------------------------------------------------------------
# 4. Distinctness.
# ---------------------------------------------------------------------------

def test_distinctness_depends_on_theta_and_merges_structurally():
    """G7 measured the over-count this exists to remove: ~3x, from same-seed re-draws.

    At 0.90 two designs differing in one residue of ten are one cluster; at 0.99 they are two.
    And the structural merge collapses a pair the identity test kept apart, which is what
    makes draw-collapse visible rather than counted as yield.
    """
    a = Design(run="r1", lineage=0, sequence="AAAAAAAAAA")
    b = Design(run="r1", lineage=1, sequence="AAAAAAAAAC")      # 90% identical
    assert identity(a.sequence, b.sequence) == 0.9

    assert cluster([a, b], theta=0.90).distinct == 1
    assert cluster([a, b], theta=0.99).distinct == 2

    # Single linkage: a chain of near-identical designs merges even where no single pair
    # would reach the threshold against the first.
    c = Design(run="r1", lineage=2, sequence="AAAAAAAACC")
    assert cluster([a, b, c], theta=0.90).distinct == 1

    # Structural: two unrelated sequences that folded to the same backbone.
    same = [(float(i), 0.0, 0.0) for i in range(8)]
    x = Design(run="r1", lineage=0, sequence="AAAAAAAA", ca=same)
    y = Design(run="r1", lineage=1, sequence="CCCCCCCC", ca=same)
    merged = cluster([x, y], theta=0.99)
    assert merged.distinct == 1, "identical structures are one design"
    assert "ca_rmsd" in merged.criterion, \
        "the criterion must say it merged on RMSD, not on TM - they are not the same measure"
    assert cluster([x, y], theta=0.99, structural=lambda p, q: False).distinct == 2


# ---------------------------------------------------------------------------
# 5. Tier assignment against the project's own best run.
# ---------------------------------------------------------------------------

def test_job_22692304_lands_t1_and_not_t2():
    """This project's best run - `6/6 tasks ok`, every stage passing its gates - is T1.

    `fa_rep` 109.4 against upstream's 100, `complex_plddt` 0.507 against 0.75, and
    `interaction_energy` never computed at all. A harness that scored it T2 would be measuring
    this project's own gates rather than the thresholds the comparison is judged on.
    """
    design = Design(run="r0001", lineage=0, metrics=dict(JOB_22692304), tools=CHAIN)
    assert tier_of(design, CHAIN) == 0, (
        "NOT EVEN T1: `interaction_energy` was computed by nothing, and T1 is 'every tool "
        "ran, no integrity gate failed, every declared metric reported'. Scoring it T1 would "
        "report the chain as plumbed while the metric that measures binding was absent")

    with_energy = Design(run="r0001", lineage=0, tools=CHAIN,
                         metrics={**JOB_22692304, "interaction_energy": -9.0})
    assert tier_of(with_energy, CHAIN) == 1, "T1 now, and fa_rep 109.4 still fails T2"

    fixed = Design(run="r0001", lineage=0, tools=CHAIN,
                   metrics={**JOB_22692304, "interaction_energy": -9.0, "fa_rep": 92.0})
    assert tier_of(fixed, CHAIN) == 2, "T2 now, and T3 needs the fold"
    assert tier_of(Design(run="r", lineage=0, tools=CHAIN, metrics=PASSING), CHAIN) == 3


def test_a_truncated_lineage_cannot_reach_t1(tmp_path):
    """T1 is "every tool ran". A lineage that ran three stages cleanly has not passed T1.

    Job 22675512 is the case: a budget correction truncated the chain, and the three stages
    that did run passed every gate they had.
    """
    short = Design(run="r0001", lineage=0, metrics=PASSING, tools=CHAIN[:3])
    assert tier_of(short, CHAIN) == 0
    assert tier_of(Design(run="r", lineage=0, metrics=PASSING, tools=CHAIN), CHAIN) == 3


# ---------------------------------------------------------------------------
# 6. Censoring.
# ---------------------------------------------------------------------------

def test_time_to_the_tenth_design_is_censored_not_nulled(tmp_path):
    """"No tenth design" and "the tenth arrived instantly" are opposite findings.

    A null or a zero would be read as either, and the pre-registration says the figure is
    reported as `> 3.25 h (censored)`.
    """
    few = {("r0001", i): PASSING for i in range(3)}
    f = score(load_arm(_arm(tmp_path, "few", designs=few,
                            sequences={k: f"{'ACGT'[i % 4] * 8}" for i, k in
                                       enumerate(sorted(few))})), CHAIN)
    assert f.time_to_tenth_h is None
    assert f.censored_at_h == pytest.approx(3.25)

    many = {("r0001", i): PASSING for i in range(12)}
    arm = load_arm(_arm(tmp_path, "many", designs=many,
                        sequences={k: f"{chr(65 + i) * 8}" for i, k in
                                   enumerate(sorted(many))}))
    g = score(arm, CHAIN)
    assert g.distinct_t2 == 12
    assert g.time_to_tenth_h is not None and g.censored_at_h is None


# ---------------------------------------------------------------------------
# 7 and 8. What the harness refuses to publish.
# ---------------------------------------------------------------------------

def test_a_mock_task_stops_the_arm_being_published(tmp_path):
    """A mock chain completes `6/6 tasks ok` with plausible metrics and invented designs.

    `mock_noodle` goes further: it reports a confident `designability` for a structure with no
    secondary structure. So a mock arm does not merely fail to inform - it produces numbers a
    reader would act on, and the harness must not print them as a yield.
    """
    rows = [_task("r0001", 0, "mock_generate", metrics={"designability": 0.9})]
    f = score(load_arm(_arm(tmp_path, "mocky", designs={("r0001", 0): PASSING},
                            extra_tasks=rows)), CHAIN)
    assert f.mock_tasks == 1
    assert not f.publishable
    assert any("MOCK" in n for n in f.notes)


def test_a_degraded_decision_voids_the_arm(tmp_path):
    """A fallen-back arm is byte-for-byte a model-D campaign, and invisible in the log.

    Every degraded path writes one of three events, named the same way on purpose so that one
    query finds them all whatever model made the decision.
    """
    for event in ("oracle_degraded", "reasoner_degraded", "caller_timeout"):
        f = score(load_arm(_arm(tmp_path, f"arm_{event}",
                                designs={("r0001", 0): PASSING},
                                transitions=[{"event": event}])), CHAIN)
        assert f.degraded_events == 1, event
        assert not f.publishable, event
        assert any("degraded" in n for n in f.notes), event


# ---------------------------------------------------------------------------
# 9. A missing input is reported as missing.
# ---------------------------------------------------------------------------

def test_an_unavailable_sacct_is_reported_rather_than_divided_by(tmp_path):
    """The sibling printed "at most nan% of the billed GPU time had a GPU task running".

    It had no `sacct`, divided anyway, and published a `nan` as a finding. A figure that
    depends on an input nobody has is not reported at all, and the note says why.
    """
    f = score(load_arm(_arm(tmp_path, "nosacct", designs={("r0001", 0): PASSING},
                            sacct=False)), CHAIN)
    assert f.gpu_hours is None
    assert f.gpu_hours_per_t2 is None and f.t2_per_node_hour is None
    assert any("allocation unknown" in n for n in f.notes)
    assert not any(isinstance(v, float) and math.isnan(v)
                   for v in (f.gpu_hours, f.gpu_hours_per_t2, f.t2_per_node_hour)
                   if v is not None)


# ---------------------------------------------------------------------------
# 10. The one-variable guard.
# ---------------------------------------------------------------------------

def test_the_comparison_is_refused_when_the_arms_are_not_comparable(tmp_path):
    """Every one of these is held identical by design, so a difference is not a caveat.

    It means the figures measure two things at once - the reasoner and something else - and
    the exit code is what stops a script publishing them anyway.
    """
    designs = {("r0001", 0): PASSING}
    seqs = {("r0001", 0): "AAAA"}
    base = load_arm(_arm(tmp_path, "d", designs=designs, model="D", sequences=seqs))

    for field_, value in (("git_sha", "deadbeef"), ("seed_salt", "other"),
                          ("campaign_path", "campaigns/other.yaml"),
                          ("prereg_sha", "pre2")):
        other = load_arm(_arm(tmp_path, f"a_{field_}", designs=designs, model="A",
                              sequences=seqs, **{field_: value}))
        blocked = one_variable_guard([base, other])
        assert blocked and field_.split("_")[0] in " ".join(blocked).lower(), field_
        assert not compare([base, other], CHAIN).publishable

    clean = load_arm(_arm(tmp_path, "a_ok", designs=designs, model="A", sequences=seqs))
    assert one_variable_guard([base, clean]) == []
    assert compare([base, clean], CHAIN).publishable


def test_a_comparison_without_the_control_is_refused(tmp_path):
    """The control is what every other arm's cost is justified against.

    Three arms and no baseline is three numbers with nothing to compare them to, and A/B/C are
    all more expensive than D by construction.
    """
    designs = {("r0001", 0): PASSING}
    a = load_arm(_arm(tmp_path, "a", designs=designs, model="A",
                      sequences={("r0001", 0): "AAAA"}))
    result = compare([a], CHAIN)
    assert not result.publishable
    assert any("control" in r for r in result.blocked)


# ---------------------------------------------------------------------------
# 11. Robustness and reproducibility.
# ---------------------------------------------------------------------------

def test_a_truncated_ledger_is_survived_and_rescoring_is_byte_identical(tmp_path):
    """A campaign killed by a wall clock leaves a half-written line.

    A harness that raised on it could not score the run that most needs scoring - and a
    rescoring must reproduce the first one exactly, or no published figure can be checked.
    """
    root = _arm(tmp_path, "trunc", designs={("r0001", 0): PASSING, ("r0001", 1): PASSING},
                sequences={("r0001", 0): "AAAA", ("r0001", 1): "CCCC"})
    tasks = root / "provenance" / "tasks.jsonl"
    tasks.write_text(tasks.read_text() + '{"run": "r0002", "tool": "rfd3_desi')

    first = score(load_arm(root), CHAIN)
    second = score(load_arm(root), CHAIN)
    assert first.draws == 2, "the truncated record is skipped, not guessed at"
    assert first == second, "rescoring must be byte-identical"


def test_an_arm_directory_with_nothing_in_it_scores_zero_rather_than_raising(tmp_path):
    """A job that died before writing provenance still has to be reportable."""
    empty = tmp_path / "empty"
    (empty / "provenance").mkdir(parents=True)
    f = score(load_arm(empty), CHAIN)
    assert f.draws == 0 and f.t2 == 0 and f.gpu_hours is None
    assert f.publishable, "nothing ran, which is not the same as something being wrong"


# ---------------------------------------------------------------------------
# 12. The contrast, against hand-computed tables.
# ---------------------------------------------------------------------------

def test_the_poisson_contrast_and_holm_adjustment_are_hand_checkable():
    """No scipy, so the arithmetic is three lines and can be verified on paper.

    10 against 5 over equal exposure: RR = 2.0, se = sqrt(1/10 + 1/5) = 0.5477,
    CI = exp(ln2 +- 1.96 x 0.5477) = (0.684, 5.851), p = 2 x Phi(-1.2656) = 0.2057.
    Holm over three contrasts multiplies the smallest p by 3: 0.617.
    """
    r = rate_ratio("A", 10, 4.0, 5, 4.0)
    assert r.ratio == pytest.approx(2.0)
    assert r.low == pytest.approx(0.6836, abs=1e-3)
    assert r.high == pytest.approx(5.8513, abs=1e-3)
    assert r.p == pytest.approx(0.2057, abs=1e-3)

    adjusted = holm([rate_ratio("A", 10, 4, 5, 4), rate_ratio("B", 6, 4, 5, 4),
                     rate_ratio("C", 5, 4, 5, 4)])
    by_arm = {x.arm: x for x in adjusted}
    assert by_arm["A"].p_holm == pytest.approx(3 * by_arm["A"].p, abs=1e-6)
    assert by_arm["B"].p_holm >= by_arm["A"].p_holm, "Holm's values must be monotone"
    assert by_arm["C"].p_holm == pytest.approx(1.0)


def test_the_decision_rule_needs_the_interval_and_not_just_the_point_estimate():
    """An arm wins iff the Holm-adjusted interval is entirely above 1.3 AND the point
    estimate is at least 1.5. Stated once, applied in one place.

    A point estimate of 3.0 whose interval reaches below 1.3 is what this experiment produces
    at its own counts, and calling that a win is the mistake the pre-registration exists to
    prevent.
    """
    small = rate_ratio("A", 6, 4.0, 2, 4.0)
    assert small.ratio == pytest.approx(3.0)
    assert small.low < 1.3 and not holm([small])[0].wins

    large = rate_ratio("A", 120, 4.0, 40, 4.0)
    assert large.ratio == pytest.approx(3.0)
    assert large.low > 1.3 and holm([large])[0].wins


def test_the_smallest_detectable_difference_is_reported(tmp_path):
    """The design's own analysis says this must be stated, so the harness states it.

    At an expected `C_T2` near 14 the interval spans roughly x/÷ 2.0, so only a >= 2.2x
    difference is detectable here - which is why the honest claim is the interval rather than
    the p-value.
    """
    assert mde([14, 14]) == pytest.approx(2.098, abs=1e-3)
    assert mde([0, 0]) is None, "no counts, no detectable difference"
    assert mde([100, 100]) < mde([14, 14]), "more counts, a smaller detectable difference"


def test_the_report_names_every_arm_and_marks_the_censored_figures(tmp_path):
    """The table is what gets read, so it has to carry the caveats rather than the JSON."""
    designs = {("r0001", 0): PASSING}
    seqs = {("r0001", 0): "AAAA"}
    arms = [load_arm(_arm(tmp_path, "d", designs=designs, model="D", sequences=seqs)),
            load_arm(_arm(tmp_path, "a", designs=designs, model="A", sequences=seqs))]
    text = compare(arms, CHAIN).report()

    assert "cens" in text, "an unreached tenth design must be marked censored in the table"
    assert "rate ratio" in text
    for arm in ("d", "a"):
        assert arm in text
