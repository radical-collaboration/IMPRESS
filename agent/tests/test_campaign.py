"""T2 - mock campaign. A complete campaign end to end on a laptop.

Real manager, real policy, real composer, real validator, real state and provenance,
with ConcurrentExecutionBackend and mock tools. Exercises every layer above the substrate.
"""
import asyncio

import pytest

from impress_a.compose.composer import Composer
from impress_a.compose.graph import TaskGraph, TaskNode
from impress_a.compose.interlock import Scrutiny
from impress_a.compose.validate import SiteCaps
from impress_a.control.plane import InProcessControlPlane
from impress_a.core.artifacts import (
    AUTHORITY_ASSAY,
    AUTHORITY_ML_PREDICTOR,
    ArtifactRef,
    Property,
    PropertySource,
    SourceKind,
)
from impress_a.core.decision import ExperimentIntent
from impress_a.core.goal import Goal
from impress_a.core.pareto import Direction, Objective
from impress_a.core.qc import QCVerdict
from impress_a.core.session import CampaignStopped, SubmissionRejected
from impress_a.core.spec import (
    Aim,
    Spec,
    SpecObjective,
    SpecRevision,
    Stage,
    TaskMapping,
    TaskRecord,
    TaskState,
)
from impress_a.core.tree import DesignNode
from impress_a.core.types import ArtifactType
from impress_a.exec.backend import make_engine
from impress_a.exec.dispatch import Dispatcher
from impress_a.manager import CampaignManager, CampaignSpec
from impress_a.policy.agentic import FourNodePolicy
from impress_a.policy.explicit import ThresholdPolicy
from impress_a.policy.external import ExternalPolicy
from impress_a.policy.legacy import LegacyPlanner
from impress_a.policy.oracle import OraclePolicy
from impress_a.policy.wrappers import NullPolicy, RuleCorrectionsPolicy
from impress_a.runtime.roles import _intent_for
from impress_a.tools.agent import TaskRequest
from impress_a.tools.mock_agents import _upstream
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
    await CampaignManager(spec("t-guard"), guarded, reg).run()
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
    await mgr.run()
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
    await mgr.run()
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
    # Likewise stagnation, which is the engine's own stop and a correct one here: a
    # submitter that never reads results stalls the front, and the counter (traced) hits 3
    # informed non-improving runs at ~1.40s - tens of milliseconds either side of this
    # test's scripted stop. It passed or failed on scheduling noise. The stop under test
    # has to be the one that lands.
    s.stagnation_limit = 1_000
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


async def test_a_truncated_chain_does_not_count_toward_stagnation(reg, tmp_path):
    """Backlog G1, decided.

    A chain that skips the stage producing a constrained objective yields nodes that
    `pareto.feasible` rejects for a MISSING value, so the front stays empty however well the
    science goes. The counter used to increment on every such landing - at concurrency 1 every
    landing is informed by the one before it - and ended a campaign with nothing wrong with it,
    modelled at t~135 min of a 4 h allocation, before the first exploit run could land.

    Here `mock_generate -> mock_design` stands in for the real explore chain: it emits
    ss_fraction, designability, seq_recovery and diversity, and none of OBJS' sc_rmsd, iptm or
    ddg.

    The ruling is that a run which COULD NOT have moved the front is not evidence that progress
    has stalled - the same kind of flaw as the fan-out one, and found the same way: the counter
    was asking "did the front change" when the question it needs is "did something that could
    have changed the front fail to". **This test previously asserted the opposite**, by design,
    and its docstring said it would be the first thing to change.

    Raising `stagnation_limit` was the wrong fix and is not what happened:
    `test_stagnation_still_counts_a_chain_that_could_have_moved_the_front` is the other half.
    """
    s = spec("t-g1", max_cycles=4, stagnation_limit=2, concurrency=1)
    s.root = str(tmp_path)
    res = await CampaignManager(
        s, ThresholdPolicy(stages=["mock_generate", "mock_design"], max_cycles=99,
                           target_front=99), reg).run()

    assert len(res.tree) > 0, "the runs happened"
    assert all(n.qc.verdict is not QCVerdict.FAIL for n in res.tree), \
        "and QC passed - nothing is wrong with the science"
    assert res.front == [], "the front is still empty: no node carries sc_rmsd or iptm"
    assert not res.stop_reason.startswith("stagnation:"), res.stop_reason
    assert "max_cycles" in res.stop_reason, (
        f"the allocation should be what ends it, not the counter: {res.stop_reason}")
    assert res.cycles == s.max_cycles, "every cycle it was given was used"
    # The exemption is bounded, not open - see the test below. Four cycles is under the
    # default `max_unproductive_runs`, so this campaign ends where it was told to.


