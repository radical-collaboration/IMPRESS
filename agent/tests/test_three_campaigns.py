"""M1's last criterion: three impress-a campaigns, concurrently, on one engine (item 11, EI.15).

**This was deferred to M2 and the deferral was wrong.** The `DEFERRED` entry read "needs the
AuCam workflow body calling the bridge inside a live campaign", and EI.13's own Result said the
same. It does not: the criterion is CON-1's claim — *one engine per campaign host, three
campaigns on it* — and that is checkable with three mock campaign files, an engine built over
impress-a's own routes, and 1.4 seconds. **Third time in this phase that a deferral's stated
reason did not survive being tested**, after ROME's resident-stream reload (item 40) and EI.8's
`AnchorSpec` enum.

**Why three and not two.** Decision L1 split the labels chain, so the production shape is a
design campaign plus *two* label campaigns — and CON-3 sizes the slot ceiling against five
workflow types. Two campaigns would have exercised concurrency; three is the arrangement the
project actually runs, and the one `tests/m1/test_m1.py`'s five-workflow test sizes against.

**The engine is built over `make_routes`, which the refusal taught.** A bare
`WorkflowEngine.create(backend=LocalExecutionBackend(...))` is rejected at start with *"the
engine passed in has backend(s) ['default'] but this campaign routes tasks to ['compute',
'local']"* — `routes_of` checks at start rather than letting asyncflow fail at decoration time
on the first routed task. That refusal is the engine-injection seam (item 4) working, and it is
asserted below so the seam cannot quietly stop checking.

**It must not run on Delta.** The whole value is that it passes with no GPU, no Dragon and no
LLM; running it on the cluster spends allocation and hides the invariant.
"""
from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("impress_a", reason="impress-a is not installed in this environment")
pytest.importorskip("radical.asyncflow", reason="radical.asyncflow is not installed")

from radical.asyncflow import WorkflowEngine  # noqa: E402

from impress_a.cli import build_roles, load_spec  # noqa: E402
from impress_a.exec.backend import make_routes  # noqa: E402
from impress_a.manager import CampaignManager  # noqa: E402
from impress_a.tools.registry import Registry  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: The production shape, which decision L1 made three rather than two: one design campaign and
#: one per label protocol, because `md_label` and `abfe_label` are dispatched at different
#: rates and ask the allocation for different resources.
CAMPAIGNS = (
    "campaigns/asd-smb-mock.yaml",
    "campaigns/asd-labels-md-mock.yaml",
    "campaigns/asd-labels-abfe-mock.yaml",
)


@pytest.fixture(scope="module")
def three():
    """Run all three concurrently on one engine, once, and hand back what happened."""
    return asyncio.run(_run_three())


async def _run_three():
    # RESTORED IN `finally`, and leaving it set was a latent defect found by EI.25.
    # `search_paths()` returns `explicit` AND everything in `$IMPRESS_A_TOOLKITS`, so a later
    # test calling `Registry().load(TOOLKITS)` while this still points at the same directory
    # gets that root twice, and the second pass reports `duplicate tool id` with one line in
    # `reg.errors` and no refusal. CORRECTED 2026-11-21 (H1): this said the duplicate
    # disabled the toolkit entirely; measured, the first pass has already registered those
    # ids and they survive -- the cost is the errors alone, which is enough, because
    # `test_gate6_pair.py`'s fixture asserts `reg.errors == []`. The suite passed only
    # because `test_gate6_pair.py` sorts before `test_three_campaigns.py`.
    cwd = Path.cwd()
    os.chdir(REPO)
    try:
        routes = await make_routes("concurrent", {"workers": 4})
        flow = await WorkflowEngine.create(backend=routes)
        registry = Registry().load()
        managers = []
        for path in CAMPAIGNS:
            spec = load_spec(path)
            managers.append(CampaignManager(spec, build_roles("D", spec, True), registry,
                                            flow=flow))
        results = await asyncio.gather(*(m.run() for m in managers),
                                       return_exceptions=True)
        # Recorded, not swallowed. A shutdown failure must not mask three campaign results,
        # and `except: pass` would make it invisible -- which is the thing this project keeps
        # finding in other people's code. A test below asserts it was None.
        shutdown_error = None
        try:
            await flow.shutdown()
        except Exception as exc:  # noqa: BLE001 -- any shutdown failure is reported, not raised
            shutdown_error = exc
        return {"flow": flow, "managers": managers, "results": results,
                "shutdown_error": shutdown_error}
    finally:
        os.chdir(cwd)


