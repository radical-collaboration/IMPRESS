"""T2 - mock campaign. A complete campaign end to end on a laptop.

Real manager, real policy, real composer, real validator, real state and provenance,
with ConcurrentExecutionBackend and mock tools. Exercises every layer above the substrate.
"""
import asyncio

import pytest

from impress_a.compose.interlock import Scrutiny
from impress_a.compose.validate import SiteCaps
from impress_a.core.artifacts import (AUTHORITY_ASSAY, Property, PropertySource,
                                      SourceKind)
from impress_a.core.decision import ExperimentIntent
from impress_a.core.pareto import Direction, Objective
from impress_a.core.qc import QCVerdict
from impress_a.core.tree import DesignNode
from impress_a.core.types import ArtifactType
from impress_a.core.session import CampaignStopped, SubmissionRejected
from impress_a.control.plane import InProcessControlPlane
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.agentic import FourNodePolicy
from impress_a.policy.explicit import ReplayPolicy, ThresholdPolicy
from impress_a.policy.external import ExternalPolicy
from impress_a.policy.oracle import OraclePolicy
from impress_a.policy.wrappers import NullPolicy, RuleCorrectionsPolicy
from impress_a.tools.registry import Registry

ROOT = "/tmp/impress_a_tests"   # campaign root, and where direct engines put their sessions
CHAIN = ["mock_generate", "mock_design", "mock_fold", "mock_score"]
OBJS = [Objective(name="sc_rmsd", direction=Direction.MIN, max=3.0),
        Objective(name="iptm", direction=Direction.MAX, min=0.55),
        Objective(name="ddg", direction=Direction.MIN)]


def spec(cid, **kw):
    return CampaignSpec(campaign_id=cid, goal="stabilize", objectives=OBJS,
                        budget={"gpu_hours": 2.0, "cpu_hours": 12.0},
                        max_cycles=kw.pop("max_cycles", 4),
                        site=SiteCaps(gpu_api="cuda", gpus_per_node=1),
                        backend="concurrent", backend_config={"workers": 2},
                        root=ROOT, **kw)


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


@pytest.mark.parametrize("make,name", [
    (lambda: ThresholdPolicy(), "D"),
    (lambda: OraclePolicy(fallback=ThresholdPolicy()), "B"),
    (lambda: FourNodePolicy(), "A"),
])
async def test_autonomous_models_reach_termination(reg, make, name):
    mgr = CampaignManager(spec(f"t-{name}"), make(), reg)
    res = await mgr.run()
    assert res.stop_reason, "must terminate with a stated reason"
    assert len(res.tree) > 0, f"{name} produced no candidates"
    assert res.cycles <= 4


async def test_null_policy_stops_immediately(reg):
    res = await CampaignManager(spec("t-null"), NullPolicy(), reg).run()
    assert res.cycles == 0 and len(res.tree) == 0


async def test_a_campaign_writes_nothing_into_the_cwd(reg, tmp_path, monkeypatch):
    """asyncflow puts its session dir in the CWD unless told otherwise. That is how 516
    empty `asyncflow.session.*` dirs piled up in the checkout, and on Delta it scattered
    them beside, rather than inside, each campaign's own output."""
    cwd, root = tmp_path / "cwd", tmp_path / "root"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    s = spec("t-cwd", max_cycles=1)
    s.root = str(root)
    await CampaignManager(s, ThresholdPolicy(), reg).run()
    assert not list(cwd.iterdir()), f"left in the CWD: {sorted(cwd.iterdir())}"
    assert list((root / "t-cwd").glob("asyncflow.session.*"))


async def test_lying_tool_is_caught_by_qc(reg):
    """mock_noodle completes successfully and reports confident `designability`
    while producing no secondary structure. Only the QC gate catches it - the
    Part A failure mode, manufactured on purpose."""
    from impress_a.compose.composer import Composer
    from impress_a.exec.backend import make_engine
    from impress_a.exec.dispatch import Dispatcher

    g = Composer(reg).compose(ExperimentIntent(goal="g", stages=["mock_noodle"]))
    flow, _ = await make_engine("concurrent", {"workers": 1}, work_dir=ROOT)
    try:
        res = await Dispatcher(flow, reg).run(g)
    finally:
        await flow.shutdown()
    assert not res.failures, "the tool must SUCCEED - that is what makes it silent"
    assert res.merged_metrics()["designability"] > 0.9, "and report confident numbers"
    assert res.merged_qc().verdict is QCVerdict.FAIL, "QC must catch it anyway"