async def test_stagnation_still_counts_a_chain_that_could_have_moved_the_front(reg, tmp_path):
    """The other half of G1: the fix is additive, not a weakening.

    A full chain produces every constrained objective, so its nodes are front-eligible and a
    run that leaves the front unchanged is real evidence of a stall. Without this, "exclude the
    runs that never had a chance" would be indistinguishable from "stop counting".
    """
    s = spec("t-g1-still-counts", max_cycles=20, stagnation_limit=2, concurrency=1)
    s.root = str(tmp_path)
    # target_front=99 keeps the policy from stopping first, so the counter is what ends it.
    res = await CampaignManager(
        s, ThresholdPolicy(max_cycles=99, target_front=99), reg).run()

    assert res.stop_reason.startswith("stagnation:"), res.stop_reason
    assert res.cycles < s.max_cycles, "the counter stopped it early, as it should"


class _Backtracker:
    """Runs the mock chain, branching from its first result before run `backtrack_at` -
    or before every run after the first, when `always` is set."""
    name = "backtracker"

    def __init__(self, backtrack_at: int = 1, always: bool = False):
        self.backtrack_at, self.always = backtrack_at, always
        self.first_node: str | None = None
        self.backtracked_before: set[int] = set()

    async def decide(self, obs):
        from impress_a.core.decision import Backtrack, ComposeAndRun
        due = self.always or obs.cycle == self.backtrack_at
        if self.first_node and due and (self.always or obs.cycle not in self.backtracked_before):
            self.backtracked_before.add(obs.cycle)
            return Backtrack(node_id=self.first_node, rationale="test")
        return ComposeAndRun(intent=ExperimentIntent(goal=obs.goal, stages=CHAIN, replicas=1))

    async def interpret(self, outcome, obs):
        self.first_node = self.first_node or (outcome.nodes[0] if outcome.nodes else None)

    async def on_rejected(self, decision, failure):
        from impress_a.core.decision import Stop
        return Stop(reason=f"rejected: {failure.reason}")


async def test_a_backtrack_does_not_spend_a_cycle(reg):
    """max_cycles counts RUNS. Jobs 22702568, 22726105 and 22728140 each asked for 6,
    backtracked once, and ran 5 - the driver counted the backtrack as a cycle."""
    s = spec("t-bt-cycles", max_cycles=3)
    s.stagnation_limit = 3
    res = await CampaignManager(s, _Backtracker(backtrack_at=1), reg).run()
    assert res.runs == 3 and res.cycles == 3, (res.runs, res.cycles, res.stop_reason)
    assert res.stop_reason == "max_cycles=3 reached"


async def test_a_policy_that_only_backtracks_is_stopped(reg):
    """Free backtracks must not mean unbounded ones."""
    s = spec("t-bt-spin", max_cycles=5)
    res = await CampaignManager(s, _Backtracker(always=True), reg).run()
    assert res.stop_reason == "policy backtracked twice without running anything between"
    assert res.runs == 1


# ---------------------------------------------------------------------------
# The role pipeline (phase 1 of plans/control-plane-refactor.md).
#
# The strangler's seam. Until a responsibility actually moves, the only thing worth asserting
# about the Spec Loop + Planning Loop pipeline is that it changes nothing - and that is what
# makes every later phase's failure attributable to that phase.
# ---------------------------------------------------------------------------

def _roles_shape(nodes):
    """What a campaign FOUND, not the ids it minted. Mirrors tests/test_remote_session.py."""
    return [(n.cycle, n.qc.verdict.value,
             sorted((k, p.value) for k, p in n.properties.items())) for n in nodes]


