"""T2 - mock campaign. A complete campaign end to end on a laptop.

Real manager, real policy, real composer, real validator, real state and provenance,
with ConcurrentExecutionBackend and mock tools. Exercises every layer above the substrate.
"""
import asyncio
import json

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
from impress_a.policy import registry as reasoners
from impress_a.policy.planners import ExternalPlanner, ThresholdPlanner
from impress_a.policy.registry import RolePair
from impress_a.policy.specifiers import ExternalSpecifier, ThresholdSpecifier
from impress_a.policy.wrappers import StageGuard
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


def _pair(stages: list[str] | None = None) -> RolePair:
    """Model D's two halves, which since phase 11 is what model D *is*.

    `ThresholdPolicy` and the `decide(obs) -> Decision` contract it implemented were deleted
    with the legacy path. Most of this file's campaigns want "a reasoner that drives a
    complete campaign deterministically", which is what this is.
    """
    return RolePair(ThresholdSpecifier(),
                    ThresholdPlanner(stages=stages or CHAIN))


class _SubmitsAFixedChain:
    """A `conduct` reasoner that submits one chain, over and over, and judges nothing.

    Needed because `ThresholdPlanner` **refuses** to plan a chain that cannot measure any of
    the campaign's objectives - it finds no producer, so there is no Stage - which is the
    right behaviour and leaves the executor-level rules that deal with such a chain with no
    way to be reached. Those rules are real: a run that could not have moved the front is not
    evidence of stagnation (backlog G1), the exemption is bounded, and a graph that cannot
    produce a declared objective is refused (backlog A8).

    So a truncated chain now has to be **deliberate**, and this is what makes it so.
    """

    name = "submits-a-fixed-chain"

    def __init__(self, stages: list[str], runs: int = 99, replicas: int = 1) -> None:
        self.stages, self.runs, self.replicas = stages, runs, replicas
        self.rejections: list = []

    async def conduct(self, session) -> None:
        from impress_a.core.session import CampaignStopped, SubmissionRejected

        for _ in range(self.runs):
            try:
                run = await session.submit(ExperimentIntent(
                    goal="g", stages=self.stages, replicas=self.replicas))
            except SubmissionRejected as rejected:
                self.rejections.append(rejected.failure)
                continue
            except CampaignStopped:
                return
            try:
                await session.result(run)
            except CampaignStopped:
                return


class _SubmitsAFixedStage:
    """A `conduct` reasoner that submits one hand-built Stage and records the refusal.

    The Stage path is where backlog A8 became a refusal rather than a warning, and reaching it
    needs a Stage whose tasks cover every READY objective - so the Reviewer's coverage gate
    passes - while the chain cannot produce the campaign's DECLARED objectives, which is what
    the A8 check reads. That is the real shape of the failure: a Planner planning faithfully
    against a Spec that does not cover what the campaign is for.

    `ThresholdPlanner` cannot be used for it, because it refuses to plan a chain with no
    producer at all - correctly. So the Stage is built here.
    """

    name = "submits-a-fixed-stage"

    def __init__(self, stages: list[str]) -> None:
        self.stages = stages
        self.rejections: list = []

    async def conduct(self, session) -> None:
        from impress_a.core.session import CampaignStopped, SubmissionRejected
        from impress_a.core.spec import Aim, Spec, SpecObjective, SpecRevision, Stage, TaskMapping

        aim = Aim(statement="whatever this chain can measure")
        objective = SpecObjective(aim=aim.id, statement="run the chain",
                                  targets=["ss_fraction"])
        spec = Spec()
        spec.apply(SpecRevision(new_aims=[aim], new_objectives=[objective]))
        await session.publish_spec(spec)

        for _ in range(3):
            stage = Stage(spec_generation=spec.generation, tasks=[
                TaskMapping(task_id=f"l0_s{i}_{tool}", objectives=[objective.id], tool=tool)
                for i, tool in enumerate(self.stages)])
            try:
                await session.submit_stage(stage)
            except SubmissionRejected as rejected:
                self.rejections.append(rejected.failure)
            except CampaignStopped:
                return
        await session.stop("submitted all it had")


@pytest.fixture(scope="module")
def reg():
    return Registry().load()


@pytest.mark.parametrize("letter", ["A", "B", "D"])
async def test_autonomous_models_reach_termination(reg, letter):
    """Every autonomous model, as the halves the registry actually builds.

    By letter rather than by class: a model IS its two halves since phase 11, and building
    them through `build_roles` is what the CLI does - so this exercises the wiring a campaign
    uses rather than a hand-assembled pair that could drift from it.
    """
    options = reasoners.ReasonerOptions(stages=CHAIN, max_cycles=4)
    mgr = CampaignManager(spec(f"t-{letter}"),
                          reasoners.build_roles(letter, options=options), reg)
    res = await mgr.run()
    assert res.stop_reason, "must terminate with a stated reason"
    assert len(res.tree) > 0, f"{letter} produced no candidates"
    assert res.cycles <= 4