async def test_guard_corrects_every_decision(reg):
    guarded = RuleCorrectionsPolicy(ThresholdPolicy(base_replicas=99),
                                    max_replicas=2, forbid_tools=("mock_noodle",))
    res = await CampaignManager(spec("t-guard"), guarded, reg).run()
    assert guarded.corrections, "guard must have corrected an over-large request"


async def test_provisional_results_are_marked_suspect(reg):
    """A novel composition pattern runs, but nothing unreviewed is quietly believed."""
    s = spec("t-suspect", max_cycles=1)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    mgr.trust.patterns.clear()
    res = await mgr.run()
    nodes = [n for n in res.tree if n.qc.verdict is not QCVerdict.FAIL]
    assert nodes and all(n.qc.verdict is QCVerdict.SUSPECT for n in nodes)


async def test_external_steering_and_post_termination_measurement(reg):
    pol = ExternalPolicy(timeout_s=8.0, on_timeout="stop")
    mgr = CampaignManager(spec("t-C", max_cycles=2), pol, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async def caller():
        for _ in range(2):
            await asyncio.sleep(0.3)
            obs = await plane.observe(cid)
            assert obs.campaign_id == cid, "caller sees the policy's own observation"
            await plane.steer(cid, {"kind": "compose_and_run", "stages": CHAIN,
                                    "replicas": 2})
        await asyncio.sleep(0.3)
        await plane.steer(cid, {"kind": "stop", "reason": "caller done"})

    t = asyncio.create_task(caller())
    res = await mgr.run()
    await t
    assert len(res.tree) > 0

    nid = next(iter(mgr.tree.nodes))
    out = await plane.ingest_measurement(cid, nid, Property(
        name="ddg", value=-5.0,
        source=PropertySource(name="robolab", kind=SourceKind.MEASURED,
                              authority=AUTHORITY_ASSAY)))
    assert out["accepted"]
    n = mgr.tree.get(nid)
    assert n.properties["ddg"].is_measured and n.properties["ddg"].value == -5.0


async def test_provenance_is_written_and_replayable(reg):
    mgr = CampaignManager(spec("t-prov"), ThresholdPolicy(), reg)
    res = await mgr.run()
    graphs = list(mgr.prov.read("graphs"))
    results = list(mgr.prov.read("results"))
    trans = list(mgr.prov.read("transitions"))
    assert graphs and results and trans
    assert any(t.get("event") == "terminated" for t in trans)
    assert all("signature" in g and "estimate" in g for g in graphs)


async def test_budget_is_charged_and_bounds_the_campaign(reg):
    s = spec("t-budget", max_cycles=10)
    s.budget = {"gpu_hours": 0.35, "cpu_hours": 3.0}
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    res = await mgr.run()
    assert mgr.budget.spent, "cost must be charged"
    assert all(mgr.budget.remaining(d) >= -1e-9 for d in mgr.budget.limits)


async def test_concurrent_runs_of_one_intent_are_independent(reg):
    """Two graphs dispatched together must not return the same numbers.

    Task labels used to derive from the CYCLE (`c{cycle}`), which was unique only
    because a cycle implied exactly one submission. Two graphs in flight then shared a
    label, and since task ids are graph-local the mock RNG - seeded on that label - drew
    identically. The campaign would absorb two candidates, both would reach the Pareto
    front, and the front would show two points that are really one measurement. QC
    cannot catch it: each result is individually valid.
    """
    from impress_a.compose.composer import Composer
    from impress_a.exec.backend import make_engine
    from impress_a.exec.dispatch import Dispatcher

    intent = ExperimentIntent(goal="g", stages=CHAIN, replicas=2)
    comp = Composer(reg)
    g1, g2 = comp.compose(intent, "r0001"), comp.compose(intent, "r0002")
    assert sorted(g1.nodes) == sorted(g2.nodes), "task ids are graph-local - the setup"

    flow, _ = await make_engine("concurrent", {"workers": 4}, work_dir=ROOT)
    try:
        d = Dispatcher(flow, reg)
        r1, r2 = await asyncio.gather(d.run(g1, invocation="r0001"),
                                      d.run(g2, invocation="r0002"))
    finally:
        await flow.shutdown()

    assert not r1.failures and not r2.failures, "concurrent dispatch must not fail"
    assert len(r1.per_task) == len(g1.nodes), "every task must report"
    assert r1.merged_metrics() != r2.merged_metrics(), \
        "two submissions of one intent returned identical metrics - fake replicates"

    lin = r1.lineages(g1)
    assert len(lin) == 2, "replicas: N means N lineages"
    assert r1.metrics_for(lin[0]) != r1.metrics_for(lin[1]), \
        "replica lineages within one graph must be independent draws"


async def test_control_plane_sees_campaign_events_and_jobs(reg, tmp_path):
    """`events()` must report what the campaign did, not only what the plane was told.

    The plane has always assigned `manager.prov_sink`, but nothing read it, so the
    stream could only ever replay the plane's own calls - a monitor watching a running
    campaign saw silence. The job ledger had the same problem: constructed, never
    written, so a restart could not tell which runs were still open.
    """
    # An isolated root: the job ledger is append-only and would otherwise accumulate
    # across runs of the suite, which is correct behaviour and useless to assert on.
    s = spec("t-events", max_cycles=2)
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)
    res = await mgr.run()

    evts = [e async for e in plane.events(cid)]
    kinds = {e["kind"] for e in evts}
    assert "campaign" in kinds, "campaign start must reach the stream"
    assert "graphs" in kinds and "executions" in kinds, "composition and execution too"
    assert "terminated" in {e.get("event") for e in evts}
    assert [e["seq"] for e in evts] == list(range(len(evts))), "cursor must be dense"

    jobs = mgr.jobs.entries()
    assert jobs, "every submission must leave a durable record"
    submitted = {j["job_id"] for j in jobs if j.get("status") == "submitted"}
    assert len(submitted) == res.runs, "one ledger entry per dispatched run"
    assert not mgr.jobs.open_jobs(), "a finished campaign leaves no run unresolved"