@pytest.mark.parametrize("make_policy, label", [
    (ThresholdPolicy, "D"),
    (FourNodePolicy, "A"),
    (lambda: RuleCorrectionsPolicy(ThresholdPolicy(base_replicas=99), max_replicas=2), "guard"),
    # The three members of the Decision union that the role interfaces deliberately cannot
    # express, so each one exercises a different branch of the adapter's named overflow:
    # NullPolicy stops on its first decision, and _Backtracker branches from an earlier node
    # before every run after the first - which in the target design is a parent_node on a
    # SpecObjective rather than a verb, and here must still reproduce exactly.
    (NullPolicy, "null"),
    (lambda: _Backtracker(always=True), "backtrack"),
])
async def test_roles_pipeline_reproduces_the_legacy_campaign(reg, tmp_path, make_policy, label):
    """Same policy, both control paths, identical science.

    **Each arm needs its own trust_root, and that is a finding rather than test hygiene.** The
    trust ledger is site-scoped and spans campaigns by design, so with one ledger the first
    arm's clean runs promote the pattern and the second arm runs *trusted* - its nodes come
    back `pass` where the first arm's were `suspect`, with byte-identical metrics. Two
    campaigns that differ only in which ran first is exactly the confound the four-arm
    experiment gives each arm its own IMPRESS_A_TRUST_DIR to avoid, and this is the cheapest
    place to see the mechanism.
    """
    out = {}
    for control in ("legacy", "roles"):
        s = spec(f"t-par-{label}-{control}", control=control,
                 trust_root=str(tmp_path / f"trust-{control}"))
        res = await CampaignManager(s, make_policy(), reg).run()
        out[control] = (res.cycles, res.stop_reason, len(res.front),
                        _roles_shape(res.tree.nodes.values()))

    assert out["legacy"][1] == out["roles"][1], "the stop reason must be the same sentence"
    assert out["legacy"][0] == out["roles"][0], "the same number of runs must be admitted"
    assert out["legacy"][2] == out["roles"][2], "the front must be the same size"
    assert out["legacy"][3] == out["roles"][3], "every node, verdict and metric must match"


async def test_a_stage_round_trips_through_an_intent(reg):
    """Scaffolding, pinned: phase 1 must not touch compose/ or exec/.

    `LegacyPlanner` renders a decision as a Stage and the Deployer renders it back, so the
    executor keeps receiving exactly the intent it always did. Everything `Composer.compose`
    reads has to survive that round trip - the ordered tool list, the replica count, and the
    per-tool params whose silent loss is backlog H3.
    """
    intent = ExperimentIntent(goal="stabilize", stages=CHAIN, replicas=3,
                              params={"mock_generate": {"diffusion_steps": 170},
                                      "mock_design": {"temperature": 0.35}})
    planner = LegacyPlanner(ThresholdPolicy())
    stage = planner._render(intent, Spec())
    back = _intent_for(stage, Goal(text="stabilize"))

    assert back.stages == intent.stages
    assert back.replicas == intent.replicas
    assert back.params == intent.params
    assert len({t.lineage for t in stage.runs}) == 3
    assert len(stage.runs) == 3 * len(CHAIN)


async def test_the_listener_stops_the_campaign_when_every_objective_is_satisfied(reg, tmp_path):
    """The Spec's own stop condition, which no legacy policy could express.

    The bounded objectives here are all met by the first run, so the Spec completes and the
    Listener asks to stop - with its own reason, not the policy's. `max_cycles` is high enough
    that reaching it would prove nothing.
    """
    s = spec("t-spec-complete", control="roles", max_cycles=20,
             trust_root=str(tmp_path / "trust"))
    s.objectives = [Objective(name="iptm", direction=Direction.MAX, min=0.1),
                    Objective(name="sc_rmsd", direction=Direction.MIN, max=99.0)]
    res = await CampaignManager(s, ThresholdPolicy(max_cycles=20, target_front=99), reg).run()

    assert res.stop_reason == "every spec objective satisfied"
    assert res.cycles >= 1


async def test_an_unbounded_objective_never_completes_the_spec(reg, tmp_path):
    """`total_score: minimize` is an optimisation target, never a finish line.

    `Objective.satisfied_by` answers True for any value when both bounds are None, which is
    right for ranking - nothing is pruned - and would be wrong here: it would finish a campaign
    the moment its first unbounded metric reported anything. This is the bug the parity probe
    surfaced, and it is the reason `SatisfactionRule.is_bounded` exists.
    """
    s = spec("t-spec-unbounded", control="roles", max_cycles=2,
             trust_root=str(tmp_path / "trust"))
    s.objectives = [Objective(name="ddg", direction=Direction.MIN)]
    res = await CampaignManager(s, ThresholdPolicy(max_cycles=2, target_front=99), reg).run()

    assert res.stop_reason != "every spec objective satisfied"
    assert "max_cycles" in res.stop_reason


