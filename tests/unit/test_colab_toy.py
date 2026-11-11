"""The Colab quickstart's helper, tested without an engine.

Everything here runs against `examples/colab/`, which is not a package and is
not installed. It is loaded by path, mirroring the `sys.path` append the
notebook itself does, rather than through a conftest hook that would reach
every test in the suite.

The run itself is covered in tests/integration/test_colab_toy_run.py; this file
is the arithmetic, the event log and the agreement between the in-process
scoring function and the subprocess that the tasks actually exec.
"""

import concurrent.futures
import subprocess
import sys
from pathlib import Path

import pytest

from ..conftest import COLAB_DIR as _COLAB
from ..conftest import load_colab_module as _load

toy_science = _load("toy_science")
impress_toy = _load("impress_toy")

ToyConfig = toy_science.ToyConfig


# -- configuration ---------------------------------------------------------


def test_defaults_are_a_valid_run():
    cfg = ToyConfig()
    assert cfg.n_targets > 0
    assert cfg.sleep_s == pytest.approx(cfg.task_duration_s * cfg.time_scale)


@pytest.mark.parametrize(
    "field,value",
    [
        ("n_targets", 0),
        ("n_passes", 0),
        ("max_generations", -1),
        ("min_degraded_to_spawn", 0),
        ("fragile_fraction", 1.5),
        ("noise_sd", -1.0),
        ("degradation_threshold", -0.1),
        ("max_workers", 0),
        ("task_duration_s", -0.1),
        ("time_scale", 0.0),
    ],
)
def test_invalid_configuration_is_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        ToyConfig(**{field: value})


def test_max_generations_zero_is_allowed():
    """Zero is the 'never spawn' setting, not an invalid one.

    The notebook offers it as an experiment, so it must construct.
    """
    assert ToyConfig(max_generations=0).max_generations == 0


# -- the scoring model -----------------------------------------------------


def test_fragile_count_is_exact_and_deterministic():
    """Exact, because a run one short of min_degraded_to_spawn never spawns."""
    cfg = ToyConfig(n_targets=6, fragile_fraction=0.5)
    first = toy_science.fragile_targets(cfg)
    assert len(first) == 3
    assert first == toy_science.fragile_targets(cfg)
    assert first <= set(toy_science.target_names(6))


def test_a_different_seed_picks_different_fragile_targets():
    a = toy_science.fragile_targets(ToyConfig(n_targets=8, seed=1))
    b = toy_science.fragile_targets(ToyConfig(n_targets=8, seed=2))
    assert a != b


def _score(**over):
    kwargs = dict(
        target="T1",
        pass_index=0,
        generation=0,
        migrated=False,
        seed=7,
        noise_sd=0.0,
        fragile=False,
    )
    kwargs.update(over)
    return toy_science.simulate_score(**kwargs)


def test_scoring_is_deterministic_across_processes():
    """Seeded from sha256, not hash(), because the tasks are subprocesses.

    `hash()` is salted per interpreter, so a run seeded from it would not
    reproduce between the pipeline and the task it launches.
    """
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from toy_science import simulate_score;"
            "print(simulate_score('T1', 0, 0, False, 7, 0.0, False))",
            str(_COLAB),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert float(out.stdout.strip()) == _score()


def test_fragile_targets_decline_and_sturdy_ones_do_not():
    fragile_drop = _score(fragile=True, pass_index=0) - _score(
        fragile=True, pass_index=1
    )
    sturdy_drop = _score(pass_index=0) - _score(pass_index=1)
    assert fragile_drop == pytest.approx(-toy_science.FRAGILE_DRIFT)
    assert sturdy_drop < 0


def test_a_migrated_target_declines_more_slowly_than_a_fragile_one():
    """A child buys time; it does not repair the target."""
    migrated = _score(fragile=True, migrated=True, pass_index=1)
    left_alone = _score(fragile=True, pass_index=1)
    assert migrated > left_alone