async def test_observation_recency_follows_a_cursor_not_the_cycle(reg):
    """`recent` must mean "landed since you last looked"."""
    mgr = CampaignManager(spec("t-cursor", max_cycles=2), ThresholdPolicy(), reg)
    await mgr.run()

    # A fresh observer asking from the beginning sees everything absorbed.
    full = mgr.observe(since=0)
    assert len(full.recent) == len(mgr.executor._absorbed) == full.seq

    # Asking from the current watermark sees nothing new - and does not disturb anyone.
    caught_up = mgr.observe(since=full.seq)
    assert caught_up.recent == []
    assert mgr.observe(since=0).seq == full.seq, "observe must not consume the cursor"


async def _watch_inflight(mgr):
    """Record how many experiments were outstanding at each reap."""
    ex = mgr.executor
    seen, sets = [], []
    orig = ex._reap

    async def watched(run_id):
        seen.append(len(ex._inflight))
        sets.append([(r.run_id, r.signature, r.scrutiny.trusted)
                     for r in ex._inflight.values()])
        return await orig(run_id)

    ex._reap = watched
    return seen, sets


async def test_concurrency_holds_several_experiments_in_flight(reg, tmp_path):
    """The whole point: submission no longer blocks the reasoner.

    Previously `dispatcher.run` was awaited where it was submitted, so exactly one graph
    could exist at a time and a cycle could not end until the slowest lineage finished.
    """
    s = spec("t-conc", max_cycles=6)
    s.root, s.concurrency = str(tmp_path), 3
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    seen, sets = await _watch_inflight(mgr)
    res = await mgr.run()

    assert max(seen) > 1, "no two experiments ever overlapped"
    assert max(seen) <= s.concurrency, "the concurrency cap must bind"
    assert res.runs >= max(seen)
    assert not mgr.executor._inflight, "draining must leave nothing outstanding"
    assert not mgr.budget.holds, "every reservation must be settled or released"
    assert all(mgr.budget.remaining(d) >= -1e-9 for d in mgr.budget.limits)


async def test_untrusted_patterns_are_never_concurrent_with_themselves(reg, tmp_path):
    """One in-flight instance per untrusted signature.

    Promotion counts CONSECUTIVE clean runs. Three concurrent instances of one
    provisional pattern are a single draw sampled three times, so the pattern would
    promote without the first result ever informing the second launch - the interlock
    reporting evidence it never gathered. Distinct shapes may still run in parallel,
    which is the fan-out worth having.
    """
    s = spec("t-interlock-conc", max_cycles=6)
    s.root, s.concurrency = str(tmp_path), 3
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    _, sets = await _watch_inflight(mgr)
    await mgr.run()

    overlapped = [row for row in sets if len(row) > 1]
    assert overlapped, "this test is meaningless without overlap"
    for row in overlapped:
        untrusted = [sig for _, sig, trusted in row if not trusted]
        assert len(untrusted) == len(set(untrusted)), \
            f"two instances of one untrusted pattern were in flight: {row}"


