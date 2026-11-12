"""The engine's telemetry, on: what a campaign writes when it asks for it.

asyncflow traces every task and block itself once `start_telemetry` is called, so the test is
of the wiring - started at `executor.start`, stopped before the bounded engine teardown - and of
what lands on disk: a checkpoint holding one span per Stage block, with that run's work under it.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("opentelemetry.sdk")

from impress_a.compose.validate import SiteCaps  # noqa: E402
from impress_a.core.pareto import Direction, Objective  # noqa: E402
from impress_a.manager import CampaignManager, CampaignSpec  # noqa: E402
from impress_a.policy.planners import ThresholdPlanner  # noqa: E402
from impress_a.policy.registry import RolePair  # noqa: E402
from impress_a.policy.specifiers import ThresholdSpecifier  # noqa: E402
from impress_a.tools.registry import Registry  # noqa: E402

CHAIN = ["mock_generate", "mock_design", "mock_fold"]


def _spec(tmp_path, every):
    return CampaignSpec(
        campaign_id="t-telemetry", goal="stabilize",
        objectives=[Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
                    Objective(name="iptm", direction=Direction.MAX, min=0.55)],
        budget={"gpu_hours": 2.0, "cpu_hours": 12.0}, max_cycles=2,
        site=SiteCaps(gpu_api="cuda", gpus_per_node=1), backend="concurrent",
        backend_config={"workers": 2}, root=str(tmp_path),
        trust_root=str(tmp_path / "trust"), telemetry_checkpoint_s=every,
        backend_shutdown_timeout_s=60)


async def test_a_campaign_that_asks_for_telemetry_gets_a_span_per_stage(tmp_path):
    """One `block` span per admitted run, every node of that run parented to it and carrying
    the run's label - so a trace answers "what did run r0002 do" without our own bookkeeping."""
    mgr = CampaignManager(_spec(tmp_path, 30),
                          RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=CHAIN)),
                          Registry().load())
    res = await mgr.run()
    assert mgr.executor.telemetry is None, "stopped before the engine went"

    files = sorted((tmp_path / "t-telemetry" / "telemetry").glob("*.jsonl"))
    assert files, "the final checkpoint is written at stop"
    spans = [r for f in files for line in f.read_text().splitlines() if line.strip()
             for r in [json.loads(line)] if "span_id" in r and "event_type" not in r]
    blocks = [sp for sp in spans if sp["name"] == "block"]
    assert len(blocks) == res.cycles, "one Stage block per admitted run"
    for block in blocks:
        members = [sp for sp in spans if sp["name"] == "task"
                   and sp.get("parent_span_id") == block["span_id"]]
        assert len(members) == 2 * len(CHAIN), "both lineages' nodes sit under their block"
        labels = {sp["attributes"]["asyncflow.workflow_id"] for sp in members}
        assert len(labels) == 1 and labels.pop().startswith("r"), "one run label per block"
        assert {sp["attributes"]["backend"] for sp in members} == {"local"}, \
            "adapters run on the local route; a mock tool starts no command"


async def test_telemetry_is_off_unless_asked(tmp_path):
    mgr = CampaignManager(_spec(tmp_path, 0),
                          RolePair(ThresholdSpecifier(), ThresholdPlanner(stages=CHAIN)),
                          Registry().load())
    await mgr.run()
    assert not (tmp_path / "t-telemetry" / "telemetry").exists()