def test_scores_stay_in_range():
    extreme = toy_science.simulate_score("T1", 99, 0, False, 7, 0.0, True)
    assert toy_science.SCORE_FLOOR <= extreme <= toy_science.SCORE_CEILING


# -- the adaptive rule -----------------------------------------------------


def test_degradation_is_strictly_greater_than_the_threshold():
    """A target that held its score exactly is not degraded at threshold 0."""
    assert not toy_science.is_degraded(50.0, 50.0, 0.0)
    assert toy_science.is_degraded(49.9, 50.0, 0.0)
    assert not toy_science.is_degraded(46.0, 50.0, 4.0)
    assert toy_science.is_degraded(45.9, 50.0, 4.0)


def test_verdicts_skip_targets_with_nothing_to_compare_against():
    out = toy_science.verdicts({"T1": 50.0, "T2": 50.0}, {"T1": 60.0}, 4.0)
    assert [v.target for v in out] == ["T1"]
    assert out[0].degraded
    assert out[0].drop == pytest.approx(10.0)


def test_the_cap_is_what_stops_recursion():
    """The framework enforces no cap; if the rule does not, start() hangs."""
    cfg = ToyConfig(max_generations=1, min_degraded_to_spawn=1)
    current, previous = {"T1": 40.0}, {"T1": 60.0}
    assert toy_science.decide(current, previous, 0, cfg).spawn
    at_cap = toy_science.decide(current, previous, 1, cfg)
    assert not at_cap.spawn
    assert "generation cap" in at_cap.reason


def test_too_few_degraded_declines_and_says_so():
    cfg = ToyConfig(min_degraded_to_spawn=2, max_generations=3)
    decision = toy_science.decide({"T1": 40.0}, {"T1": 60.0}, 0, cfg)
    assert not decision.spawn
    assert "1 degraded" in decision.reason
    assert decision.degraded == ("T1",)


def test_a_spawn_names_the_targets_that_caused_it():
    cfg = ToyConfig(min_degraded_to_spawn=2, max_generations=3)
    decision = toy_science.decide(
        {"T1": 40.0, "T2": 40.0, "T3": 59.0},
        {"T1": 60.0, "T2": 60.0, "T3": 60.0},
        0,
        cfg,
    )
    assert decision.spawn
    assert decision.degraded == ("T1", "T2")


# -- the score_stage subprocess --------------------------------------------