async def test_drained_runs_are_still_absorbed_and_still_count_as_evidence(reg, tmp_path):
    """Work in flight when the loop exits has been paid for; it must not be discarded."""
    s = spec("t-drain", max_cycles=3)
    s.root, s.concurrency = str(tmp_path), 4      # more slots than turns: nothing waits
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    res = await mgr.run()

    assert res.runs >= 1, "the campaign must have dispatched something"
    assert len(mgr.tree) > 0, "drained results must reach the tree"
    assert not mgr.executor._inflight and not mgr.budget.holds
    assert mgr.budget.spent, "drained runs must still be charged"
    entries = mgr.jobs.entries()
    submitted = {j["job_id"] for j in entries if j.get("status") == "submitted"}
    terminal = {j["job_id"] for j in entries
                if j.get("status") in ("done", "failed", "cancelled")}
    assert submitted and submitted == terminal, \
        "every dispatched run must reach a terminal state, drained or not"


async def test_cancel_is_advisory_and_the_outcome_still_comes_from_collect(reg):
    """Cancellation reclaims queued work only, and never reports its own success.

    The concurrent backend calls `Future.cancel()`, which returns False once a callable
    has started, and asyncflow discards that answer anyway. So a run's terminal state
    must come from collecting it - never from the fact that cancel was called.
    """
    from impress_a.compose.composer import Composer
    from impress_a.exec.backend import make_engine
    from impress_a.exec.dispatch import Dispatcher

    g = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=CHAIN, replicas=4), "r0009")
    flow, _ = await make_engine("concurrent", {"workers": 2}, work_dir=ROOT)
    try:
        d = Dispatcher(flow, reg)
        h = d.submit(g, run_id="r0009")
        d.cancel(h)
        assert h.cancelled
        res = await d.collect(h)           # must still reach a terminal state
    finally:
        await flow.shutdown()

    assert len(res.failures) + len(res.per_task) == len(g.nodes), \
        "every task must be accounted for, cancelled or not"
    assert res.failures, "queued work should have been reclaimed"


async def test_run_labels_tag_tasks_so_concurrent_graphs_stay_distinguishable(reg):
    """Task names are graph-local and collide across runs; the tag is what separates
    them in a log or a trace."""
    from impress_a.compose.composer import Composer
    from impress_a.exec.backend import make_engine
    from impress_a.exec.dispatch import Dispatcher

    flow, _ = await make_engine("concurrent", {"workers": 2}, work_dir=ROOT)
    try:
        d = Dispatcher(flow, reg)
        hs = [d.submit(Composer(reg).compose(
            ExperimentIntent(goal="g", stages=["mock_generate", "mock_design"]), lbl),
            run_id=lbl) for lbl in ("r0042", "r0043")]
        for h in hs:
            await d.collect(h)
        tagged: dict[str, set[str]] = {}
        for c in flow.components.values():
            desc = c["description"]
            tagged.setdefault(desc.get("workflow_id"), set()).add(desc["name"])
    finally:
        await flow.shutdown()

    assert set(tagged) == {"r0042", "r0043"}, "each run's tasks carry its label"
    assert tagged["r0042"] == tagged["r0043"], \
        "the names themselves collide - the tag is doing the work"


class EnsemblePolicy:
    """A reasoner that drives itself: fan out, then adapt to whatever lands first.

    This is the workflow the old loop could not express. `decide` was called once per
    cycle and the manager then blocked on the graph it asked for, so a federation of task
    agents generating an ensemble in parallel had nowhere to live.
    """

    name = "ensemble"

    def __init__(self, width=4, follow_ups=2):
        self.width, self.follow_ups = width, follow_ups
        self.order: list[str] = []
        self.observed_inflight = 0

    async def conduct(self, session):
        obs = await session.observe()
        ids = []
        for _ in range(self.width):
            ids.append(await session.submit(ExperimentIntent(
                goal=obs.goal, stages=CHAIN, replicas=1)))

        self.observed_inflight = len(await session.inflight())

        # Consume results as they land and launch follow-ups from the best so far.
        launched = 0
        async for outcome in session.as_completed(ids):
            self.order.append(outcome.run_id)
            if launched < self.follow_ups:
                launched += 1
                try:
                    await session.submit(ExperimentIntent(
                        goal=obs.goal, stages=CHAIN, replicas=1,
                        parent_node=outcome.nodes[0] if outcome.nodes else None))
                except SubmissionRejected:
                    pass
        await session.stop("ensemble complete")


