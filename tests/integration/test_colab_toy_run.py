"""The Colab quickstart against a real engine and asyncflow's own backend.

Needs no rhapsody, so it runs wherever the package's own dependencies are
installed -- the same tier as test_task_defaults_local.py.

What is worth asserting here is what a reader of the notebook is promised: the
same seed gives the same decisions, the threshold changes how many children
appear, the generation cap holds, and a second run in the same kernel works.
That last one is not a nicety: the sweep cell depends on it.

Wall clock is dominated by the manager's adaptive poll rather than by the
tasks, which is why these configurations are two passes deep and sleep for
nothing. Each `run_adaptive_step(wait=True)` costs about a second: the manager
notices the flag on one 0.5s poll and clears the barrier on a later one.
"""

import os
from dataclasses import replace

import pytest

from ..conftest import load_colab_module

toy_science = load_colab_module("toy_science")
impress_toy = load_colab_module("impress_toy")

ToyConfig = toy_science.ToyConfig

pytestmark = pytest.mark.integration


def _cfg(**over):
    """Small enough to be quick, big enough to spawn."""
    base = ToyConfig(
        n_targets=4,
        n_passes=2,
        fragile_fraction=0.5,
        min_degraded_to_spawn=2,
        degradation_threshold=2.0,
        max_generations=1,
        noise_sd=0.0,
        task_duration_s=0.0,
    )
    return replace(base, **over)


async def test_a_run_completes_and_spawns_a_child(tmp_path):
    result = await impress_toy.run_toy(_cfg(), quiet=True, work_dir=tmp_path)

    assert result.spawns == 1
    assert len(result.pipelines) == 2
    assert result.max_generation == 1
    # The child's name is the parent's plus its generation, and the parent
    # handed over exactly the targets it found degraded.
    row = result.genealogy[0]
    assert row["child"].startswith(row["parent"])
    assert row["migrated"]


async def test_scores_come_back_from_the_subprocess(tmp_path):
    """The tasks exec score_stage.py; the numbers are its stdout, parsed.

    With noise_sd at zero the two paths must agree exactly, which is what
    makes this a check on the plumbing rather than on the arithmetic.
    """
    cfg = _cfg()
    result = await impress_toy.run_toy(cfg, quiet=True, work_dir=tmp_path)
    fragile = toy_science.fragile_targets(cfg)

    assert result.scores
    for row in result.scores:
        expected = toy_science.simulate_score(
            target=row["target"],
            pass_index=row["pass"],
            generation=row["generation"],
            migrated=row["generation"] > 0,
            seed=cfg.seed,
            noise_sd=cfg.noise_sd,
            fragile=row["target"] in fragile,
        )
        assert row["score"] == expected


async def test_the_same_seed_gives_the_same_decisions(tmp_path):
    """Decisions, not timings: wall clock jitters between runs."""
    first = await impress_toy.run_toy(_cfg(), quiet=True, work_dir=tmp_path / "a")
    second = await impress_toy.run_toy(_cfg(), quiet=True, work_dir=tmp_path / "b")

    assert first.decisions == second.decisions
    assert first.pipelines == second.pipelines
    assert [r["migrated"] for r in first.genealogy] == [
        r["migrated"] for r in second.genealogy
    ]


async def test_two_runs_in_one_event_loop(tmp_path):
    """The sweep cell runs several configurations back to back in one kernel.

    Each gets its own backend, engine and manager, and the caller shuts the
    engine down; a leak here would surface as a hang rather than a failure.
    """
    first = await impress_toy.run_toy(
        _cfg(seed=1), quiet=True, work_dir=tmp_path / "one"
    )
    second = await impress_toy.run_toy(
        _cfg(seed=2), quiet=True, work_dir=tmp_path / "two"
    )

    assert first.events and second.events
    assert first.makespan > 0 and second.makespan > 0


async def test_a_generation_cap_of_zero_never_spawns(tmp_path):
    """The framework enforces no cap, so the rule has to.

    Without one, `ImpressManager.start()` has no pipeline-free moment to
    return on and the run never ends.
    """
    result = await impress_toy.run_toy(
        _cfg(max_generations=0), quiet=True, work_dir=tmp_path
    )

    assert result.spawns == 0
    assert result.pipelines == ["p1"]
    assert any("generation cap" in reason for _, reason in result.decisions)


async def test_an_unreachable_threshold_never_spawns(tmp_path):
    result = await impress_toy.run_toy(
        _cfg(degradation_threshold=99.0), quiet=True, work_dir=tmp_path
    )

    assert result.spawns == 0
    assert all("no spawn" in reason for _, reason in result.decisions)


async def test_a_low_threshold_spawns_up_to_the_cap(tmp_path):
    """Lowering the threshold is the notebook's headline experiment."""
    result = await impress_toy.run_toy(
        _cfg(degradation_threshold=0.0, max_generations=2, n_passes=3),
        quiet=True,
        work_dir=tmp_path,
    )

    assert result.spawns >= 2
    assert result.max_generation == 2


async def test_the_engine_leaves_nothing_in_the_cwd(tmp_path, monkeypatch):
    """asyncflow creates a session directory under the engine's work_dir.

    Without an explicit one it lands in the process's cwd, which in a notebook
    is whatever the reader happened to be in.
    """
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    await impress_toy.run_toy(_cfg(), quiet=True, work_dir=tmp_path / "work")

    assert os.listdir(elsewhere) == []


async def test_the_live_log_is_printed_from_the_loop(tmp_path, capsys):
    """A non-quiet run streams one line per event while it runs."""
    await impress_toy.run_toy(_cfg(), quiet=False, work_dir=tmp_path)

    printed = capsys.readouterr().out
    assert "pipeline_start" in printed
    assert "structure_prediction" in printed
    assert "adaptive_eval" in printed
