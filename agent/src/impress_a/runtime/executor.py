"""The executor: sole owner of campaign state.

Split out of the manager so that the reasoner stops being the loop body and becomes a
peer. The executor owns the tree, the budget, the trust ledger, provenance, the job
ledger, the engine and the table of runs in flight; the reasoner owns nothing and asks
for everything through `CampaignSession`.

ONE WRITER. Every mutation of campaign state happens here, and every mutating block is
free of `await` - so an observation can never be taken half way through absorbing a run.
That property is a discipline, not something the language enforces: adding an `await`
inside `observe` or `_absorb` would reintroduce torn reads, and they are nearly
impossible to diagnose from provenance afterwards.

The executor also DECIDES termination. The reasoner may request a stop; whether the
campaign has actually ended is not its call, because budget, stagnation and repeated
failure are all facts about state the executor alone holds.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..compose.composer import Composer
from ..compose.interlock import Scrutiny, TrustLedger
from ..compose.validate import SiteCaps, Validator
from ..core.artifacts import Property, PropertySource
from ..core.budget import BudgetLedger
from ..core.decision import (
    CampaignObservation,
    ExperimentIntent,
    PopulationStats,
    RequestHuman,
    ValidationFailure,
)
from ..core.pareto import Objective, pareto_front
from ..core.provenance import ProvenanceLog
from ..core.qc import QCVerdict
from ..core.results import RunOutcome, RunState, RunStatus
from ..core.session import CampaignStopped, SubmissionRejected
from ..core.tree import CampaignTree, DesignNode, NodeStatus
from ..exec.dispatch import Dispatcher, ExecutionResults
from ..exec.ledger import JobLedger
from ..tools.registry import Registry


class CampaignAborted(RuntimeError):
    """Transient infrastructure failure, not a goal or a programming error.

    Adopted from campaign_manager (Phase 3): callers can alert on this differently from
    an unexpected crash.
    """


@dataclass
class CampaignSpec:
    campaign_id: str
    goal: str
    objectives: list[Objective]
    budget: dict[str, float] = field(default_factory=dict)
    max_cycles: int = 10      # turns of the loop; NOT a bound on work once a turn
                              # may submit more than one experiment
    max_runs: int = 0         # submissions; 0 = unbounded. See `max_cycles`.
    concurrency: int = 1      # experiments allowed in flight at once
    stagnation_limit: int = 3
    max_failed_cycles: int = 3
    max_attempts: int = 4              # bounded retry, for a `decide`-style policy
    max_admission_failures: int = 8    # executor-side cap; binds any reasoner
    site: SiteCaps = field(default_factory=SiteCaps)
    backend: str = "concurrent"
    backend_config: dict[str, Any] = field(default_factory=dict)
    root: str = "campaigns/_runs"
    # Where the SITE-scoped trust ledger lives, independent of `root`. Empty keeps the
    # historical `root/_trust`, which is right wherever CWD is stable - a laptop, the test
    # tier. It is wrong the moment something cds per run: `delta_gpu_run.sh` cds into
    # a per-job dir under $WORK_DIR/impress_a_runs, so a relative path resolved per job
    # and the ledger started empty every time. Promotion counts consecutive clean runs
    # within one file, so it was unreachable on Delta from the first run onward and the
    # trusted code path had never executed. `cli.load_spec` fills this from
    # $IMPRESS_A_TRUST_DIR; the launcher exports it beside MPNN_DIR and BOLTZ_CACHE.
    trust_root: str = ""
    # 0 disables: rhapsody's Dragon backend builds `Batch()` synchronously in its own
    # constructor (worker pool, GPU-affinity policies, telemetry) with no `await` points,
    # so a stall there blocks the event loop entirely - no heartbeat, no timeout, nothing
    # - until the whole allocation's walltime is spent. See `exec.backend.make_engine_bounded`.
    backend_startup_timeout_s: float = 0.0
    backend_startup_heartbeat_s: float = 30.0
    # The mirror image, and measured on the reference pipeline rather than assumed: on
    # IMPRESS job 22491438 `flow.shutdown()` never returned after every pipeline had
    # finished. The job sat 60 minutes and had to be cancelled by hand - ~64 GPU-hours,
    # 37% of its billed total, spent after the science was already done. Teardown is the
    # worst place to hang, because the campaign has its results and is throwing them away
    # by never writing the run to completion. 0 disables, as above.
    backend_shutdown_timeout_s: float = 0.0
    # WHICH tools this campaign is about. Without it every policy falls back to its own
    # default chain - which is the mock one - so a campaign naming real toolkits would
    # load them, validate them, and then run mocks.
    stages: list[str] = field(default_factory=list)
    # Campaign-level tool parameters: the ligand, the contig, anything that describes
    # the SCIENTIFIC QUESTION rather than the search strategy. Merged beneath whatever
    # a policy asks for, so a policy never has to know a tool's parameter names.
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    replicas: int = 0         # cap on lineages per experiment; 0 = policy decides


@dataclass
class CampaignResult:
    campaign_id: str
    cycles: int               # turns of the loop
    stop_reason: str
    front: list[DesignNode]
    tree: CampaignTree
    corrections: list[str] = field(default_factory=list)
    runs: int = 0             # experiments submitted


@dataclass
class RunRecord:
    """One submitted experiment, from admission through to absorption.

    The signature and scrutiny ride here rather than in a loop variable: interlock
    bookkeeping has to apply to the run that actually finished, which stops being the
    most recently composed one as soon as two are outstanding.
    """

    run_id: str
    graph: Any
    signature: str
    scrutiny: Scrutiny
    intent: ExperimentIntent
    turn: int
    handle: Any = None
    state: RunState = RunState.ADMITTED
    cancel_requested: bool = False
    #: Absorptions visible when this run was admitted. What separates a run that had a
    #: chance to act on the last result from one already in flight when it landed.
    informed_by: int = 0


log = logging.getLogger(__name__)


class CampaignExecutor:
    def __init__(self, spec: CampaignSpec, policy: Any = None,
                 registry: Registry | None = None):
        self.spec, self.policy = spec, policy
        self.reg = registry or Registry().load()
        self.tree = CampaignTree()
        self.budget = BudgetLedger(limits=dict(spec.budget))
        self.root = Path(spec.root) / spec.campaign_id
        self.prov = ProvenanceLog(self.root / "provenance")
        self.jobs = JobLedger(self.root / "jobs" / "ledger.jsonl")
        trust_dir = Path(spec.trust_root) if spec.trust_root else Path(spec.root) / "_trust"
        self.trust = TrustLedger.load(trust_dir / f"{spec.site.gpu_api}.jsonl")
        self.composer = Composer(self.reg)
        self.validator = Validator(self.reg, spec.site, self.budget)
        self.cycle = 0
        # Labels issued vs experiments actually dispatched. A rejected submission still
        # burns a label - the retry is a different graph with a different draw, so it
        # must not reuse one - but it never ran and must not be counted as a run.
        self.run_seq = 0
        self.dispatched = 0
        self.max_attempts = spec.max_attempts
        self.pending_human: RequestHuman | None = None
        self.prov_sink: Any = None
        self._stagnant = 0
        # Absorptions counted toward stagnation so far. Runs admitted before this
        # watermark were already in flight when the last counted result landed.
        self._counted_through = 0
        self._failed_runs = 0
        self.flow = None
        self.dispatcher: Dispatcher | None = None
        self.last_rejection: ValidationFailure | None = None
        self._runs: dict[str, RunRecord] = {}
        self._inflight: dict[str, RunRecord] = {}
        self._outcomes: dict[str, RunOutcome] = {}
        self._waiters: dict[str, Any] = {}
        self._completed: asyncio.Queue = asyncio.Queue()
        self._halt = asyncio.Event()
        self._activity = asyncio.Event()
        # Pause gates ADMISSION, not execution: work already dispatched runs to
        # completion, because stopping it would mean cancelling it, and cancellation
        # here is advisory at best. `pause` has been on the control plane since the
        # first prototype and never did anything - nothing awaited it.
        self._paused = asyncio.Event()
        self._paused.set()
        self._stop_reason: str | None = None
        self._rejections = 0
        # Untrusted signatures currently in flight. Promotion counts CONSECUTIVE clean
        # runs, so N concurrent instances of one provisional pattern would promote it on
        # a single draw sampled N times - evidence the interlock never actually gathered.
        self._untrusted_inflight: set[str] = set()
        self._last_front_ids: set[str] = set()
        # Node ids in ABSORPTION order. `recent` used to mean "nodes stamped with the
        # previous cycle", which is only meaningful while a cycle absorbs exactly one
        # result. A cursor into this list says "what has landed since you last looked",
        # which stays true however many runs are in flight.
        self._absorbed: list[str] = []
        self._cursor = 0

    # -- provenance ----------------------------------------------------------
    def _log(self, kind: str, record: dict[str, Any]) -> None:
        """Write provenance and mirror it to the control plane's event stream.

        The plane has always assigned `manager.prov_sink`; nothing ever read it, so
        `events()` could only ever replay the plane's own calls and never saw anything
        the campaign actually did."""
        self.prov.append(kind, record)
        if self.prov_sink is not None:
            self.prov_sink(self.spec.campaign_id, kind, dict(record))

    # -- observe -------------------------------------------------------------
    def observe(self, last_rejection: ValidationFailure | None = None,
                since: int | None = None) -> CampaignObservation:
        """A read-only snapshot. `since` is a watermark into absorption order; the
        default reports what the last consumer saw, so an observer on the control plane
        gets parity of evidence with the policy without disturbing its cursor."""
        live = self.tree.live()
        front = pareto_front(live, self.spec.objectives)
        allnodes = list(self.tree)
        stats = PopulationStats(
            size=len(allnodes), live=len(live),
            failed=sum(1 for n in allnodes if n.qc.verdict is QCVerdict.FAIL),
            suspect=sum(1 for n in allnodes if n.qc.verdict is QCVerdict.SUSPECT),
            metric_means={
                o.name: round(sum(v for n in live if (v := n.metric(o.name)) is not None)
                              / max(1, sum(1 for n in live if n.metric(o.name) is not None)), 3)
                for o in self.spec.objectives},
        )
        cursor = self._cursor if since is None else max(0, min(since, len(self._absorbed)))
        return CampaignObservation(
            campaign_id=self.spec.campaign_id, cycle=self.cycle, goal=self.spec.goal,
            objectives=self.spec.objectives, pareto_front=front, population=stats,
            recent=[self.tree.get(nid) for nid in self._absorbed[cursor:]],
            seq=len(self._absorbed),
            budget=self.budget, available_tools=self.reg.ids(),
            last_rejection=last_rejection)

    # -- update --------------------------------------------------------------
    def _absorb(self, results: ExecutionResults, graph, parent: str | None,
                scrutiny: Scrutiny, decision_id: str, turn: int = 0) -> list[DesignNode]:
        """One DesignNode per replica lineage - N replicas are N candidates, not one.

        Stamped with the turn that SUBMITTED the run, not the current one: the campaign
        moves on while work is outstanding, so `self.cycle` no longer describes the
        experiment a result came from.
        """
        made: list[DesignNode] = []
        for lineage, task_ids in sorted(results.lineages(graph).items()):
            node = DesignNode(parent=parent, cycle=turn,
                              produced_by=graph.id, decision=decision_id)
            qc = results.qc_for(task_ids)
            if scrutiny.mark_suspect and qc.verdict is not QCVerdict.FAIL:
                qc.mark_suspect("provisional composition pattern - not yet trusted")
            node.qc = qc
            # `DesignNode.artifacts` has existed since the first prototype and was
            # never populated, so there was no way to get from a node on the Pareto
            # front to the structure it is a claim about.
            node.artifacts = results.artifacts_for(task_ids)
            for k, v in results.metrics_for(task_ids).items():
                node.properties[k] = Property(
                    name=k, value=v,
                    source=PropertySource(name="mock_toolkit", authority=10))
            if any(t in results.failures for t in task_ids):
                node.status = NodeStatus.FAILED
            self.tree.add(node)
            self._absorbed.append(node.id)
            made.append(node)
            self._log("results", {"node": node.id, "cycle": turn,
                                  "run": decision_id, "lineage": lineage,
                                  "qc": qc.verdict.value,
                                  "metrics": results.metrics_for(task_ids)})
        return made

    def _note_progress(self, rec: RunRecord) -> bool:
        """Update the stagnation counter. Returns True if the campaign has stalled.

        Counts consecutive INFORMED attempts that failed to improve the front - a run
        submitted after the previously counted result had already been absorbed.

        Counting every absorbed run instead is wrong the moment more than one experiment
        is in flight: a four-wide ensemble is launched before any of it reports, so no
        member could have acted on the others' results. Blaming four runs for failing to
        improve on evidence none of them ever saw stopped healthy campaigns within about
        a second of fanning out. It is the same mistake the interlock already refuses to
        make when it rules that concurrent instances of a pattern are one draw sampled
        twice rather than two pieces of evidence.

        At `concurrency: 1` every run is submitted after the previous one was absorbed,
        so every run counts and the behaviour is exactly what it always was.
        """
        ids = {n.id for n in pareto_front(self.tree.live(), self.spec.objectives)}
        if ids != self._last_front_ids:
            self._last_front_ids, self._stagnant = ids, 0
        elif rec.informed_by >= self._counted_through:
            self._stagnant += 1
            self._counted_through = len(self._absorbed)
        # else: already in flight when that result landed - same wave, not new evidence.
        return self._stagnant >= self.spec.stagnation_limit

    # -- admit ---------------------------------------------------------------
    async def _admit_once(self, intent: ExperimentIntent, run_label: str
                          ) -> tuple[RunRecord | None, ValidationFailure | None]:
        """Compose, check and reserve, for ONE attempt. Dispatches nothing.

        The bounded retry used to live here, wrapped around a call back into the policy.
        It belongs to the caller now: a reasoner retries by calling `submit` again, and
        can equally well decide to submit something else instead - which `on_rejected`
        could never express, since it had to return a decision about the same attempt.
        """
        intent = self._apply_campaign_defaults(intent)
        try:
            graph = self.composer.compose(intent, run_label)
        except KeyError as unknown:
            # The composer resolves tool ids before gate 1 ever sees the graph, so an
            # id that does not exist raised out of admission instead of being refused.
            # A caller that mistypes a tool deserves the same answer as one that wires
            # it up wrongly: a rejection naming the gate and the reason.
            return None, ValidationFailure(
                gate="type",
                reason=f"unknown tool {unknown.args[0] if unknown.args else unknown}",
                detail={"stages": list(intent.stages),
                        "available": self.reg.ids()})
        sig = graph.pattern_signature()
        self.trust.record_for(sig, [n.tool for n in graph.nodes.values()])
        scrutiny = Scrutiny.for_pattern(self.trust, sig)

        failure = self.validator.validate(graph)
        if failure is None and not scrutiny.trusted and sig in self._untrusted_inflight:
            failure = ValidationFailure(
                gate="interlock", transient=True,
                reason="an untrusted pattern may have only one instance in flight; "
                       "promotion counts consecutive clean runs, and concurrent "
                       "instances are one draw sampled twice")
        if failure is None and scrutiny.cost_cap_fraction is not None:
            est = self.validator.estimate(graph)
            for dim, c in est.items():
                cap = self.budget.available(dim) * scrutiny.cost_cap_fraction
                if self.budget.limits.get(dim) and c > cap:
                    failure = ValidationFailure(
                        gate="interlock", transient=True,
                        reason=f"provisional pattern capped at "
                               f"{scrutiny.cost_cap_fraction:.0%} of available "
                               f"{dim} ({c:.3f} > {cap:.3f})")
                    break
        if failure is None and scrutiny.force_dry_run:
            failure = await self.validator.dry_run(graph)
        if failure is None:
            # Reserve LAST. dry_run awaits, so the budget gate 5 saw may already have
            # been claimed by another submission; reserve re-checks and is the
            # authoritative admission decision.
            est = self.validator.estimate(graph)
            if blown := self.budget.reserve(est, run_label):
                failure = ValidationFailure(
                    gate="budget", transient=True,
                    reason=f"estimate exceeds AVAILABLE budget in {blown} "
                           f"(work already in flight holds the difference)",
                    detail={"estimate": est,
                            "available": {d: self.budget.available(d) for d in blown}})

        orphaned = self._objectives_without_a_producer(graph) if failure is None else []
        if orphaned:
            log.warning(
                "graph %s is admitted but cannot produce %s - no tool in %s reports "
                "%s. Objectives with a min/max bound count a missing value as a "
                "constraint violation, so every node from this graph is excluded from "
                "the front. The run will cost its full estimate and return nothing "
                "rankable.",
                graph.id, ", ".join(orphaned),
                " -> ".join(n.tool for n in graph.nodes.values()),
                "them" if len(orphaned) > 1 else "it")

        self._log("graphs", {
            "cycle": self.cycle, "graph": graph.id, "run": run_label,
            "signature": sig, "trusted": scrutiny.trusted,
            "nodes": {k: v.tool for k, v in graph.nodes.items()},
            "estimate": self.validator.estimate(graph),
            "unproducible_objectives": orphaned,
            "rejected": failure.model_dump() if failure else None})

        if failure is not None:
            return None, failure
        if not scrutiny.trusted:
            self._untrusted_inflight.add(sig)
        return RunRecord(run_id=run_label, graph=graph, signature=sig,
                         scrutiny=scrutiny, intent=intent, turn=self.cycle,
                         informed_by=len(self._absorbed)), None

    def _objectives_without_a_producer(self, graph) -> list[str]:
        """Campaign objectives no tool in this graph reports a metric for.

        Job 22675512: a budget correction truncated `boltz_predict` off the chain, and
        with it the only producer of `complex_plddt` and `ligand_iptm` - two of that
        campaign's four objectives. Nothing noticed. The composer and the validator never
        receive `spec.objectives` at all, so the graph was type-correct, affordable,
        admitted, and incapable of informing half of what it was for.

        Reads `ToolSpec.metrics`, which every tool now declares. The first version of this
        inferred the set from `metric_in_range` gate params instead, and warned falsely on
        the mock campaign - its tools emit ddg/iptm/sc_rmsd and gate on none of them, so a
        graph that demonstrably produced a four-node front was reported as unable to produce
        anything. Gate metrics are still unioned in, because a gated name is by definition
        reported, and that keeps a tool honest if its declaration drifts.
        """
        wanted = {o.name for o in self.spec.objectives}
        if not wanted:
            return []
        produced: set[str] = set()
        for node in graph.nodes.values():
            spec = self.reg.get(node.tool)
            produced.update(spec.metrics)
            for gate in spec.qc_gates:
                if metric := (gate.params or {}).get("metric"):
                    produced.add(metric)
        return sorted(wanted - produced)

    def _apply_campaign_defaults(self, intent: ExperimentIntent) -> ExperimentIntent:
        """Fill in what the campaign declares and the policy did not ask about.

        The ligand and the contig are campaign configuration, not search strategy: a
        policy chooses how to explore, not what molecule the campaign is about. Merging
        here rather than in each policy means an external directive and a `conduct`
        reasoner get them for free, and no policy has to learn a tool's parameter names.

        The policy always wins on any key it did set - this supplies defaults, it does
        not override decisions.
        """
        if not (self.spec.stages or self.spec.params or self.spec.replicas):
            return intent
        merged = dict(intent.params)
        for tool_id, defaults in self.spec.params.items():
            merged[tool_id] = {**defaults, **merged.get(tool_id, {})}
        # `replicas` is a CAP, not a default. Breadth costs GPU-hours, so how wide a
        # campaign may go is the campaign's call; how wide to go within that is the
        # policy's. A policy that shrinks its request after a rejection still shrinks.
        replicas = intent.replicas
        if self.spec.replicas:
            replicas = min(replicas, self.spec.replicas)
        return intent.model_copy(update={
            "stages": intent.stages or list(self.spec.stages),
            "params": merged,
            "replicas": max(1, replicas),
        })

    # -- the session surface -------------------------------------------------
    async def submit(self, intent: ExperimentIntent) -> str:
        """Admit and dispatch one experiment, without waiting for it."""
        if self._halt.is_set():
            raise CampaignStopped(self._stop_reason or "campaign has ended")
        await self._await_resume()
        if self.spec.max_runs and self.run_seq >= self.spec.max_runs:
            self.request_stop(f"max_runs={self.spec.max_runs} reached")
            raise CampaignStopped(self._stop_reason)

        self.run_seq += 1
        run_label = f"r{self.run_seq:04d}"
        rec, failure = await self._admit_once(intent, run_label)
        if failure is not None:
            self.last_rejection = failure
            self._rejections += 1
            # The executor caps this independently of any driver. A `conduct` reasoner
            # is under no obligation to honour `max_attempts`, and an unbounded
            # submit/reject loop would spin the campaign forever at no cost to itself.
            if self._rejections >= self.spec.max_admission_failures:
                self.request_stop(
                    f"{self._rejections} submissions rejected at admission")
            raise SubmissionRejected(failure)

        self._rejections = 0
        self.cycle += 1
        self.dispatched += 1
        self._runs[run_label] = rec
        self._inflight[run_label] = rec
        self._waiters[run_label] = asyncio.get_running_loop().create_future()
        rec.state = RunState.RUNNING
        self.jobs.record(job_id=run_label, status="submitted", graph=rec.graph.id,
                         signature=rec.signature, cycle=self.cycle,
                         estimate=self.validator.estimate(rec.graph))
        rec.handle = self.dispatcher.submit(rec.graph, run_id=run_label)
        log.info("submitted %s: %s (trusted=%s, estimate=%s)", run_label,
                 {tid: n.tool for tid, n in rec.graph.nodes.items()},
                 rec.scrutiny.trusted, self.validator.estimate(rec.graph))
        self._activity.set()
        return run_label

    def status(self, run_id: str) -> RunStatus:
        rec = self._runs[run_id]
        return RunStatus(run_id=run_id, state=rec.state, graph_id=rec.graph.id,
                         signature=rec.signature, trusted=rec.scrutiny.trusted,
                         turn=rec.turn, estimate=self.validator.estimate(rec.graph))

    def inflight(self) -> list[RunStatus]:
        return [self.status(rid) for rid in list(self._inflight)]

    async def result(self, run_id: str) -> RunOutcome:
        """Wait for one run. Raises `CampaignStopped` if the campaign ends first.

        Races the run against the campaign ending. Awaiting the run's future alone would
        hang whenever termination is decided while a reasoner is waiting - which is the
        deadlock this two-coroutine split makes possible, and it is silent.
        """
        if (done := self._outcomes.get(run_id)) is not None:
            return done
        fut = self._waiters.get(run_id)
        if fut is None:
            raise KeyError(f"unknown run {run_id}")
        halt = asyncio.ensure_future(self._halt.wait())
        try:
            finished, _ = await asyncio.wait({fut, halt},
                                             return_when=asyncio.FIRST_COMPLETED)
            if fut in finished:
                return fut.result()
            raise CampaignStopped(self.stop_reason)
        finally:
            halt.cancel()

    async def next_completed(self) -> RunOutcome:
        """The next run to FINISH, which is not the next one submitted."""
        return await self._completed.get()

    def cancel(self, run_id: str) -> None:
        rec = self._inflight.get(run_id)
        if rec is not None and rec.handle is not None:
            rec.cancel_requested = True
            self.dispatcher.cancel(rec.handle)

    def backtrack(self, node_id: str, rationale: str = "") -> str:
        branch = self.tree.branch_from(node_id)
        branch.cycle = self.cycle
        self.tree.add(branch)
        self._log("decisions", {"cycle": self.cycle, "kind": "backtrack",
                                "from": node_id, "new": branch.id,
                                "rationale": rationale})
        return branch.id

    def request_human(self, question: str, context: dict[str, Any] | None = None) -> None:
        self.pending_human = RequestHuman(question=question, context=context or {})
        self._log("transitions", {"event": "request_human", "question": question})
        self.request_stop(f"awaiting human: {question}")

    def pause(self) -> None:
        self._paused.clear()

    def resume(self) -> None:
        self._paused.set()
        self._activity.set()

    @property
    def paused(self) -> bool:
        return not self._paused.is_set()

    async def _await_resume(self) -> None:
        """Block while paused - but never past the end of the campaign."""
        if self._paused.is_set():
            return
        resumed = asyncio.ensure_future(self._paused.wait())
        halt = asyncio.ensure_future(self._halt.wait())
        try:
            await asyncio.wait({resumed, halt}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            resumed.cancel()
            halt.cancel()
        if self._halt.is_set():
            raise CampaignStopped(self.stop_reason)

    def request_stop(self, reason: str) -> None:
        """Record the first reason the campaign ended. Later ones are consequences."""
        if not self._halt.is_set():
            log.info("stop requested: %s", reason)
        if self._stop_reason is None:
            self._stop_reason = reason
        self._halt.set()
        self._activity.set()

    @property
    def stop_reason(self) -> str:
        return self._stop_reason or "completed"

    @property
    def stopped(self) -> bool:
        return self._halt.is_set()

    # -- reap ----------------------------------------------------------------
    def _settle(self, run_id: str, rec: RunRecord,
                results: ExecutionResults) -> list[DesignNode]:
        self.budget.settle(run_id, results.cost)
        self._untrusted_inflight.discard(rec.signature)
        self.jobs.record(job_id=run_id,
                         status=(RunState.FAILED if results.failures
                                 else RunState.DONE).value,
                         cost=results.cost, failures=results.failures)
        self._log("executions", {"cycle": rec.turn, "graph": rec.graph.id,
                                 "run": run_id, "cost": results.cost,
                                 "failures": results.failures})
        log.info("reaped %s: %d/%d tasks ok, cost=%s%s", run_id,
                 len(results.per_task), len(rec.graph.nodes), results.cost,
                 f", failures={results.failures}" if results.failures else "")
        return self._absorb(results, rec.graph, rec.intent.parent_node,
                            rec.scrutiny, run_id, turn=rec.turn)

    def _abandon(self, run_id: str, rec: RunRecord, err: BaseException) -> None:
        log.warning("abandoned %s: %r", run_id, err)
        self.budget.release(run_id)          # never ran; never charge for it
        self._untrusted_inflight.discard(rec.signature)
        self.jobs.record(job_id=run_id,
                         status=(RunState.CANCELLED if rec.cancel_requested
                                 else RunState.FAILED).value,
                         error=str(err))

    def _record_evidence(self, rec: RunRecord, results: ExecutionResults) -> bool:
        """Feed one run's outcome to the interlock. Returns True if it was a failure.

        Kept separate from reaping because a drained run is still evidence: it ran, it
        was paid for, and the pattern either held up or did not. Dropping that at
        teardown would quietly starve the promotion counter.
        """
        sig = rec.signature
        if results.all_gates_passed and not results.failures:
            if self.trust.on_clean_run(sig):
                self._log("transitions", {"event": "pattern_promoted",
                                          "signature": sig})
            return False
        if self.trust.on_failure(sig):
            self._log("transitions", {"event": "pattern_demoted", "signature": sig})
        return True

    async def _reap(self, run_id: str) -> None:
        """Fold one finished run into campaign state and wake whoever is waiting."""
        rec = self._inflight.pop(run_id, None)
        if rec is None:
            return
        try:
            results = await self.dispatcher.collect(rec.handle)
        except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001 - see below
            # Any failure to collect still has to release the reservation and resolve
            # the waiter; letting it escape would strand both.
            self._abandon(run_id, rec, e)
            rec.state = RunState.FAILED
            self._resolve(run_id, RunOutcome(run_id=run_id, graph_id=rec.graph.id,
                                             state=RunState.FAILED,
                                             signature=rec.signature,
                                             failures={"run": str(e)}))
            return

        nodes = self._settle(run_id, rec, results)
        rec.state = (RunState.CANCELLED if rec.cancel_requested and results.failures
                     else RunState.FAILED if results.failures else RunState.DONE)
        outcome = results.to_outcome(run_id, rec.graph, state=rec.state,
                                     nodes=[n.id for n in nodes],
                                     signature=rec.signature)
        # NOTE: `policy.interpret` is deliberately NOT called here. It used to be, which
        # made this the only place the executor reached into the reasoner - and it worked
        # only while the two shared a process. A reasoner driving the campaign through a
        # remote session leaves a placeholder policy behind here, so the hook fired
        # against the wrong object, or not at all. Collecting an outcome is the reasoner's
        # half of the seam; `SequentialPolicyDriver._collect` owns the call, and a
        # `conduct` policy that collects for itself calls it for itself.

        if self._record_evidence(rec, results):
            self._failed_runs += 1
            if self._failed_runs >= self.spec.max_failed_cycles:
                self._resolve(run_id, outcome)
                raise CampaignAborted(
                    f"{self._failed_runs} consecutive all-failed runs")
        else:
            self._failed_runs = 0

        self._resolve(run_id, outcome)

        if self._note_progress(rec):
            self.request_stop(
                f"stagnation: front unchanged over {self._stagnant} informed attempts")
        elif blown := self.budget.exhausted():
            self.request_stop(f"budget exhausted: {blown}")

    def _resolve(self, run_id: str, outcome: RunOutcome) -> None:
        """Deliver a finished run to whoever asked for it, and write it down.

        The payload goes to the ledger, not just the status: a restart that could only
        learn THAT a run finished would have to re-run it to find out what it produced,
        which on HPC means paying for the allocation twice.
        """
        self._outcomes[run_id] = outcome
        self.jobs.record_outcome(run_id, outcome)
        self._completed.put_nowait(outcome)
        fut = self._waiters.pop(run_id, None)
        if fut is not None and not fut.done():
            fut.set_result(outcome)
        # The same notification, mirrored onto the event stream. `_completed` is an
        # in-memory queue, so a reasoner in another process cannot see it; without this
        # record `as_completed` has no remote equivalent and the far side is back to
        # polling. It is emitted here rather than in `_settle` because this is the one
        # point every finished run passes through - an ABANDONED run never settles, and
        # in-process it still reaches the queue.
        self._log("executions", {"event": "run_finished", "run": run_id,
                                 "state": outcome.state.value,
                                 "nodes": list(outcome.nodes)})

    def _fail_waiters(self, err: BaseException) -> None:
        """Nobody is left waiting on a campaign that has ended.

        A reasoner blocked on `result()` when the executor aborts would otherwise wait on
        a future that will never be set - the deadlock this split makes possible.
        """
        for fut in self._waiters.values():
            if not fut.done():
                fut.set_exception(err)
        self._waiters.clear()
        self._completed.put_nowait(None)          # unblock `as_completed`
        # ... and its remote equivalent. This is the moment after which nothing further
        # will ever be delivered - drain has already resolved everything still in
        # flight - so it is the sentinel a remote `as_completed` stops on, exactly as
        # the `None` above is the one an in-process caller stops on.
        self._log("transitions", {"event": "campaign_ended",
                                  "reason": self.stop_reason})

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        from ..exec.backend import make_engine_bounded
        # Logged either side because this call is the only stretch of a campaign that
        # precedes its own provenance: rhapsody's Dragon backend builds `Batch()` - the
        # results DDict, the worker pool, telemetry - synchronously in its constructor, so
        # a stall there leaves no campaign.jsonl and no other trace at all. Bounded by
        # `backend_startup_timeout_s` (0 = unbounded, the default) precisely because of
        # that: see `exec.backend.make_engine_bounded`.
        log.info("engine: constructing %s backend (config=%s)",
                 self.spec.backend, self.spec.backend_config or {})
        self.flow, self._backend = await make_engine_bounded(
            self.spec.backend, self.spec.backend_config, self.spec.backend_startup_timeout_s,
            self.spec.backend_startup_heartbeat_s, work_dir=str(self.root))
        log.info("engine: %s backend ready", self.spec.backend)
        self.dispatcher = Dispatcher(self.flow, self.reg, self.spec.backend)
        self.jobs.record(event="campaign_started",
                         campaign=self.spec.campaign_id,
                         policy=getattr(self.policy, "name", "?"))
        self._log("campaign", {"spec": self.spec.campaign_id, "goal": self.spec.goal,
                               "policy": getattr(self.policy, "name", "?"),
                               "objectives": [o.model_dump()
                                              for o in self.spec.objectives],
                               "budget": self.spec.budget})

    async def pump(self) -> None:
        """Reap runs as they finish, for as long as the campaign runs.

        Waits on whichever run completes FIRST, rather than the oldest. That is the
        difference the reasoner can actually feel: an ensemble comes back in the order
        the science finishes, not the order it was asked for.
        """
        halt = asyncio.ensure_future(self._halt.wait())
        try:
            while not self._halt.is_set():
                if not self._inflight:
                    wake = asyncio.ensure_future(self._activity.wait())
                    await asyncio.wait({wake, halt},
                                       return_when=asyncio.FIRST_COMPLETED)
                    wake.cancel()
                    self._activity.clear()
                    continue
                pending = {rec.handle.gather: rid
                           for rid, rec in self._inflight.items()}
                done, _ = await asyncio.wait(set(pending) | {halt},
                                             return_when=asyncio.FIRST_COMPLETED)
                for fut in done:
                    if fut is halt:
                        continue
                    await self._reap(pending[fut])
        finally:
            halt.cancel()

    async def drain(self) -> None:
        """Collect whatever is still outstanding before the engine goes away.

        `shutdown()` used to run with nothing in flight, because the loop could only exit
        between graphs. Now any exit can leave work running, and tearing the engine down
        underneath it both races and discards results already paid for.
        """
        while self._inflight:
            run_id = next(iter(self._inflight))
            rec = self._inflight.pop(run_id)
            try:
                results = await self.dispatcher.collect(rec.handle)
            # Keep draining; one bad run must not strand the others' reservations.
            # Deliberately not BaseException: a KeyboardInterrupt during teardown should
            # still get out.
            except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001
                self._abandon(run_id, rec, e)
                self._resolve(run_id, RunOutcome(run_id=run_id, state=RunState.FAILED,
                                                 graph_id=rec.graph.id,
                                                 failures={"run": str(e)}))
                continue
            nodes = self._settle(run_id, rec, results)
            # Evidence, yes; termination checks, no - the campaign is already ending,
            # and stagnation or an abort decided here would only race the real reason.
            self._record_evidence(rec, results)
            rec.state = RunState.FAILED if results.failures else RunState.DONE
            self._resolve(run_id, results.to_outcome(
                run_id, rec.graph, state=rec.state, nodes=[n.id for n in nodes],
                signature=rec.signature))

    async def shutdown(self, err: BaseException | None = None) -> None:
        self._halt.set()
        try:
            await self.drain()
        finally:
            self._fail_waiters(err or CampaignStopped(self.stop_reason))
            if self.flow is not None:
                await self._shutdown_engine()

    async def _shutdown_engine(self) -> None:
        """Tear the engine down, bounded, and never let teardown sink the campaign.

        A hung `flow.shutdown()` holds the allocation open long after the work is done -
        see `backend_shutdown_timeout_s`. Giving up on it is safe in a way that giving up
        on construction is not: every result is already written to provenance and the
        ledger by this point, so the worst case is leaked backend state in a process that
        is about to exit anyway. The timeout is therefore logged, not raised - an
        abandoned teardown must not turn a finished campaign into a failed one.
        """
        timeout_s = self.spec.backend_shutdown_timeout_s
        if timeout_s <= 0:
            await self.flow.shutdown()
            return
        try:
            await asyncio.wait_for(asyncio.shield(self.flow.shutdown()), timeout_s)
        except asyncio.TimeoutError:
            log.warning(
                "engine: %s backend did not shut down within %.0fs - abandoning it. "
                "The campaign's results are already durable; this leaks backend state in "
                "an exiting process. See docs/limitations.md.",
                self.spec.backend, timeout_s)