async def test_a_reasoner_can_fan_out_and_collect_as_results_land(reg, tmp_path):
    from impress_a.compose.composer import Composer
    from impress_a.compose.interlock import PatternRecord

    s = spec("t-ensemble", max_cycles=99)
    s.root, s.concurrency = str(tmp_path), 8
    pol = EnsemblePolicy(width=4)
    mgr = CampaignManager(s, pol, reg)

    # A shape the site has already proven. The interlock deliberately refuses to run an
    # UNTRUSTED pattern concurrently with itself, so a fan-out of one novel workflow is
    # not something a reasoner may do - it has to earn that first. Trusted shapes are
    # exactly what an ensemble is made of.
    sig = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=CHAIN, replicas=1), "probe"
    ).pattern_signature()
    mgr.trust.patterns[sig] = PatternRecord(signature=sig, trusted=True, clean_runs=3)

    res = await mgr.run()

    assert pol.observed_inflight > 1, \
        "four experiments were submitted without waiting; they must overlap"
    assert len(pol.order) == 4, "every submitted run must be delivered"
    assert res.runs >= 4
    assert len(mgr.tree) >= 4, "each lineage becomes its own candidate"
    assert not mgr.executor._inflight and not mgr.budget.holds
    assert res.stop_reason == "ensemble complete"


async def test_reasoner_is_woken_when_the_executor_ends_the_campaign(reg, tmp_path):
    """A reasoner waiting on a run when the campaign ends must not wait forever.

    The executor decides termination - budget, stagnation, repeated failure are facts
    about state the reasoner cannot see. Splitting them into two coroutines makes it
    possible for the executor to stop while the reasoner is blocked on a future that
    nothing will ever set. It must be woken with an exception instead.
    """
    woken = asyncio.Event()

    class Waiter:
        name = "waiter"

        async def conduct(self, session):
            obs = await session.observe()
            rid = await session.submit(ExperimentIntent(
                goal=obs.goal, stages=CHAIN, replicas=1))
            await session.stop("caller asked to stop while still waiting")
            try:
                await session.result(rid)
            except CampaignStopped:
                woken.set()
                raise

    s = spec("t-deadlock", max_cycles=99)
    s.root = str(tmp_path)
    await CampaignManager(s, Waiter(), reg).run()
    assert woken.is_set(), "the reasoner was left waiting on a campaign that had ended"


async def test_a_finished_run_survives_the_process_that_ran_it(reg, tmp_path):
    """The durable half of the split: results outlive the executor that produced them.

    The job ledger has existed since the first prototype and was never read or written.
    A restart therefore lost track of everything - and a run whose result is not
    recorded has to be re-run, which on HPC means paying for the allocation twice.
    """
    s = spec("t-durable", max_cycles=2)
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    res = await mgr.run()
    assert res.runs >= 1

    done = [r for r in mgr.runs.list_runs() if r.state.is_terminal]
    assert done, "runs must reach a terminal state"
    rid = done[0].run_id

    # A NEW manager over the same root - nothing shared but the log on disk.
    fresh = CampaignManager(s, ThresholdPolicy(), reg)
    recovered = fresh.runs.outcome(rid)
    assert recovered is not None, "the outcome must be readable from the ledger alone"
    assert recovered.run_id == rid
    assert recovered.metrics == mgr.runs.outcome(rid).metrics, \
        "the recovered result must be the result, not just the fact of one"
    assert recovered.state.is_terminal