def test_the_task_subprocess_agrees_with_the_scoring_function():
    """The tasks exec this script, so the two must not drift apart."""
    out = subprocess.run(
        [
            sys.executable,
            str(_COLAB / "score_stage.py"),
            "T3",
            "2",
            "0",
            "0",
            "7",
            "0.0",
            "1",
            "0",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = toy_science.simulate_score("T3", 2, 0, False, 7, 0.0, True)
    assert float(out.stdout.strip()) == expected


def test_the_task_subprocess_rejects_a_wrong_argument_count():
    out = subprocess.run(
        [sys.executable, str(_COLAB / "score_stage.py"), "T1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 2
    assert "usage" in out.stderr


# -- the event recorder ----------------------------------------------------


def test_an_unknown_event_kind_is_a_bug_not_a_passthrough():
    with pytest.raises(ValueError, match="unknown event kind"):
        impress_toy.EventRecorder(quiet=True).emit("nonsense")


def test_every_thread_s_events_arrive():
    """The adaptive callback runs on a thread pool, not on the loop.

    Measured: it lands on `ThreadPoolExecutor-0_0`. An unsynchronised list
    would drop appends under that.
    """
    rec = impress_toy.EventRecorder(quiet=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda i: rec.emit("adaptive_eval", pipeline=f"p{i}"),
                range(400),
            )
        )
    assert len(rec.events) == 400
    assert len({e["pipeline"] for e in rec.events}) == 400


def test_draining_empties_the_queue_but_keeps_the_log():
    rec = impress_toy.EventRecorder(quiet=True)
    rec.emit("run_start")
    assert len(rec.drain()) == 1
    assert rec.drain() == []
    assert len(rec.events) == 1


def test_events_hands_back_copies():
    rec = impress_toy.EventRecorder(quiet=True)
    rec.emit("run_start")
    rec.events[0]["kind"] = "tampered"
    assert rec.events[0]["kind"] == "run_start"


def test_a_formatted_line_carries_name_generation_and_reason():
    line = impress_toy.format_event(
        {
            "t": 3.25,
            "kind": "adaptive_eval",
            "pipeline": "p1.g1",
            "generation": 1,
            "task": "",
            "targets": ["T1"],
            "detail": {"reason": "spawn: 2 degraded"},
        }
    )
    # The name already carries lineage, so the generation is its own column
    # rather than a suffix -- otherwise this reads "p1.g1.g1".
    assert "p1.g1" in line and line.count(".g1") == 1
    assert "g1" in line
    assert "spawn: 2 degraded" in line


# -- deriving the tables ---------------------------------------------------


def _ev(kind, t, *, pipeline="p1", generation=0, task="", targets=(), detail=None):
    """One event in the recorder's schema, without the ceremony."""
    return {
        "t": t,
        "kind": kind,
        "pipeline": pipeline,
        "generation": generation,
        "task": task,
        "targets": list(targets),
        "detail": dict(detail or {}),
    }


def _run_result(events):
    return impress_toy.RunResult(cfg=ToyConfig(), events=events, work_dir=Path("."))


PREDICT = "structure_prediction"


def test_scores_and_genealogy_are_derived_from_the_event_log():
    result = _run_result(
        [
            _ev("pipeline_start", 0.0, targets=["T1"]),
            _ev(
                "task_end",
                0.2,
                task=PREDICT,
                targets=["T1"],
                detail={"pass": 0, "score": 70.0},
            ),
            _ev("task_end", 0.3, task="score_extraction", detail={"mean": 70.0}),
            _ev(
                "spawn",
                1.5,
                targets=["T1"],
                detail={"child": "p1.g1", "reason": "spawn: 1 degraded"},
            ),
        ]
    )
    # score_extraction reports a mean, not a per-target score, so it is not a
    # row in the score table.
    assert result.scores == [
        {
            "pipeline": "p1",
            "generation": 0,
            "target": "T1",
            "pass": 0,
            "score": 70.0,
            "t": 0.2,
        }
    ]
    assert result.genealogy == [
        {
            "parent": "p1",
            "child": "p1.g1",
            "generation": 1,
            "migrated": ["T1"],
            "t": 1.5,
        }
    ]
    assert result.spawns == 1
    assert result.pipelines == ["p1"]
    assert result.makespan == pytest.approx(1.5)


def test_decisions_ignore_wall_clock():
    """What a determinism check should compare: times jitter, verdicts do not."""
    detail = {"reason": "no spawn: 0 degraded"}
    early = [_ev("adaptive_eval", 1.0, detail=detail)]
    late = [_ev("adaptive_eval", 1.9, detail=detail)]
    assert _run_result(early).decisions == _run_result(late).decisions


def test_task_spans_pair_starts_with_ends():
    toy_figures = _load("toy_figures")
    result = _run_result(
        [
            _ev("task_start", 0.0, task=PREDICT, targets=["T1"], detail={"pass": 0}),
            _ev(
                "task_end",
                0.2,
                task=PREDICT,
                targets=["T1"],
                detail={"pass": 0, "score": 70.0},
            ),
            # A start with no end -- a cancelled task -- is dropped, not paired
            # with the next unrelated end.
            _ev("task_start", 0.3, task=PREDICT, targets=["T2"], detail={"pass": 0}),
        ]
    )
    spans = toy_figures.task_spans(result)
    assert len(spans) == 1
    assert spans[0]["targets"] == ["T1"]
    assert spans[0]["t1"] - spans[0]["t0"] == pytest.approx(0.2)