async def test_the_stagnation_exemption_is_bounded(reg, tmp_path):
    """An exemption with no counter is fail-open, and on HPC that is a whole allocation.

    G1 is right that a run which could not have reached the front is not evidence of
    stagnation - but if NO run can, the stagnation counter never advances and a campaign whose
    chain can never produce a constrained objective runs at full speed to its cycle limit. The
    first version of the G1 fix did exactly that, and the test above locked it in.

    The stop reason is deliberately distinct: "stagnation" would say the search stalled, where
    this says nothing capable of scoring was ever attempted. Different defect, different fix -
    almost always a chain that cannot produce a constrained objective rather than an unlucky
    one.
    """
    s = spec("t-unproductive", max_cycles=20, stagnation_limit=99, concurrency=1)
    s.max_unproductive_runs = 3
    s.root = str(tmp_path)
    res = await CampaignManager(
        s, ThresholdPolicy(stages=["mock_generate", "mock_design"], max_cycles=99,
                           target_front=99), reg).run()

    assert "could not produce a constrained objective" in res.stop_reason, res.stop_reason
    assert not res.stop_reason.startswith("stagnation:"), \
        "a chain that can never score is not a stalled search"
    assert res.cycles <= s.max_unproductive_runs + 1
    assert res.cycles < s.max_cycles, "it did not burn the allocation"


async def test_a_productive_run_resets_the_unproductive_counter(reg, tmp_path):
    """The bound counts CONSECUTIVE unproductive runs, so exploration between exploits is free.

    Without this the backstop would be a cap on total exploration, which is a search-shaping
    knob - and that is exactly what G1 ruled out.
    """
    s = spec("t-unproductive-reset", max_cycles=6, stagnation_limit=99, concurrency=1)
    s.max_unproductive_runs = 2
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor

    ex._unproductive = 1
    ex._note_progress(_rec(could_reach=True))
    assert ex._unproductive == 0, "a run that could have scored clears the backstop"
    ex._note_progress(_rec(could_reach=False))
    ex._note_progress(_rec(could_reach=False))
    assert ex._unproductive == 2


def _rec(could_reach: bool):
    from types import SimpleNamespace
    return SimpleNamespace(informed_by=0, could_reach_the_front=could_reach)


async def test_available_tools_is_narrowed_to_the_campaigns_stages(reg, tmp_path):
    """One list, derived from the other - because this one goes into model B's prompt.

    `policy/oracle.py` renders `available_tools` verbatim, so the registry's full list told a
    real campaign that the mock toolkit was available. That is the mock-chain-on-a-GPU hazard
    in the half the typed `toolkit` view did not cover, and two lists describing the same thing
    disagree eventually.
    """
    s = spec("t-narrowed", stages=["mock_generate", "mock_fold"])
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    obs = mgr.observe()

    assert obs.available_tools == ["mock_fold", "mock_generate"]
    assert obs.toolkit is not None and obs.toolkit.ids == obs.available_tools
    assert "mock_noodle" not in obs.available_tools, \
        "a tool the campaign did not enable must not be offered to a reasoner"


async def test_the_stage_path_refuses_a_chain_that_cannot_produce_an_objective(reg, tmp_path):
    """Backlog A8, as a refusal on the new path.

    The legacy `submit` still warns, deliberately: that keeps the old path's behaviour
    unchanged - including the truncated-chain characterization test, which runs a sub-chain on
    purpose - and phase 11 deletes the warning with the path. So the two differ here, and that
    is the point of a strangler rather than an accident.
    """
    s = spec("t-a8-gate", control="roles", max_cycles=3,
             trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(stages=["mock_generate", "mock_design"]), reg)
    res = await mgr.run()

    assert list(res.tree.nodes) == [], \
        "nothing should have been admitted, so nothing was absorbed"
    rejected = [r for r in mgr.prov.read("stages") if r.get("event") == "rejected"]
    assert rejected, "the refusal must be on the record, not only in the return value"
    assert any("reports" in r["rejected"]["reason"] for r in rejected), \
        f"the reason must name the unproducible metric: {[r['rejected'] for r in rejected]}"


