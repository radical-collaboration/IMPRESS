"""The campaign manager - the outer loop.

  observe -> decide -> compose -> validate -> execute -> analyze -> update -> terminate?

Only `decide` differs between control models, which is what makes them interchangeable.
The loop is OURS: Phase 3 established that ceding it to a framework forces the validation
gates, dry-run and interlock into awkward places (decisions 0003, and Phase 3 doc 04).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .compose.composer import Composer
from .compose.interlock import Scrutiny, TrustLedger
from .compose.validate import SiteCaps, Validator
from .core.artifacts import Property, PropertySource
from .core.budget import BudgetLedger
from .core.decision import (Backtrack, CampaignObservation, ComposeAndRun,
                            PopulationStats, RequestHuman, Stop, ValidationFailure)
from .core.pareto import Objective, pareto_front
from .core.provenance import ProvenanceLog
from .core.qc import QCVerdict
from .core.tree import CampaignTree, DesignNode, NodeStatus
from .exec.dispatch import Dispatcher, ExecutionResults
from .exec.ledger import JobLedger
from .tools.registry import Registry


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
    max_cycles: int = 10
    stagnation_limit: int = 3
    max_failed_cycles: int = 3
    max_attempts: int = 4
    site: SiteCaps = field(default_factory=SiteCaps)
    backend: str = "concurrent"
    backend_config: dict[str, Any] = field(default_factory=dict)
    root: str = "campaigns/_runs"


@dataclass
class CampaignResult:
    campaign_id: str
    cycles: int
    stop_reason: str
    front: list[DesignNode]
    tree: CampaignTree
    corrections: list[str] = field(default_factory=list)


class CampaignManager:
    def __init__(self, spec: CampaignSpec, policy: Any, registry: Registry | None = None):
        self.spec, self.policy = spec, policy
        self.reg = registry or Registry().load()
        self.tree = CampaignTree()
        self.budget = BudgetLedger(limits=dict(spec.budget))
        self.root = Path(spec.root) / spec.campaign_id
        self.prov = ProvenanceLog(self.root / "provenance")
        self.jobs = JobLedger(self.root / "jobs" / "ledger.jsonl")
        self.trust = TrustLedger.load(Path(spec.root) / "_trust" / f"{spec.site.gpu_api}.json")
        self.composer = Composer(self.reg)
        self.validator = Validator(self.reg, spec.site, self.budget)
        self.cycle = 0
        self.max_attempts = spec.max_attempts
        self.pending_human: RequestHuman | None = None
        self._stagnant = 0
        self._failed_cycles = 0
        self._last_front_ids: set[str] = set()

    # -- observe -------------------------------------------------------------
    def observe(self, last_rejection: ValidationFailure | None = None) -> CampaignObservation:
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
        return CampaignObservation(
            campaign_id=self.spec.campaign_id, cycle=self.cycle, goal=self.spec.goal,
            objectives=self.spec.objectives, pareto_front=front, population=stats,
            recent=[n for n in allnodes if n.cycle == self.cycle - 1],
            budget=self.budget, available_tools=self.reg.ids(),
            last_rejection=last_rejection)

    # -- update --------------------------------------------------------------
    def _absorb(self, results: ExecutionResults, graph, parent: str | None,
                scrutiny: Scrutiny, decision_id: str) -> list[DesignNode]:
        """One DesignNode per replica lineage - N replicas are N candidates, not one."""
        made: list[DesignNode] = []
        for lineage, task_ids in sorted(results.lineages(graph).items()):
            node = DesignNode(parent=parent, cycle=self.cycle,
                              produced_by=graph.id, decision=decision_id)
            qc = results.qc_for(task_ids)
            if scrutiny.mark_suspect and qc.verdict is not QCVerdict.FAIL:
                qc.mark_suspect("provisional composition pattern - not yet trusted")
            node.qc = qc
            for k, v in results.metrics_for(task_ids).items():
                node.properties[k] = Property(
                    name=k, value=v,
                    source=PropertySource(name="mock_toolkit", authority=10))
            if any(t in results.failures for t in task_ids):
                node.status = NodeStatus.FAILED
            self.tree.add(node)
            made.append(node)
            self.prov.append("results", {"node": node.id, "cycle": self.cycle,
                                         "lineage": lineage, "qc": qc.verdict.value,
                                         "metrics": results.metrics_for(task_ids)})
        return made

    # -- the loop ------------------------------------------------------------
    async def run(self) -> CampaignResult:
        from .exec.backend import make_engine
        flow, backend = await make_engine(self.spec.backend, self.spec.backend_config)
        dispatcher = Dispatcher(flow, self.reg, self.spec.backend)
        self.prov.append("campaign", {"spec": self.spec.campaign_id, "goal": self.spec.goal,
                                      "policy": getattr(self.policy, "name", "?"),
                                      "objectives": [o.model_dump() for o in self.spec.objectives],
                                      "budget": self.spec.budget})
        stop_reason, rejection, last_results = "completed", None, None
        try:
            while self.cycle < self.spec.max_cycles:
                obs = self.observe(rejection)
                rejection = None
                decision = await self.policy.decide(obs)

                if isinstance(decision, Stop):
                    stop_reason = decision.reason
                    break
                if isinstance(decision, RequestHuman):
                    self.pending_human = decision
                    self.prov.append("transitions", {"event": "request_human",
                                                     "question": decision.question})
                    stop_reason = f"awaiting human: {decision.question}"
                    break
                if isinstance(decision, Backtrack):
                    branch = self.tree.branch_from(decision.node_id)
                    branch.cycle = self.cycle
                    self.tree.add(branch)
                    self.prov.append("decisions", {"cycle": self.cycle, "kind": "backtrack",
                                                   "from": decision.node_id,
                                                   "new": branch.id,
                                                   "rationale": decision.rationale})
                    self.cycle += 1
                    continue

                # compose -> validate -> (interlock) -> dry-run -> execute,
                # with BOUNDED retry inside the cycle: a rejection hands the policy a
                # reason and another attempt, rather than silently costing a cycle.
                assert isinstance(decision, ComposeAndRun)
                graph = sig = scrutiny = results = None
                for attempt in range(self.max_attempts):
                    graph = self.composer.compose(decision.intent)
                    sig = graph.pattern_signature()
                    self.trust.record_for(sig, [n.tool for n in graph.nodes.values()])
                    scrutiny = Scrutiny.for_pattern(self.trust, sig)

                    failure = self.validator.validate(graph)
                    if failure is None and scrutiny.cost_cap_fraction is not None:
                        est = self.validator.estimate(graph)
                        for dim, c in est.items():
                            cap = self.budget.remaining(dim) * scrutiny.cost_cap_fraction
                            if self.budget.limits.get(dim) and c > cap:
                                failure = ValidationFailure(
                                    gate="interlock",
                                    reason=f"provisional pattern capped at "
                                           f"{scrutiny.cost_cap_fraction:.0%} of remaining "
                                           f"{dim} ({c:.3f} > {cap:.3f})")
                                break
                    if failure is None and scrutiny.force_dry_run:
                        failure = await self.validator.dry_run(graph)

                    self.prov.append("graphs", {
                        "cycle": self.cycle, "attempt": attempt, "graph": graph.id,
                        "signature": sig, "trusted": scrutiny.trusted,
                        "nodes": {k: v.tool for k, v in graph.nodes.items()},
                        "estimate": self.validator.estimate(graph),
                        "rejected": failure.model_dump() if failure else None})

                    if failure is None:
                        break
                    rejection = failure
                    retry = await self.policy.on_rejected(decision, failure)
                    if isinstance(retry, Stop):
                        stop_reason = retry.reason
                        graph = None
                        break
                    if not isinstance(retry, ComposeAndRun):
                        graph = None
                        stop_reason = "policy returned a non-runnable decision on rejection"
                        break
                    decision = retry
                else:
                    graph = None
                    stop_reason = f"{self.max_attempts} attempts all rejected in cycle {self.cycle}"

                if graph is None:
                    break

                results = await dispatcher.run(graph, invocation=f"c{self.cycle}")
                last_results = results
                self.budget.charge(results.cost)
                self.prov.append("executions", {"cycle": self.cycle, "graph": graph.id,
                                                "cost": results.cost,
                                                "failures": results.failures})

                self._absorb(results, graph, decision.intent.parent_node,
                             scrutiny, f"c{self.cycle}")
                await self.policy.interpret(results, obs)

                # interlock bookkeeping
                if results.all_gates_passed and not results.failures:
                    if self.trust.on_clean_run(sig):
                        self.prov.append("transitions", {"event": "pattern_promoted",
                                                         "signature": sig})
                    self._failed_cycles = 0
                else:
                    if self.trust.on_failure(sig):
                        self.prov.append("transitions", {"event": "pattern_demoted",
                                                         "signature": sig})
                    self._failed_cycles += 1
                    if self._failed_cycles >= self.spec.max_failed_cycles:
                        raise CampaignAborted(
                            f"{self._failed_cycles} consecutive all-failed cycles")

                # stagnation
                ids = {n.id for n in pareto_front(self.tree.live(), self.spec.objectives)}
                self._stagnant = 0 if ids != self._last_front_ids else self._stagnant + 1
                self._last_front_ids = ids
                if self._stagnant >= self.spec.stagnation_limit:
                    stop_reason = f"stagnation: front unchanged for {self._stagnant} cycles"
                    break
                if blown := self.budget.exhausted():
                    stop_reason = f"budget exhausted: {blown}"
                    break
                self.cycle += 1
            else:
                stop_reason = f"max_cycles={self.spec.max_cycles} reached"
        finally:
            await flow.shutdown()

        front = pareto_front(self.tree.live(), self.spec.objectives)
        self.prov.append("transitions", {"event": "terminated", "reason": stop_reason,
                                         "cycles": self.cycle, "front": [n.id for n in front]})
        return CampaignResult(campaign_id=self.spec.campaign_id, cycles=self.cycle,
                              stop_reason=stop_reason, front=front, tree=self.tree,
                              corrections=getattr(self.policy, "corrections", []))