async def test_the_null_model_stops_immediately(reg):
    """And it needs no special case anywhere, which is the point of the null halves.

    `NullSpecifier` returns an empty Spec, `Spec.complete()` is "nothing is open", so the
    Listener stops the campaign through the designed path. `NullPolicy` had to return a `Stop`
    decision, which is a sentence the driver had to recognise.
    """
    res = await CampaignManager(spec("t-null"),
                                reasoners.build_roles("null"), reg).run()
    assert res.cycles == 0 and len(res.tree) == 0
    assert res.stop_reason == "every spec objective satisfied"


async def test_a_campaign_writes_nothing_into_the_cwd(reg, tmp_path, monkeypatch):
    """asyncflow puts its session dir in the CWD unless told otherwise. That is how 516
    empty `asyncflow.session.*` dirs piled up in the checkout, and on Delta it scattered
    them beside, rather than inside, each campaign's own output."""
    cwd, root = tmp_path / "cwd", tmp_path / "root"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    s = spec("t-cwd", max_cycles=1)
    s.root = str(root)
    await CampaignManager(s, _pair(), reg).run()
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


async def test_the_guard_corrects_every_stage(reg):
    """The unconditional external guard, now on the Planner half.

    `RuleCorrectionsPolicy` corrected an `ExperimentIntent`; `StageGuard` corrects a `Stage`,
    which is a different object with lineages and per-task parameters. It is also narrower on
    purpose: two of the three corrections its predecessor made are now enforced where nothing
    can bypass them - the replica cap in the executor, and a task serving no objective at the
    Reviewer's coverage gate - and `--no-guard` could switch both off.
    """
    pair = RolePair(ThresholdSpecifier(),
                    StageGuard(ThresholdPlanner(stages=CHAIN, base_replicas=99),
                               forbid_tools=("mock_noodle",), max_lineages=2))
    await CampaignManager(spec("t-guard"), pair, reg).run()
    assert pair.planner.refusals, "the guard must have trimmed an over-wide request"


async def test_provisional_results_are_marked_suspect(reg):
    """A novel composition pattern runs, but nothing unreviewed is quietly believed."""
    s = spec("t-suspect", max_cycles=1)
    mgr = CampaignManager(s, _pair(), reg)
    mgr.trust.patterns.clear()
    res = await mgr.run()
    nodes = [n for n in res.tree if n.qc.verdict is not QCVerdict.FAIL]
    assert nodes and all(n.qc.verdict is QCVerdict.SUSPECT for n in nodes)


async def test_external_steering_and_post_termination_measurement(reg):
    """Model C in one process, which is the arrangement model C has.

    `plane.steer` reaches `manager.policy`, so the halves have to be in the process serving
    the plane - `impress-a serve <spec> --model C`. The directive shape changed with the
    halves: a `role` key routes it, and the Planner's keys are the engine's vocabulary.
    """
    pair = RolePair(ExternalSpecifier(timeout_s=8.0),
                    ExternalPlanner(stages=CHAIN, timeout_s=8.0, on_timeout="stop"))
    mgr = CampaignManager(spec("t-C", max_cycles=2), pair, reg)
    plane = InProcessControlPlane()
    cid = plane.register(mgr)

    async def caller():
        for _ in range(2):
            await asyncio.sleep(0.3)
            obs = await plane.observe(cid)
            assert obs.campaign_id == cid, "caller sees the policy's own observation"
            await plane.steer(cid, {"role": "specifier", "kind": "hold"})
            await plane.steer(cid, {"role": "planner", "stages": CHAIN, "replicas": 2})
        await asyncio.sleep(0.3)
        await plane.steer(cid, {"role": "planner", "kind": "stop",
                                "reason": "caller done"})

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
    mgr = CampaignManager(spec("t-prov"), _pair(), reg)
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
    mgr = CampaignManager(s, _pair(), reg)
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
    mgr = CampaignManager(s, _pair(), reg)
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
    mgr = CampaignManager(spec("t-cursor", max_cycles=2), _pair(), reg)
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


def _trust_the_chain(mgr, reg, widths=(1, 2, 3)) -> list[str]:
    """Assert trust for the chain at each width a policy might ask for.

    Needed because an untrusted pattern is held to **one instance in flight**, deliberately,
    so a campaign whose every submission is one novel shape cannot overlap anything - which
    makes a concurrency test impossible to write without either trusting something or
    accepting a defect.

    And a defect is what these tests used to rely on. `on_rejected` answered the interlock's
    one-instance rejection by **truncating the chain**, which produces a different shape with
    a different signature - so the second instance was admitted as a different pattern, and
    the rule the test next asserted was being defeated by the correction that got it there.
    Removing the truncation (job 22675512, where it took the only producer of two of four
    objectives off the graph) made that visible: both tests stopped admitting anything at all.

    Replica multiplicity enters the signature, so each width is its own pattern and each has
    to be asserted (backlog A10).
    """
    from impress_a.compose.composer import Composer
    from impress_a.compose.interlock import PatternRecord

    sigs = []
    for width in widths:
        sig = Composer(reg).compose(
            ExperimentIntent(goal="g", stages=CHAIN, replicas=width), "probe"
        ).pattern_signature()
        mgr.trust.patterns[sig] = PatternRecord(signature=sig, trusted=True, clean_runs=3)
        sigs.append(sig)
    return sigs