async def test_a_stage_writes_one_durable_task_record_per_deployed_task(reg, tmp_path):
    """Task-keyed and campaign-global, because nothing durable was before this.

    The job ledger folds on `job_id`, per-task data existed only nested inside a RunOutcome,
    and a task id was unique only within one TaskGraph - so to find one task you had to know
    its run and scan a list. asyncflow cannot help: it tags tasks with `workflow_id` and
    exposes no lookup by it, which is why the caller's own table is the only index that can
    exist.
    """
    s = spec("t-taskreg", control="roles", max_cycles=2,
             trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    snap = mgr.executor.tasks.snapshot()
    assert snap, "the registry must be written, not merely available"
    assert all(r.task_id.startswith(f"{s.campaign_id}/") for r in snap.values()), \
        "a task id unique only inside one graph is what made DEFER and CANCEL unexpressible"
    assert len({r.task_id for r in snap.values()}) == len(snap), "no collisions across runs"
    assert {r.state for r in snap.values()} == {TaskState.DONE}, \
        "states must leave DEPLOYED, or the registry answers only `what was deployed`"
    assert mgr.executor.tasks.open_tasks() == [], \
        "and nothing is left open, which is the question a restart asks"
    assert all(r.objectives for r in snap.values()), \
        "every task records what it was for - that is what makes an orphan decidable"


async def test_a_cancel_only_stage_is_not_an_error_but_runs_nothing(reg, tmp_path):
    """Housekeeping is a legitimate Stage with nothing to run.

    Composing an empty graph to reject it would turn cancelling orphaned work into a
    rejection, and the Planner would have to avoid asking.
    """
    s = spec("t-cancel-only", control="roles", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    await ex.start()
    try:
        with pytest.raises(SubmissionRejected) as caught:
            await ex.submit_stage(Stage(cancels=["nothing-here"]))
        assert caught.value.failure.gate == "coverage"
        assert caught.value.failure.transient is True, \
            "nothing is wrong with the campaign; this Stage simply had no work"
        assert ex.dispatched == 0
    finally:
        await ex.shutdown()


async def test_a_two_input_node_receives_each_input_on_its_declared_port(reg, tmp_path):
    """The defect this phase exists for, and it could not be expressed before `mock_join`.

    `TaskNode.inputs` - the typed port map the composer computes and gate 1 type-checks - was
    read by the validator and discarded by the dispatcher, which keyed inputs `dep0..depN`
    positionally. Every real adapter then recovered its artifact by SCANNING the payloads for
    one whose `outputs` contained the port it wanted. That works only while a node has exactly
    one upstream dependency: with two typed inputs the scan returns whichever dep came first,
    so the graph type-checks at composition and mis-wires at runtime, silently.

    An Aim hierarchy with real dependencies hits that on its first branch, which is why it is
    fixed before the Runner and before anything composes a branching Stage. `mock_join`
    asserts what it was handed rather than reporting it, so a mis-wire fails an integrity gate
    instead of producing a plausible number.
    """
    g = TaskGraph()
    g.add(TaskNode(id="gen", tool="mock_generate", seed=1))
    g.add(TaskNode(id="des", tool="mock_design", deps=["gen"],
                   inputs={"backbone": "gen.designs"}, seed=2))
    # Both ports wired explicitly, and deliberately in an order that does NOT match the
    # dependency order: `backbone` comes from the FIRST dep and `sequences` from the second,
    # so a positional reading gets them the wrong way round.
    g.add(TaskNode(id="join", tool="mock_join", deps=["gen", "des"],
                   inputs={"backbone": "gen.designs", "sequences": "des.sequences"},
                   seed=3))

    flow, _ = await make_engine("concurrent", {"workers": 3}, work_dir=str(tmp_path))
    try:
        d = Dispatcher(flow, reg)
        results = await d.collect(d.submit(g, run_id="r-join"))
    finally:
        await flow.shutdown()

    assert results.failures == {}, results.failures
    joined = results.per_task["join"]
    assert joined.metrics["wired_correctly"] == 1.0, (
        "each input must arrive on its declared port; a positional reading swaps them")
    assert joined.metrics["inputs_seen"] == 2.0
    assert joined.qc.verdict is not QCVerdict.FAIL


async def test_an_ordering_only_dependency_still_reaches_the_adapter(reg, tmp_path):
    """A real edge with no typed port behind it keeps its `dep{i}` key.

    Otherwise wiring by port would silently drop the dependency's payload, and an adapter that
    reads `inputs` for anything other than a declared port would stop seeing it.
    """
    g = TaskGraph()
    g.add(TaskNode(id="gen", tool="mock_generate", seed=1))
    g.add(TaskNode(id="also", tool="mock_generate", seed=2))
    # `des` declares one typed input but depends on two nodes: the second is ordering only.
    g.add(TaskNode(id="des", tool="mock_design", deps=["gen", "also"],
                   inputs={"backbone": "gen.designs"}, seed=3))

    flow, _ = await make_engine("concurrent", {"workers": 3}, work_dir=str(tmp_path))
    try:
        d = Dispatcher(flow, reg)
        results = await d.collect(d.submit(g, run_id="r-order"))
    finally:
        await flow.shutdown()

    assert results.failures == {}, results.failures
    assert "des" in results.per_task


async def test_deleting_an_objective_makes_its_pending_tasks_cancellable(reg, tmp_path):
    """DELETED -> orphan -> CANCEL, end to end, through the roles the architecture names.

    The executor REPORTS orphans on the observation; the Planner DECIDES to cancel by putting
    them in `Stage.cancels`; the executor acts on that at admission. The split is the point:
    computing the fact needs both the task registry and the applied Spec, which only the
    executor sees, while cancelling is a planning decision.

    *Every* objective must be deleted, not any - which is why `TaskMapping.objectives` is a
    list. A task serving one live objective among three dead ones is still wanted, and with one
    objective per task the question could not be asked.
    """
    s = spec("t-orphan", control="roles", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    await ex.start()
    try:
        aim = Aim(statement="a")
        keep, drop = SpecObjective(aim=aim.id), SpecObjective(aim=aim.id)
        ex.publish_spec(Spec().apply(SpecRevision(new_aims=[aim],
                                                  new_objectives=[keep, drop])))
        # Two pending tasks: one serving both objectives, one serving only the doomed one.
        ex.tasks.record_task(TaskRecord(task_id="t-both", campaign_id=s.campaign_id,
                                        objectives=[keep.id, drop.id],
                                        state=TaskState.PENDING))
        ex.tasks.record_task(TaskRecord(task_id="t-doomed", campaign_id=s.campaign_id,
                                        objectives=[drop.id], state=TaskState.PENDING))
        assert ex.observe().orphan_tasks == [], "nothing is deleted yet"

        ex.apply_revision(SpecRevision(deleted=[drop.id]))
        assert ex.observe().orphan_tasks == ["t-doomed"], (
            "a task serving one live objective among dead ones is still wanted")

        # The Planner's decision, as it reaches the executor.
        ex._apply_cancels(Stage(cancels=["t-doomed"]))
        snap = ex.tasks.snapshot()
        assert snap["t-doomed"].state is TaskState.CANCELLED
        assert snap["t-both"].state is TaskState.PENDING
        assert ex.observe().orphan_tasks == [], "a cancelled task is no longer open work"
    finally:
        await ex.shutdown()


async def test_a_running_task_asked_to_stop_is_recorded_orphaned_not_cancelled(reg, tmp_path):
    """Cancellation is advisory once a callable has started, so the record must not lie.

    Measured rather than assumed: the concurrent backend's `Future.cancel()` returns False once
    the callable is running and asyncflow discards that answer, and `impress`'s own
    `kill_parent` cancels a pipeline's asyncio Task without reaching the backend. Reclaiming
    the GPU is backlog C4 and unsolved - so a RUNNING task asked to stop is ORPHANED, which
    says "we wanted this stopped and could not", rather than CANCELLED, which would claim we
    did.
    """
    s = spec("t-advisory", control="roles", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    await ex.start()
    try:
        ex.tasks.record_task(TaskRecord(task_id="t-running", campaign_id=s.campaign_id,
                                        objectives=["o1"], state=TaskState.RUNNING))
        ex._apply_cancels(Stage(cancels=["t-running"]))
        assert ex.tasks.snapshot()["t-running"].state is TaskState.ORPHANED
    finally:
        await ex.shutdown()


async def test_a_mock_draw_does_not_depend_on_what_its_inputs_are_called(reg, tmp_path):
    """The same lesson twice, now pinned.

    `_upstream` once seeded on `str(inputs)`, so adding a field to `GateResult` reshuffled
    every downstream draw. The keys were still in the seed, so when the dispatcher started
    keying inputs by declared port instead of `dep0..depN`, every draw reshuffled again and
    the demo campaign's cycle count changed - a rename of the wiring altering the science.

    A mock's draw must be a function of what upstream PRODUCED, never of how it was addressed.
    """
    payload = {"tool": "mock_generate", "outputs": {"designs": "backbone[1]"},
               "metrics": {"designability": 0.9}, "qc": {"verdict": "pass"}}
    positional = _upstream({"dep0": payload})
    by_port = _upstream({"backbone": payload})
    assert positional == by_port, "the key must not reach the seed"

    # And an added QC field must not either - the original form of this bug.
    noisier = dict(payload, qc={"verdict": "pass", "new_field": 1})
    assert _upstream({"backbone": noisier}) == by_port


async def test_a_task_reports_its_own_wall_clock(reg, tmp_path):
    """Backlog G8: nothing timed a task, and every cost figure was the estimate repeated.

    `TaskResult.cost` was `dict(self.spec.cost_model.cost)` - a copy of the spec - and the job
    ledger recorded that same figure. The consequences were measurable from outside anyway:
    GPU-busy at most 17% of billed GPU time, CPU efficiency around 42%, three of four GPUs
    never holding work. None of it was attributable to a task.
    """
    s = spec("t-timed", control="roles", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    telemetry = list(mgr.prov.read("tasks"))
    assert telemetry, "per-task telemetry must be written, not merely available"
    timed = [r for r in telemetry if r.get("wall_s") is not None]
    assert timed, "every settled task carries its own wall clock"
    assert all(r["wall_s"] > 0 for r in timed)
    assert all(set(r["phases"]) == {"pre_process", "parameterize", "run", "post_process"}
               for r in timed), (
        "per-phase, so import time is separable from work - `import pyrosetta` alone took "
        "471s off HDD against a 300s budget, and a timeout names a budget, not a cause")
    assert all(r["host"] and r["pid"] for r in timed), \
        "recorded where the task ran, which is the only place that can know"


async def test_declared_and_measured_cost_are_both_recorded_and_distinct(reg, tmp_path):
    """Two numbers, not one quietly redefined.

    The declared figure feeds gate 5 and the untrusted-pattern cap, and those REFUSE graphs -
    so it must stay conservative rather than drift toward measurement (backlog A11). Settling
    the measured figure instead would change what admission refuses for every campaign at
    once.
    """
    s = spec("t-twocosts", control="roles", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    rows = [r for r in mgr.prov.read("tasks") if r.get("wall_s") is not None]
    assert all(r["cost_estimated"] for r in rows), "the declared figure is still recorded"
    assert all("wall_s" in r["cost_measured"] for r in rows)
    # And the budget settled on the DECLARED figure, which is what keeps refusals comparable.
    assert mgr.budget.spent, "something was charged"
    declared_total = sum(v for r in rows for d, v in r["cost_estimated"].items()
                         if d == "gpu_hours")
    assert abs(mgr.budget.spent.get("gpu_hours", 0.0) - declared_total) < 1e-9, \
        "the ledger must still settle the declared estimate, not the measurement"


async def test_a_property_names_the_tool_that_reported_it(reg, tmp_path):
    """Defect (k): every metric from every tool carried `mock_toolkit`/authority 10.

    That made the whole predicted-versus-measured machinery unreachable from the normal path.
    Decision 0012 turns on a property knowing where it came from: `outranks` compares
    authority, so an assay can supersede an ML prediction only if the prediction says it is
    one.
    """
    s = spec("t-sources", control="roles", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, ThresholdPolicy(), reg)
    await mgr.run()

    sources = {p.source.name for n in mgr.tree.nodes.values() for p in n.properties.values()}
    assert sources, "the campaign produced properties"
    assert "mock_toolkit" not in sources, "the hardcoded source is gone"
    assert sources <= set(reg.ids()), f"every source must be a real tool id: {sources}"
    assert all(p.source.authority == AUTHORITY_ML_PREDICTOR
               for n in mgr.tree.nodes.values() for p in n.properties.values()), (
        "a mock ML predictor must not claim an authority that would outrank an assay")


async def test_two_campaign_instances_with_different_salts_draw_differently(reg, tmp_path):
    """Backlog G7: run labels restart at `r0001`, so without a salt every job drew the same.

    17 designs on record turned out to be 5 independent folds sampled about three times each.
    Seeding fixes length and biases fold - same-seed pairs measured median TM 0.82 against
    0.28 across seeds - and does not reproduce coordinates, so this is variance reduction
    rather than exact pairing. An empty salt reproduces the old behaviour exactly, which is
    what keeps every recorded figure comparable.
    """
    def seeds(salt):
        g = Composer(reg, seed_salt=salt).compose(
            ExperimentIntent(goal="g", stages=CHAIN, replicas=2), "r0001")
        return sorted(n.seed for n in g.nodes.values())

    assert seeds("exp-a") != seeds("exp-b"), "different experiments must draw differently"
    assert seeds("exp-a") == seeds("exp-a"), "and the same salt must reproduce"
    assert seeds("") == sorted(
        Composer(reg).compose(
            ExperimentIntent(goal="g", stages=CHAIN, replicas=2), "r0001").nodes[k].seed
        for k in Composer(reg).compose(
            ExperimentIntent(goal="g", stages=CHAIN, replicas=2), "r0001").nodes), (
        "an empty salt must reproduce the pre-G7 draw exactly")


async def test_a_refinement_stage_starts_from_its_parents_artifacts(reg, tmp_path):
    """The mechanism the ten-sequence Goal needs, and which did not exist.

    `ExperimentIntent.parent_node` set `DesignNode.parent` and nothing else, so "exploit a
    node" re-ran its RECIPE rather than refining its STRUCTURE. The reference pipeline's median
    pLDDT of 94.4 comes from a partial-diffusion loop - `num_refine_cycles`, `rfd3_partial_t` -
    feeding a parent's structure back into the generator, and no campaign here could express
    that. Across every recorded run `complex_plddt` is 0.426 / 0.486 / 0.507 against a 0.75
    bound: 0 of 3, which is a missing mechanism rather than bad luck.

    Matched by declared TYPE, not by name: a parent's artifacts are named for the port that
    produced them and a consumer names them for its own purpose.
    """
    s = spec("t-refine", control="roles", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    await ex.start()
    try:
        parent = DesignNode()
        parent.artifacts = {"designs": ArtifactRef(type=ArtifactType.BACKBONE,
                                                   value="parent-backbone")}
        ex.tree.add(parent)

        # `mock_design` takes a Backbone. As the root of a refinement Stage it has no upstream
        # task, so without the parent feed its input port would be unsatisfied.
        stage = Stage(parent_node=parent.id,
                      tasks=[TaskMapping(task_id="r0_s0_mock_design", tool="mock_design",
                                         objectives=["o1"], lineage=0)])
        graph = ex.composer.compose_stage(
            stage, "r0001", parent_artifacts=ex._artifacts_of(stage.parent_node))

        node = graph.nodes["r0_s0_mock_design"]
        assert node.deps == [], "it is a root: nothing upstream in this graph"
        assert "backbone" in node.seed_inputs, (
            "the parent's Backbone must satisfy the declared `backbone` port")
        assert node.seed_inputs["backbone"].value == "parent-backbone"

        # And the request a task actually receives resolves it through the same accessor as a
        # real upstream dependency, so an adapter needs no special case.
        req = TaskRequest(tool="mock_design", seed_inputs=dict(node.seed_inputs))
        assert req.input_ref("backbone").value == "parent-backbone"
    finally:
        await ex.shutdown()


async def test_an_upstream_payload_beats_a_seeded_one(reg):
    """A refinement's later stages consume what THIS run produced, not what its parent did.

    Otherwise a chain would refine the parent at every stage instead of once at the root, and
    the loop would not be a loop.
    """
    upstream = {"outputs": {"designs": ArtifactRef(type=ArtifactType.BACKBONE,
                                                   value="this-run")}}
    req = TaskRequest(tool="mock_design", inputs={"backbone": upstream},
                      input_ports={"backbone": "designs"},
                      seed_inputs={"backbone": ArtifactRef(type=ArtifactType.BACKBONE,
                                                           value="parent")})
    assert req.input_ref("backbone").value == "this-run"


async def test_a_refinement_naming_an_unknown_node_gets_no_artifacts(reg, tmp_path):
    """An unknown parent is a graph with unsatisfied roots, which gate 1 is the place to refuse.

    The composer is not where identity is checked, and raising there would turn a Planner's
    stale reference into a crash rather than a rejection it can answer.
    """
    s = spec("t-refine-unknown", control="roles", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, ThresholdPolicy(), reg).executor
    assert ex._artifacts_of("n-does-not-exist") == {}
    assert ex._artifacts_of(None) == {}