async def test_reattach_reports_orphans_and_checks_the_control_model(reg, tmp_path):
    """What a restart finds, and the ADR 0005 check that only a restart can break.

    A campaign's results are attributable to one stated methodology because the control
    model is fixed at launch. That enforced itself while a campaign lived and died inside
    one process; once a reasoner can reattach, nothing stops it reattaching as a
    different policy unless somebody checks.
    """
    s = spec("t-reattach", max_cycles=2)
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    fresh = CampaignManager(s, ThresholdPolicy(), reg)
    report = fresh.runs.reattach(expected_policy="threshold")
    assert report.campaign_id == "t-reattach"
    assert report.policy == "threshold", "the launching methodology must be on record"
    assert report.policy_matches
    assert report.completed, "finished runs must be recoverable by id"
    assert not report.orphaned, "a cleanly finished campaign strands nothing"

    assert not fresh.runs.reattach(expected_policy="oracle").policy_matches, \
        "resuming under a different control model must be detectable"

    # A run recorded as submitted and never resolved is what recovery exists for.
    mgr.jobs.record(job_id="r9999", status="submitted", graph="g-lost")
    assert "r9999" in fresh.runs.reattach().orphaned


async def test_control_plane_drives_runs_by_id(reg, tmp_path):
    """The operations an out-of-process reasoner would use, over the in-process adapter."""
    s = spec("t-plane-runs", max_cycles=99)
    s.root, s.concurrency = str(tmp_path), 4

    class Idle:
        name = "idle"

        async def conduct(self, session):
            await asyncio.sleep(3600)          # the caller drives; we just stay alive

    mgr = CampaignManager(s, Idle(), reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async def caller():
        await asyncio.sleep(0.2)
        intent = {"goal": "g", "stages": CHAIN, "replicas": 1}
        first = await plane.submit_run(cid, intent)
        assert first["accepted"], first
        rid = first["run_id"]

        listed = await plane.list_runs(cid)
        assert any(r["run_id"] == rid for r in listed)

        # An untrusted shape may not run concurrently with itself - the caller is
        # subject to the same gates as any policy, and is told why.
        second = await plane.submit_run(cid, intent)
        if not second["accepted"]:
            assert second["failure"]["gate"] in ("interlock", "budget")
            assert second["failure"]["transient"] is True

        for _ in range(100):
            if (out := await plane.run_result(cid, rid)) is not None:
                assert out["run_id"] == rid
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the run never produced a retrievable result")

        await plane.stop(cid, "caller done")

    t = asyncio.create_task(caller())
    res = await mgr.run()
    await t
    assert res.stop_reason == "caller done", \
        "stop must work for any policy, not only an externally steered one"
    assert len(mgr.tree) >= 1


async def test_pause_actually_holds_admission(reg, tmp_path):
    """`pause` was on the control plane from the start and never did anything.

    It gates ADMISSION, not execution: work already dispatched runs to completion,
    because holding it would mean cancelling it, and cancellation here is advisory.
    """
    from impress_a.compose.composer import Composer
    from impress_a.compose.interlock import PatternRecord

    s = spec("t-pause", max_cycles=99)
    s.root, s.concurrency = str(tmp_path), 16
    # Generous budget on purpose: this test is about pause, and a budget that binds
    # first looks exactly like a pause that never lifted.
    s.budget = {"gpu_hours": 200.0, "cpu_hours": 2000.0}
    admitted: list[str] = []

    class Submitter:
        name = "submitter"

        async def conduct(self, session):
            obs = await session.observe()
            while True:
                admitted.append(await session.submit(ExperimentIntent(
                    goal=obs.goal, stages=CHAIN, replicas=1)))
                await asyncio.sleep(0.02)

    mgr = CampaignManager(s, Submitter(), reg)
    # A proven shape: the interlock refuses to run an untrusted one concurrently with
    # itself, which would be what held admission rather than the pause under test.
    sig = Composer(reg).compose(
        ExperimentIntent(goal="g", stages=CHAIN, replicas=1), "probe"
    ).pattern_signature()
    mgr.trust.patterns[sig] = PatternRecord(signature=sig, trusted=True, clean_runs=3)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async def caller():
        await asyncio.sleep(0.25)
        await plane.pause(cid)
        assert mgr.executor.paused
        held = len(admitted)
        await asyncio.sleep(0.3)
        assert len(admitted) == held, "admission continued while paused"
        await plane.resume(cid)
        await asyncio.sleep(0.25)
        assert len(admitted) > held, "admission did not resume"
        # Paused then stopped must not hang: admission waits, but never past the end.
        await plane.pause(cid)
        await plane.stop(cid, "stopped while paused")

    t = asyncio.create_task(caller())
    res = await mgr.run()
    await t
    assert res.stop_reason == "stopped while paused"
    assert not mgr.executor._inflight and not mgr.budget.holds


async def test_outputs_are_typed_handles_that_survive_the_wire(reg, tmp_path):
    """Stage 4's contract: everything a remote reasoner receives must round-trip.

    `TaskResult.outputs` used to be `dict[str, Any]` holding whatever the tool returned,
    and the projection stringified it. Neither says what an output IS, and neither
    survives a process boundary in a form the far side can act on.
    """
    import json

    from impress_a.core.results import RunOutcome

    s = spec("t-wire", max_cycles=2)
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    outcomes = list(mgr.executor._outcomes.values())
    assert outcomes, "the campaign must have produced something to inspect"

    for out in outcomes:
        assert out.artifacts, "a run must report what it produced, not only numbers"
        for port, ref in out.artifacts.items():
            assert ref.type is not None, f"{port} must carry its declared type"
            assert ref.located is not None, f"{port} must point at something"
        # Exact round-trip, not merely parseable: a field that silently changes type
        # over JSON is the bug this contract exists to prevent.
        blob = json.dumps(out.model_dump(mode="json"))
        assert RunOutcome(**json.loads(blob)) == out


async def test_a_front_node_can_be_traced_to_the_structure_it_claims(reg, tmp_path):
    """`DesignNode.artifacts` existed from the first prototype and was never populated,
    so there was no way from a ranked candidate to the file it is a claim about."""
    s = spec("t-artifacts", max_cycles=2)
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    res = await mgr.run()

    assert res.front, "need a ranked candidate to trace"
    for node in res.front:
        assert node.artifacts, f"{node.id} is ranked but points at nothing"
        assert any(r.type is ArtifactType.COMPLEX for r in node.artifacts.values()), \
            "the scored structure must be reachable from the node"


async def test_an_undeclared_output_is_refused_not_silently_dropped(reg):
    """The composer type-checks the graph against declared ports. An output nobody
    declared cannot be consumed and cannot be typed, so swallowing it would hide a
    spec bug behind a downstream 'missing input'."""
    from impress_a.tools.agent import TaskRequest

    agent = reg.agent_for("mock_generate")(reg.get("mock_generate"))
    with pytest.raises(ValueError, match="undeclared output"):
        await agent.post_process(TaskRequest(tool="mock_generate"),
                                 {"outputs": {"not_a_port": "x"}, "metrics": {}})


def _stagnation_probe(reg, tmp_path, concurrency):
    """An executor with a front that never moves, so only the counting is under test."""
    s = spec("t-stag", max_cycles=99)
    s.root, s.concurrency = str(tmp_path), concurrency
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    return ex


def _absorbed_run(ex, informed_by, nodes=1):
    """Stand in for a completed run: record what it could see, then absorb its nodes."""
    from impress_a.runtime.executor import RunRecord

    rec = RunRecord(run_id=f"r{informed_by}", graph=None, signature="sig",
                    scrutiny=Scrutiny.for_pattern(ex.trust, "sig"), intent=None,
                    turn=0, informed_by=informed_by)
    ex._absorbed.extend(["n"] * nodes)      # the run landed
    return ex._note_progress(rec)


def test_one_wave_of_concurrent_runs_counts_as_one_attempt(reg, tmp_path):
    """Four runs launched together are one draw sampled four times.

    None of them could act on the others' results, so blaming all four for failing to
    improve on evidence none of them saw is what stopped healthy campaigns within a
    second of fanning out.
    """
    ex = _stagnation_probe(reg, tmp_path, concurrency=4)

    # All four admitted before anything had been absorbed: informed_by == 0.
    for _ in range(4):
        _absorbed_run(ex, informed_by=0)
    assert ex._stagnant == 1, "a wave is one attempt, not four"

    # A second wave, admitted after the first four landed, is fresh evidence.
    for _ in range(4):
        _absorbed_run(ex, informed_by=4)
    assert ex._stagnant == 2

    for _ in range(4):
        _absorbed_run(ex, informed_by=8)
    assert ex._stagnant == 3, "three barren waves still stop the campaign"


def test_serial_stagnation_is_unchanged(reg, tmp_path):
    """At concurrency 1 every run is informed by the previous one, so every run counts -
    exactly the behaviour this had before fan-out existed."""
    ex = _stagnation_probe(reg, tmp_path, concurrency=1)
    for i in range(3):
        stalled = _absorbed_run(ex, informed_by=i)
        assert ex._stagnant == i + 1
    assert stalled, "stagnation_limit=3 must still fire on the third attempt"


def test_improving_the_front_resets_stagnation(reg, tmp_path):
    ex = _stagnation_probe(reg, tmp_path, concurrency=1)
    _absorbed_run(ex, informed_by=0)
    _absorbed_run(ex, informed_by=1)
    assert ex._stagnant == 2

    # A node that lands on the front is progress, whatever the counter said before.
    node = DesignNode(cycle=0)
    node.properties["sc_rmsd"] = Property(
        name="sc_rmsd", value=0.1, source=PropertySource(name="t", authority=10))
    node.properties["iptm"] = Property(
        name="iptm", value=0.99, source=PropertySource(name="t", authority=10))
    ex.tree.add(node)
    _absorbed_run(ex, informed_by=2)
    assert ex._stagnant == 0, "a moved front clears the counter"


async def test_polling_alone_never_advances_stagnation(reg, tmp_path):
    """A reasoner that watches without submitting must not talk itself into stopping."""
    s = spec("t-stag-poll", max_cycles=99)
    s.root = str(tmp_path)
    looked: list[int] = []

    class Watcher:
        name = "watcher"

        async def conduct(self, session):
            for _ in range(25):
                await session.observe()
                await session.inflight()
                looked.append(len(await session.inflight()))
                await asyncio.sleep(0.01)
            await session.stop("watched, submitted nothing")

    mgr = CampaignManager(s, Watcher(), reg)
    res = await mgr.run()
    assert len(looked) == 25, "the watcher must actually have polled"
    assert mgr.executor._stagnant == 0
    assert res.stop_reason == "watched, submitted nothing", \
        "polling must not be mistaken for a campaign that has run out of ideas"


class _RecordsInterpret(ThresholdPolicy):
    """A model-D policy that writes down every outcome `interpret` is handed."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.interpreted: list[str] = []

    async def interpret(self, results, obs):
        self.interpreted.append(results.run_id)
        return await super().interpret(results, obs)


async def test_interpret_fires_once_per_collected_run(reg, tmp_path):
    """The `interpret` hook belongs to whoever collects the outcome - exactly once.

    It used to be called by the executor, on the executor's own reference to the policy.
    That worked only while the reasoner shared its process; it is now the driver's, at
    `SequentialPolicyDriver._collect`. This pins BOTH halves of that move: a duplicate
    means someone restored the executor's call without removing the driver's, and a
    policy that accumulates across runs would then double-count.
    """
    s = spec("t-interpret", max_cycles=3)
    s.root = str(tmp_path)
    pol = _RecordsInterpret()
    res = await CampaignManager(s, pol, reg).run()

    assert pol.interpreted, "interpret was never called - the hook is unwired"
    assert len(pol.interpreted) == len(set(pol.interpreted)), \
        f"interpret called twice for the same run: {pol.interpreted}"
    assert res.stop_reason


async def test_a_truncated_chain_can_never_move_the_front(reg, tmp_path):
    """Backlog G1, made detectable rather than fixed.

    A chain that skips the stage producing a constrained objective yields nodes that
    `pareto.feasible` rejects for a MISSING value. The front stays empty; `_note_progress`
    increments on every informed landing that leaves it unchanged, including
    empty-and-still-empty; and at concurrency 1 every landing is informed by the one
    before it. So the executor ends a campaign whose science is going fine. Nothing here
    is a QC failure and nothing is over budget.

    Here `mock_generate -> mock_design` stands in for the real explore chain: it emits
    ss_fraction, designability, seq_recovery and diversity, and none of OBJS' sc_rmsd,
    iptm or ddg.

    This asserts the CURRENT behaviour. When G1 is decided
    (plans/exploration-vs-stagnation.md) this test is the first thing that must change.
    """
    s = spec("t-g1", max_cycles=10, stagnation_limit=3, concurrency=1)
    s.root = str(tmp_path)
    res = await CampaignManager(
        s, ThresholdPolicy(stages=["mock_generate", "mock_design"]), reg).run()

    assert len(res.tree) > 0, "the runs happened"
    assert all(n.qc.verdict is not QCVerdict.FAIL for n in res.tree), \
        "and QC passed - nothing is wrong with the science"
    assert res.front == [], "yet the front is empty: no node carries sc_rmsd or iptm"
    assert res.stop_reason.startswith("stagnation:"), res.stop_reason
    assert res.cycles < s.max_cycles, "the executor stopped it early"