def test_three_campaigns_run_concurrently_under_one_engine(three):
    """CON-1, and the criterion M1 deferred.

    One engine object, three campaigns, every one of them reaching a stop reason of its own.
    A campaign that raised, or that stopped before running a cycle, would not be concurrency —
    it would be three campaigns taking turns to fail.
    """
    raised = [r for r in three["results"] if isinstance(r, BaseException)]
    assert not raised, f"a campaign raised: {raised}"

    engines = {id(m.executor.flow) for m in three["managers"]}
    assert len(engines) == 1, (
        f"{len(engines)} distinct engines: CON-1 is one engine per campaign host, and three "
        "campaigns each building their own is the arrangement it forbids"
    )
    assert len(three["results"]) == 3
    assert all(r.cycles >= 1 for r in three["results"]), (
        "a campaign ran no cycle: "
        f"{[(r.campaign_id, r.cycles, r.stop_reason) for r in three['results']]}"
    )


def test_each_campaign_keeps_its_own_identity_tree_and_ledger(three):
    """Concurrency that shared state would be worse than serial execution.

    Three campaigns on one engine must still be three campaigns: separate ids, separate design
    trees, separate trust ledgers. A shared tree would let a label campaign's nodes reach the
    design campaign's front; a shared ledger would let one campaign's clean runs promote
    another's pattern, which is the cross-campaign evidence leak the ledger's own docstring
    warns about.
    """
    ids = {r.campaign_id for r in three["results"]}
    assert ids == {"asd-smb-mock", "asd-labels-md-mock", "asd-labels-abfe-mock"}
    assert len({id(m.executor.tree) for m in three["managers"]}) == 3
    assert len({id(m.executor.trust) for m in three["managers"]}) == 3


def test_the_design_campaign_satisfied_its_objectives_while_the_others_ran(three):
    """Not merely "did not crash": the design chain still reaches its own stop condition with
    two other campaigns pumping on the same engine."""
    by_id = {r.campaign_id: r for r in three["results"]}
    design = by_id["asd-smb-mock"]
    assert design.stop_reason == "every spec objective satisfied", design.stop_reason
    assert design.front, "the design campaign satisfied its objectives with an empty front"


def test_the_label_campaigns_each_produced_a_node(three):
    """Both label campaigns are capped at one cycle, so "ran" means "produced a node"."""
    by_id = {r.campaign_id: r for r in three["results"]}
    for name in ("asd-labels-md-mock", "asd-labels-abfe-mock"):
        result = by_id[name]
        assert result.tree.nodes, f"{name} ran {result.cycles} cycle(s) and produced no node"


def test_an_engine_without_impress_as_routes_is_refused_at_start():
    """The engine-injection seam (item 4), asserted so it cannot quietly stop checking.

    `routes_of` compares the engine's backends against the routes the campaign needs and
    raises at start. Without it, asyncflow fails at decoration time the first time a task is
    routed to a backend that is not there — which is mid-campaign, after admission, after the
    budget has been committed.
    """
    async def go():
        from radical.asyncflow import LocalExecutionBackend

        cwd = Path.cwd()
        os.chdir(REPO)
        try:
            backend = await LocalExecutionBackend(ThreadPoolExecutor())
            flow = await WorkflowEngine.create(backend=backend)
            spec = load_spec(CAMPAIGNS[0])
            mgr = CampaignManager(spec, build_roles("D", spec, True), Registry().load(),
                                  flow=flow)
            with pytest.raises(RuntimeError, match="routes tasks to"):
                await mgr.run()
            await flow.shutdown()
        finally:
            os.chdir(cwd)

    asyncio.run(go())


def test_the_shared_engine_shuts_down_cleanly_after_three_campaigns(three):
    """Three campaigns releasing one engine is where a shared resource leaks if it is going to.

    Recorded rather than raised during the run, so a shutdown failure cannot mask the three
    campaign results that are the actual subject -- and asserted here, so it cannot be
    swallowed either.
    """
    assert three["shutdown_error"] is None, (
        f"the shared engine failed to shut down after three campaigns: "
        f"{type(three['shutdown_error']).__name__}: {three['shutdown_error']}"
    )


def test_the_whole_thing_needs_no_gpu_no_dragon_and_no_llm(three):
    """Why this belongs in M1 rather than M2, asserted rather than claimed."""
    import sys

    heavy = {"torch", "dragon", "vllm", "transformers"}
    assert {m.split(".")[0] for m in sys.modules} & heavy == set()