async def test_concurrency_holds_several_experiments_in_flight(reg, tmp_path):
    """The whole point: submission no longer blocks the reasoner.

    Previously `dispatcher.run` was awaited where it was submitted, so exactly one graph
    could exist at a time and a cycle could not end until the slowest lineage finished.
    """
    s = spec("t-conc", max_cycles=6)
    s.root, s.concurrency = str(tmp_path), 3
    mgr = CampaignManager(s, _pair(), reg)
    _trust_the_chain(mgr, reg)
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
    mgr = CampaignManager(s, _pair(), reg)
    # Width 2 and 3 only. The policy explores at 3 and exploits at 2, so trusting those two
    # lets experiments overlap at all - and leaving width 1 untrusted means an UNTRUSTED
    # pattern is in play for the rule below to bite on, which is the only way this test can
    # observe the thing it is about.
    _trust_the_chain(mgr, reg, widths=(2, 3))
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
    mgr = CampaignManager(s, _pair(), reg)
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
    mgr = CampaignManager(s, _pair(), reg)
    res = await mgr.run()
    assert res.runs >= 1

    done = [r for r in mgr.runs.list_runs() if r.state.is_terminal]
    assert done, "runs must reach a terminal state"
    rid = done[0].run_id

    # A NEW manager over the same root - nothing shared but the log on disk.
    fresh = CampaignManager(s, _pair(), reg)
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
    mgr = CampaignManager(s, _pair(), reg)
    await mgr.run()

    fresh = CampaignManager(s, _pair(), reg)
    # The pair's name, which is what `getattr(policy, "name")` now returns: a model is two
    # halves and the record says which two, because "model B" and "B's specifier with D's
    # planner" are different campaigns.
    report = fresh.runs.reattach(expected_policy="threshold-spec+threshold-plan")
    assert report.campaign_id == "t-reattach"
    assert report.policy == "threshold-spec+threshold-plan", \
        "the launching methodology must be on record, and that is now both halves"
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
    mgr = CampaignManager(s, _pair(), reg)
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
    mgr = CampaignManager(s, _pair(), reg)
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
    ex = CampaignManager(s, _pair(), reg).executor
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


async def test_a_reasoner_ingests_each_collected_run_exactly_once(reg, tmp_path):
    """Collecting an outcome belongs to whoever decides on it - exactly once.

    `interpret` used to be called by the executor, on the executor's own reference to the
    policy. That worked only while the reasoner shared its process: driven through a remote
    session the executor holds a placeholder, so the hook fired against the wrong object or
    not at all, and a policy that accumulated across runs silently stopped accumulating.

    `interpret` is gone with the `decide` contract (phase 11) and the fix is structural rather
    than a hook: the **Listener** collects every outcome and ingests it into its own
    `DataRegistry`, on its own side of any process boundary, and the executor never reaches
    into a reasoner at all. That is `policy/driver.py`'s own ruling about who collects an
    outcome, surviving the driver's deletion. This pins both halves of the move: a duplicate
    would mean something restored a second ingestion path, and a Specifier counting hits
    against realized data would then double-count.
    """
    s = spec("t-ingest", max_cycles=3)
    s.root = str(tmp_path)
    pair = _pair()
    mgr = CampaignManager(s, pair, reg)
    res = await mgr.run()
    driver = mgr._roles_driver

    assert driver is not None and driver.data.realized, \
        "the reasoner ingested nothing - it is not seeing its own results"
    runs = [d.from_run for d in driver.data.realized if d.from_run]
    settled = {r["run"] for r in mgr.prov.read("executions")}
    assert set(runs) == settled, (
        f"the reasoner saw {sorted(set(runs))} of the runs the executor settled: "
        f"{sorted(settled)}")
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
        s, _SubmitsAFixedChain(["mock_generate", "mock_design"], runs=s.max_cycles),
        reg).run()

    assert len(res.tree) > 0, "the runs happened"
    assert all(n.qc.verdict is not QCVerdict.FAIL for n in res.tree), \
        "and QC passed - nothing is wrong with the science"
    assert res.front == [], "the front is still empty: no node carries sc_rmsd or iptm"
    assert not res.stop_reason.startswith("stagnation:"), res.stop_reason
    assert res.cycles == s.max_cycles, (
        f"every run it was given must be used - the reasoner's own budget is what ends it, "
        f"not the counter: {res.cycles} of {s.max_cycles}, stopped by {res.stop_reason!r}")
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
    # A reasoner that never stops itself, so the counter is what ends it.
    res = await CampaignManager(s, _SubmitsAFixedChain(CHAIN), reg).run()

    assert res.stop_reason.startswith("stagnation:"), res.stop_reason
    assert res.cycles < s.max_cycles, "the counter stopped it early, as it should"


class _Backtracker:
    """A `conduct` reasoner that branches from its first result, then submits once more.

    Was a `decide` policy returning `Backtrack`, which is not a thing any reasoner returns
    now: backtracking from an earlier node is `session.backtrack` for a `conduct` reasoner and
    `SpecObjective.parent_node` for a role pair. The two tests it carried were about the
    deleted driver's own counting - that it charged a backtrack as a cycle (jobs 22702568,
    22726105 and 22728140 each asked for 6 and ran 5), and that it stopped a policy which only
    ever backtracked. Neither defect can recur in a driver that does not exist, so what is
    pinned below is the operation that does: a backtrack branches the tree and spends no run.
    """

    name = "backtracker"

    def __init__(self) -> None:
        self.branched_from: str | None = None

    async def conduct(self, session) -> None:
        run = await session.submit(ExperimentIntent(goal="g", stages=CHAIN, replicas=1))
        outcome = await session.result(run)
        self.branched_from = outcome.nodes[0] if outcome.nodes else None
        if self.branched_from:
            await session.backtrack(self.branched_from, "test")
        await session.result(
            await session.submit(ExperimentIntent(goal="g", stages=CHAIN, replicas=1)))
        await session.stop("backtracker done")


async def test_a_backtrack_branches_the_tree_and_spends_no_run(reg, tmp_path):
    """What survives the deleted driver's off-by-one, attached to the operation that remains.

    `max_cycles` counts RUNS, and three Delta jobs asked for 6, backtracked once and ran 5
    because the driver charged the branch as a cycle. The driver is gone; `session.backtrack`
    is not, and it must still be free: two submissions and one backtrack is two runs, and the
    branch has to appear in the tree as a parent edge rather than as a third candidate.
    """
    s = spec("t-bt", max_cycles=5, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    reasoner = _Backtracker()
    res = await CampaignManager(s, reasoner, reg).run()

    assert res.runs == 2, f"two submissions, one backtrack: {res.runs} runs"
    assert reasoner.branched_from, "the reasoner never saw a node to branch from"
    branched = [r for r in res.tree if r.parent == reasoner.branched_from]
    assert branched, (
        f"nothing in the tree descends from {reasoner.branched_from} - a backtrack must "
        f"branch the population rather than discard it (ADR 0004)")


# ---------------------------------------------------------------------------
# The role pipeline.
#
# `test_roles_pipeline_reproduces_the_legacy_campaign` lived here and is DELETED, because its
# purpose is finished rather than because it became inconvenient. It ran the same policy down
# both control paths - `legacy` and `roles` - and compared the tree, the front and the stop
# reason, over five policy shapes. That was the strangler's seam: it is what made every phase's
# failure attributable to that phase, and it is why the split could be trusted before anything
# moved. There is one path now, so there is nothing to compare it against.
#
# `test_a_stage_round_trips_through_an_intent` is deleted for the same reason: it pinned
# `LegacyPlanner._render` against `_intent_for`, the pair of adapters that let phase 1 avoid
# touching `compose/` and `exec/` at all. Both adapters are gone; `submit_stage` composes a
# Stage directly.
#
# What the parity test protected lives on in two places that are not going anywhere:
# `test_split_process.py::test_a_models_own_halves_reproduce_the_in_process_campaign` compares
# one process against a socket, and `test_remote_session.py` compares a reasoner inside the
# process against one outside it.
# ---------------------------------------------------------------------------

async def test_the_listener_stops_the_campaign_when_every_objective_is_satisfied(reg, tmp_path):
    """The Spec's own stop condition, which no legacy policy could express.

    The bounded objectives here are all met by the first run, so the Spec completes and the
    Listener asks to stop - with its own reason, not the policy's. `max_cycles` is high enough
    that reaching it would prove nothing.
    """
    s = spec("t-spec-complete", max_cycles=20,
             trust_root=str(tmp_path / "trust"))
    s.objectives = [Objective(name="iptm", direction=Direction.MAX, min=0.1),
                    Objective(name="sc_rmsd", direction=Direction.MIN, max=99.0)]
    res = await CampaignManager(s, _pair(), reg).run()

    assert res.stop_reason == "every spec objective satisfied"
    assert res.cycles >= 1


async def test_a_campaign_asked_for_ten_designs_is_not_satisfied_by_one(reg, tmp_path):
    """`target_front` is how many designs clear each bar, and it used to reach nothing.

    The test above is the same campaign without a front target: its bounded objectives are met
    by the first run and the Spec completes. That is right when one design is all the caller
    asked for. It is wrong when the Goal says ten - and a campaign declaring `target_front: 10`
    behaved identically, because `ThresholdSpecifier` left `SatisfactionRule.n` at 1 and the
    declared value reached NOTHING: `target_front` was parsed into `CampaignSpec`, forwarded
    into `ReasonerOptions`, and read by no code anywhere (backlog G11).

    Arm C of the first four-arm smoke ran 24 tasks and stopped at cycle 0 on "every spec
    objective satisfied", correctly, having produced one design where the experiment's endpoint
    counts distinct designs per node-hour. Both Delta arm specs declare `target_front: 10`.

    So: same objectives, same mock tools that clear both bars on the first run, one extra
    declaration - and the campaign must keep going. It stops on `max_cycles` instead, which is
    the point: a yield is something you measure over a budget, not something you stop at the
    first instance of.
    """
    s = spec("t-front-ten", max_cycles=3, target_front=10,
             trust_root=str(tmp_path / "trust"))
    s.objectives = [Objective(name="iptm", direction=Direction.MAX, min=0.1),
                    Objective(name="sc_rmsd", direction=Direction.MIN, max=99.0)]
    s.root = str(tmp_path)
    res = await CampaignManager(s, _pair(), reg).run()

    assert res.stop_reason != "every spec objective satisfied", (
        "ten designs were asked for and the Spec was satisfied by the first one - "
        "target_front reached nothing")
    assert res.stop_reason == "max_cycles=3 reached"
    assert res.cycles == 3, "the campaign must spend its cycles, not stop at the first hit"

    # The count lands on the BOUNDED objectives only. Ten readings of a number nobody has to
    # beat say nothing more than one, which is the ruling the next test down makes.
    goal = Goal(text="g", target_front=10, objectives=[
        Objective(name="iptm", direction=Direction.MAX, min=0.1),
        Objective(name="ddg", direction=Direction.MIN)])
    rules = {o.targets[0]: o.satisfied_when
             for o in (await ThresholdSpecifier().initial_spec(goal)).objectives.values()}
    assert rules["iptm"].n == 10, "a bounded objective carries the Goal's count"
    assert rules["ddg"].n == 1, "an unbounded one ranks; a count would be meaningless"


async def test_the_front_target_reaches_a_remotely_driven_campaign_too(reg, tmp_path):
    """An external caller builds its Goal from the observation and from nothing else.

    So `target_front` has to cross with it. Dropped, a served campaign's Specifier would use
    the default while an in-process one used the spec's - and in the four-arm experiment that
    is arm C stopping at one design while A, B and D run to ten. A difference between arms
    which is not the model is exactly what `impress-a compare`'s one-variable guard refuses,
    and it would have been invisible: every arm would have completed, with plausible numbers.
    """
    s = spec("t-front-remote", max_cycles=1, target_front=10,
             trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
    obs = mgr.executor.observe()
    assert obs.target_front == 10, "the observation must carry what the caller cannot see"

    from impress_a.runtime.roles import goal_from_spec

    goal = goal_from_spec(s)
    assert goal.target_front == 10, "and the in-process Goal must carry it as well"


async def test_an_unbounded_objective_gets_a_measurement_rule_not_a_vacuous_one(reg, tmp_path):
    """`total_score: minimize` is an optimisation target, never a finish line.

    `Objective.satisfied_by` answers True for any value when both bounds are None, which is
    right for ranking - nothing is pruned - and vacuous as a satisfaction rule: a
    `metric_in_range` with no range would finish a campaign the moment its first unbounded
    metric reported anything, which is the bug the parity probe surfaced and the reason
    `SatisfactionRule.is_bounded` exists.

    What an unbounded objective gets instead is `metric_present`: it has no finish line, so
    what the campaign owes it is a MEASUREMENT, without which the front cannot order anything
    by it. So a campaign whose ONLY objective is unbounded does complete after one cycle -
    correctly, and that is asserted here rather than left to be discovered - while a bounded
    one that is never met does not.
    """
    goal = Goal(text="g", objectives=[Objective(name="ddg", direction=Direction.MIN)])
    rules = {o.targets[0]: o.satisfied_when
             for o in (await ThresholdSpecifier().initial_spec(goal)).objectives.values()}
    assert rules["ddg"].kind == "metric_present", \
        "an unbounded objective must not get a range rule with no range in it"
    assert not rules["ddg"].is_bounded

    s = spec("t-spec-unbounded", max_cycles=2, trust_root=str(tmp_path / "trust"))
    s.objectives = [Objective(name="ddg", direction=Direction.MIN)]
    s.root = str(tmp_path)
    res = await CampaignManager(s, _pair(), reg).run()
    assert res.stop_reason == "every spec objective satisfied"
    assert res.cycles == 1, "one measurement is all an unbounded objective can ask for"

    # And the bounded case, which is what "never completes" has to mean.
    hard = spec("t-spec-hard", max_cycles=2, trust_root=str(tmp_path / "trust2"))
    hard.objectives = [Objective(name="ddg", direction=Direction.MIN, max=-99.0)]
    hard.root = str(tmp_path)
    out = await CampaignManager(hard, _pair(), reg).run()
    assert out.stop_reason != "every spec objective satisfied"
    assert "max_cycles" in out.stop_reason


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
        s, _SubmitsAFixedChain(["mock_generate", "mock_design"]), reg).run()

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
    ex = CampaignManager(s, _pair(), reg).executor

    ex._unproductive = 1
    ex._note_progress(_rec(could_reach=True))
    assert ex._unproductive == 0, "a run that could have scored clears the backstop"
    ex._note_progress(_rec(could_reach=False))
    ex._note_progress(_rec(could_reach=False))
    assert ex._unproductive == 2


def _rec(could_reach: bool):
    from types import SimpleNamespace
    return SimpleNamespace(informed_by=0, could_reach_the_front=could_reach)


async def test_the_toolkit_a_reasoner_sees_is_narrowed_to_the_campaigns_stages(reg, tmp_path):
    """Because this is what goes into a model's prompt.

    `available_tools` - a flat list of bare ids beside the typed view - was deleted in phase
    11, and the hazard it carried is why: the oracle rendered it verbatim, so the registry's
    full list told a real campaign that the mock toolkit was available. That is the
    mock-chain-on-a-GPU failure in the half the typed view did not cover, and two lists
    describing the same thing disagree eventually. There is one list now, and it is typed.
    """
    s = spec("t-narrowed", stages=["mock_generate", "mock_fold"])
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
    obs = mgr.observe()

    assert obs.toolkit is not None
    assert obs.toolkit.ids == ["mock_fold", "mock_generate"]
    assert "mock_noodle" not in obs.toolkit, \
        "a tool the campaign did not enable must not be offered to a reasoner"
    assert obs.stages == ["mock_generate", "mock_fold"], \
        "and the campaign's own ORDER, which `toolkit.ids` sorts away"


async def test_the_stage_path_refuses_a_chain_that_cannot_produce_an_objective(reg, tmp_path):
    """Backlog A8, as a refusal on the new path.

    The legacy `submit` still warns, deliberately: that keeps the old path's behaviour
    unchanged - including the truncated-chain characterization test, which runs a sub-chain on
    purpose - and phase 11 deletes the warning with the path. So the two differ here, and that
    is the point of a strangler rather than an accident.
    """
    s = spec("t-a8-gate", max_cycles=3,
             trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    reasoner = _SubmitsAFixedStage(["mock_generate", "mock_design"])
    mgr = CampaignManager(s, reasoner, reg)
    res = await mgr.run()

    assert reasoner.rejections, "the Stage was admitted; A8 is not refusing"
    assert all(f.gate == "coverage" for f in reasoner.rejections), \
        [f.gate for f in reasoner.rejections]
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
    s = spec("t-taskreg", max_cycles=2,
             trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
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
    s = spec("t-cancel-only", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, _pair(), reg).executor
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
    s = spec("t-orphan", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, _pair(), reg).executor
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
    s = spec("t-advisory", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, _pair(), reg).executor
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
    s = spec("t-timed", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
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
    s = spec("t-twocosts", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
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
    s = spec("t-sources", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    mgr = CampaignManager(s, _pair(), reg)
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
    s = spec("t-refine", max_cycles=1, trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, _pair(), reg).executor
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
    s = spec("t-refine-unknown", trust_root=str(tmp_path / "trust"))
    s.root = str(tmp_path)
    ex = CampaignManager(s, _pair(), reg).executor
    assert ex._artifacts_of("n-does-not-exist") == {}
    assert ex._artifacts_of(None) == {}


async def test_a_failed_gate_reaches_tasks_provenance_through_the_executor(reg):
    """A campaign that FAILS a gate must survive reporting it.

    The gap this closes is more useful than the bug that revealed it.
    `test_lying_tool_is_caught_by_qc` is the only test that produces a QC FAIL, and it drives
    `Dispatcher` directly - so `_log_task_telemetry` never runs for it. Every test that does
    go through the executor uses tools that pass. The result was a `failed_gates` expression
    exercised on every task in the suite and never once on a non-empty list, which is how
    `[g.gate for g in task.qc.failed()]` survived to the four-arm smoke and took all four arms
    down with `AttributeError: 'dict' object has no attribute 'gate'` (backlog G9).

    `impress-a validate-tasks` could not have closed this either: a validation pass whose
    Tasks pass their integrity rows produces the same empty list.

    So this runs `mock_noodle` - which completes successfully, reports a confident
    `designability` and has no secondary structure - at the HEAD of a real chain through a
    real `CampaignManager`. It stands in for `mock_generate`: same `Backbone` output, no
    inputs, so the planner can cover the campaign's objectives and actually deploy. A
    noodle-only chain plans nothing and reaps nothing, which is the first way this test was
    written and would have passed against the bug. The test
    asserts the gate name lands in `tasks` provenance. Asserting the NAMES rather than merely
    that nothing raised: a bare non-crash would also pass if the field were silently dropped.
    """
    import pathlib as _pathlib

    chain = ["mock_noodle", "mock_design", "mock_fold", "mock_score"]
    mgr = CampaignManager(spec("t-failed-gates", max_cycles=1), _pair(chain), reg)
    await mgr.run()

    found = list(_pathlib.Path(ROOT).glob("t-failed-gates/**/tasks.jsonl"))
    assert found, f"no tasks provenance under {ROOT}/t-failed-gates"
    rows = [json.loads(ln) for ln in found[0].read_text().splitlines() if ln.strip()]
    assert rows, "tasks.jsonl is empty"

    failing = [r for r in rows if r.get("qc") == "fail"]
    assert failing, "mock_noodle must fail its gate - that is the whole point of the fixture"
    assert any(r["failed_gates"] for r in failing), \
        "a failing task recorded an EMPTY failed_gates list - the names were dropped"
    names = {g for r in failing for g in r["failed_gates"]}
    assert all(isinstance(n, str) for n in names), \
        "gate names, not objects or dicts - the harness reads these without a schema"
    assert "has_secondary_structure" in names, \
        f"the gate that catches a noodle must be named; got {names}"


# ---------------------------------------------------------------------------
# Telling a caller what the campaign is doing, while it does it
# ---------------------------------------------------------------------------


class _RecordingSink:
    """A `CycleSink` that remembers every digest, and can hand back one signal."""

    def __init__(self, signals: list[str] | None = None) -> None:
        self.digests: list = []
        self.signals = list(signals or [])

    async def report(self, digest) -> None:
        self.digests.append(digest)

    async def poll(self) -> str | None:
        return self.signals.pop(0) if self.signals else None


class _BrokenSink:
    """Somebody else's code, reaching into a process that is holding an allocation."""

    def __init__(self) -> None:
        self.calls = 0

    async def report(self, digest) -> None:
        self.calls += 1
        raise RuntimeError("the caller's socket went away")

    async def poll(self) -> str | None:
        raise RuntimeError("and so did its signal channel")


async def test_a_digest_reaches_the_sink_for_each_absorbed_cycle(reg):
    """One report per absorbed cycle, plus the two that bracket the campaign.

    Triggered on the absorption watermark rather than on `cycle`, which is incremented at
    DISPATCH and so counts submissions: a report fired there would carry no results. The
    first and last reports are not optional - the first is the caller's liveness anchor
    before any work exists to describe, and the last is the only one guaranteed to be read,
    because the stores a caller receives these through keep one value per workflow.
    """
    from impress_a.integrations import run_with_sink

    sink = _RecordingSink()
    mgr = CampaignManager(spec("t-digest", max_cycles=3), _pair(), reg)
    result = await run_with_sink(mgr, sink, period_s=0.05)

    assert [d.status for d in sink.digests][0] == "starting"
    assert sink.digests[-1].status == "stopped"
    assert sink.digests[-1].stop_reason == result.stop_reason
    assert sink.digests[-1].stop_reason, "a caller must be told WHY the campaign ended"

    # The watermark only ever advances, and the last report has seen everything absorbed.
    seqs = [d.seq for d in sink.digests]
    assert seqs == sorted(seqs), f"the absorption watermark went backwards: {seqs}"
    assert sink.digests[-1].seq == len(mgr.executor._absorbed)
    assert sink.digests[-1].cycle == mgr.executor.cycle


async def test_the_digest_carries_both_cost_scales_under_distinct_names(reg):
    """Declared and measured are two numbers, and a caller charging a budget wants the second.

    `BudgetLedger.spent` is DECLARED - it is what `reserve` and `settle` work in and what
    gate 5 refuses against, so it is correctly pessimistic, and the declared figures sit
    multiples above measurement on purpose. Reporting it outward as "what we spent" tells an
    enclosing manager the headroom as well as the cost, and its learned-cost estimate then
    converges on a number no run ever consumed (backlog G20).
    """
    from impress_a.integrations import run_with_sink

    sink = _RecordingSink()
    mgr = CampaignManager(spec("t-two-scales", max_cycles=2), _pair(), reg)
    await run_with_sink(mgr, sink, period_s=0.05)

    final = sink.digests[-1]
    assert final.spend, "declared spending must be reported"
    assert final.spend_measured, "measured spending must be reported beside it"
    assert set(final.spend_measured) & set(final.spend), "the two must share dimensions"
    assert final.limits and final.remaining
    # The ledger keeps them apart, and only the declared one bounds the campaign.
    assert mgr.budget.spent_measured and mgr.budget.spent_measured != mgr.budget.spent


async def test_the_digest_omits_the_toolkit_and_the_skill_documents(reg):
    """What it drops is the point.

    The full observation carries every `TaskCard` plus each toolkit's entire `SKILL.md` text,
    the applied `Spec`, and every front node with its properties and QC report - all of it
    static for the campaign, and all of it already given to a caller once at calltime by
    `impress-a offer`. Sending it again every thirty seconds would be sending a campaign's
    description as if it were news.
    """
    import json

    mgr = CampaignManager(spec("t-thin", max_cycles=1), _pair(), reg)
    await mgr.run()

    obs = mgr.observe()
    assert obs.toolkit is not None and obs.toolkit.skills, "the fixture must be meaningful"
    wire = json.dumps(obs.digest().model_dump(mode="json"))
    for skill in obs.toolkit.skills.values():
        assert skill[:200] not in wire, "a SKILL.md reached the wire"
    for absent in ("toolkit", "skills", "qc_gates", "parameters", "properties"):
        assert absent not in wire, f"{absent!r} reached the wire"
    # And it still says the things a caller acts on.
    assert "front_satisfying" in wire and "spend_measured" in wire


async def test_a_sink_that_raises_does_not_stop_the_campaign(reg):
    """The campaign is the thing holding the allocation; a listener is not.

    Same rule as `policy/reasoning._record`, and the opposite of `executor._log`, where an
    unguarded `prov_sink` can still take a campaign down with it (backlog G18).
    """
    from impress_a.integrations import run_with_sink

    broken = _BrokenSink()
    mgr = CampaignManager(spec("t-broken", max_cycles=2), _pair(), reg)
    result = await run_with_sink(mgr, broken, period_s=0.05)

    assert result.stop_reason, "the campaign must have run to its own conclusion"
    assert broken.calls >= 2, "and the sink must really have been called and really failed"


async def test_a_pause_from_the_caller_stops_admission_and_resume_restarts_it(reg):
    """Pause gates ADMISSION, and the digest says which state it is in.

    In-flight work runs to completion, because cancellation is advisory - the concurrent
    backend's `Future.cancel()` returns False once a callable has started, and asyncflow
    discards that answer. So a paused campaign keeps spending for up to one cycle, which is
    what `offer.pause_semantics` declares rather than hides.
    """
    from impress_a.integrations import PAUSE, RESUME, Bridge

    mgr = CampaignManager(spec("t-pause", max_cycles=2), _pair(), reg)
    sink = _RecordingSink(signals=[PAUSE, RESUME])
    bridge = Bridge(mgr, sink, period_s=0.05, tick_s=0.01)

    await bridge._signals()
    assert bridge.paused is True and mgr.executor.paused is True
    assert sink.digests[-1].status == "paused"

    await bridge._signals()
    assert bridge.paused is False and mgr.executor.paused is False
    assert sink.digests[-1].status == "running"


async def test_the_jsonl_sink_keeps_what_the_caller_was_told(reg):
    """A report nobody received used to be lost outright.

    Written beside `provenance/` and not into it: the executor is the only writer there, and a
    tenth provenance kind would make a report look like a campaign record when it is a record
    of what somebody else was told.
    """
    import json

    from impress_a.integrations import JsonlSink, run_with_sink

    mgr = CampaignManager(spec("t-jsonl", max_cycles=2), _pair(), reg)
    sink = JsonlSink(mgr.root)
    await run_with_sink(mgr, sink, period_s=0.05)

    assert sink.path.exists() and sink.path.parent.name == "reports"
    assert "provenance" not in sink.path.parts

    # Append-only, like provenance: a campaign re-run under the same id adds to the record
    # rather than replacing it, so this reads back only the rows THIS run wrote.
    rows = [json.loads(line) for line in sink.path.read_text().splitlines()]
    assert len(rows) >= sink.count >= 2
    mine = rows[-sink.count:]
    assert mine[0]["status"] == "starting" and mine[-1]["status"] == "stopped"
    assert all("ts" in r and "seq" in r for r in mine)


async def test_the_control_plane_and_the_log_both_receive_provenance(reg):
    """Two listeners, neither evicting the other. It used to be one slot.

    `ControlPlane.register` assigned `prov_sink` for its event stream and
    `cli.run_campaign` assigned it for the log heartbeat; neither checked for the other, so
    serving a campaign over HTTP silently turned off its own progress log and the loser left
    no trace of having been displaced (backlog G18).
    """
    seen_a, seen_b = [], []
    mgr = CampaignManager(spec("t-fanout", max_cycles=2), _pair(), reg)
    mgr.prov_sink = lambda cid, kind, rec: seen_a.append((cid, kind))   # the old spelling
    mgr.add_prov_listener(lambda cid, kind, rec: seen_b.append((cid, kind)))
    await mgr.run()

    assert seen_a and seen_b, "both listeners must have been called"
    assert seen_a == seen_b, "both must see the same records, in the same order"
    assert {k for _c, k in seen_a} >= {"campaign", "results"}, \
        "a listener must see what the campaign DID, not only what the plane asked"
    # The old single-slot spelling still names the first listener, so no caller has to move.
    assert mgr.prov_sink is not None


async def test_a_provenance_listener_that_raises_does_not_take_the_campaign_down(reg):
    """A bystander must not be able to kill a run from inside a provenance write.

    This was the most expensive possible place to raise: `_log` is on every settlement and
    every absorption, so a listener that threw aborted a campaign holding an allocation,
    after the work was done and while it was being recorded. `policy/reasoning._record` has
    always guarded its sink; this is the same rule arriving late.
    """
    calls = []

    def broken(cid, kind, rec):
        calls.append(kind)
        raise RuntimeError("the subscriber's socket went away")

    mgr = CampaignManager(spec("t-badlistener", max_cycles=2), _pair(), reg)
    mgr.add_prov_listener(broken)
    result = await mgr.run()

    assert result.stop_reason, "the campaign must have reached its own conclusion"
    assert calls, "and the listener must really have been called"
    assert mgr.executor.prov_dropped == len(calls), \
        "every failure must be counted, so a silently deaf subscriber is discoverable"
