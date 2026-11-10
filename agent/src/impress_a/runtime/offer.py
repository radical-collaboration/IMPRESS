"""Compute what a campaign would cost and what it could answer, without running it.

`impress-a offer <spec>.yaml`. The caller-facing half of being a subordinate workflow
(decision 0014): an enclosing campaign manager fixes its own budget and resource request when
it builds its spec, *before* it launches anything, so the handshake cannot be a message
exchanged at launch - it has to be a function it can call first. This is that function.

Here in `runtime` because the inputs are a `Registry` and a `CampaignSpec`, and `runtime` is
the layer that can see both - `compose` may import only `tools` and `core`, so it could not
reach the spec. The types are in `core/offer`, because an offer crosses a process boundary.

**It executes nothing, and the signature is the guarantee.** `offer_for_spec` is `def`, not
`async def`: no backend can be constructed without an awaited engine, and rhapsody's fail
unregistered if they are not awaited. So a synchronous function cannot run a task however
wrong its body gets, and `tests/test_validation.py` pins the signature rather than trusting
the comment.

Everything it reports is either declared in a tool spec, declared in the campaign spec, or
COMPOSED - the node count, the pattern signature and the trust verdict come from building the
graph the campaign would build, the way `cli._signatures_for` already does for `trust`,
because a signature is a hash of graph shape and guessing it would be guessing the answer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..compose.composer import Composer
from ..compose.graph import TaskGraph
from ..compose.interlock import Scrutiny, TrustLedger
from ..compose.validate import Validator
from ..core.budget import BudgetLedger
from ..core.decision import ExperimentIntent
from ..core.offer import (
    AcceptanceBar,
    CampaignOffer,
    ChainOffer,
    CostBasis,
    CostRange,
    GoalOffer,
    OperatorParam,
    ResourceOffer,
    RootPort,
)
from ..core.pareto import Direction
from ..core.toolkit import ToolkitView
from ..core.types import ArtifactType, Pattern
from ..tools.registry import Registry
from ..tools.view import view_of

#: Fixed prose, carried in every offer's `basis.notes`. It states the one thing a reader must
#: not get wrong, and it deliberately quotes no multiplier: the measured-vs-declared spread is
#: recorded in `tests/test_real_toolkits.py` and backlog A11, and a number restated here would
#: be a second copy to go stale.
_BASIS_NOTES = (
    "Every figure derives from a `cost_model` declared in a tool spec, not from measurement.",
    "Declared figures are deliberately conservative: they feed gate 5 and the untrusted-"
    "pattern cap, which REFUSE graphs, so they sit above measurement on purpose. Treat an "
    "offer as an upper bound to size a budget against, never as a prediction of consumption.",
    "`impress-a validate-tasks` is the only thing that compares a declared figure to a "
    "measured one, and it runs the tools on hardware to do it.",
)

H = 3600.0


def _wall_hours(view: ToolkitView, chain: list[str]) -> float:
    """Declared walltime along a chain, in hours. Serial, because a lineage is."""
    return sum(view.tools[t].declared_walltime_s for t in chain) / H


def _estimate(validator: Validator, graph: TaskGraph) -> dict[str, float]:
    """The same estimator gate 5 prices a graph with.

    Deliberately not a second implementation: a caller that sizes its budget to this figure
    can never be refused by gate 5 for a reason the offer did not price.
    """
    return validator.estimate(graph)


def _compose(reg: Registry, spec: Any, stages: list[str], replicas: int) -> TaskGraph:
    return Composer(reg, seed_salt=spec.seed_salt).compose(
        ExperimentIntent(goal=spec.goal, stages=list(stages),
                         params=dict(spec.params), replicas=max(1, replicas)),
        run_label="offer")


def _goal_offer(reg: Registry, view: ToolkitView, spec: Any,
                declared: list[str], chain: list[str]) -> GoalOffer:
    """What this toolkit can and cannot be asked for.

    The producible/unproducible split applies the same predicate as the Specifier's
    `unproducible` and the executor's coverage check, which is the point: a caller is told
    before launching what those two would otherwise tell it mid-campaign, as a refusal.
    """
    metrics = sorted({m for t in declared for m in view.tools[t].metrics})
    producers = {m: [t for t in declared if m in view.tools[t].metrics] for m in metrics}

    producible, unproducible = [], []
    for obj in spec.objectives:
        (producible if view.producer_of(obj.name, declared) else unproducible).append(obj.name)

    bars, integrity = [], set()
    for tool in declared:
        for gate in reg.get(tool).qc_gates:
            metric = (gate.params or {}).get("metric")
            if gate.role == "acceptance" and metric:
                bars.append(AcceptanceBar(tool=tool, metric=metric,
                                          min=(gate.params or {}).get("min"),
                                          max=(gate.params or {}).get("max")))
            elif gate.role == "integrity" and metric:
                integrity.add(metric)

    produced = sorted({p.type.value for t in declared for p in view.tools[t].outputs.values()})
    unifications = sorted(
        (a.value, b.value) for a in ArtifactType for b in ArtifactType
        if a is not b and a.unifies_with(b))

    roots = [
        RootPort(tool=tool, port=port.name, type=port.type.value)
        for tool in chain
        for port in view.tools[tool].required_inputs
        if view.source_for(port.type, tool, chain) is None
    ]
    operator = [
        OperatorParam(tool=tool, name=name, reason=reason)
        for tool in declared
        for name, reason in view.tools[tool].frozen.items()
    ]

    return GoalOffer(
        addressable_metrics=metrics,
        producers=producers,
        producible_objectives=producible,
        unproducible_objectives=unproducible,
        acceptance_thresholds=bars,
        integrity_gated_metrics=sorted(integrity),
        directions=[d.value for d in Direction],
        bounded_objectives=[o.name for o in spec.objectives
                            if o.min is not None or o.max is not None],
        unbounded_objectives=[o.name for o in spec.objectives
                              if o.min is None and o.max is None],
        producible_artifact_types=produced,
        unifications=unifications,
        unsatisfied_root_ports=roots,
        operator_only_parameters=operator,
        not_answerable_here=[
            "Whether this campaign's goal is ACHIEVABLE. An offer answers only whether each "
            "declared objective is MEASURABLE by some enabled tool.",
            "Anything about the scientific target - the ligand, the contig, the input "
            "structure. Those live in `CampaignSpec.params` and in nothing the toolkit "
            "declares, so no toolkit-derived answer can depend on them.",
            "Whether a required root port is actually satisfied. The ports listed under "
            "`unsatisfied_root_ports` are computed from the chain's wiring; gate 1 does not "
            "check them, so this is a courtesy rather than a guarantee.",
            "What a reasoner will choose. Models A, B and C may select a SUBSET of the "
            "declared chain and may move any tunable parameter, so `chain.declared` is an "
            "upper bound on what runs and `cost` an upper bound priced at it.",
            "Whether an objective will ever be SATISFIED. An unbounded objective - a "
            "direction with no `min` or `max` - can be ranked but never satisfied, only "
            "unmeasured, so it contributes no stopping condition.",
        ],
    )


def offer_for_spec(spec: Any, registry: Registry | None = None, *,
                   report_interval_s: float = 30.0,
                   validation: str | Path | None = None) -> CampaignOffer:
    """Price and scope one campaign without running it.

    `spec` is a loaded `CampaignSpec` (`cli.load_spec`). `validation` optionally names a
    `validate_tasks.json` artifact, whose measured/declared ratios are carried into
    `basis.measured_ratio` - the only route by which a measured figure enters an offer, and
    it only exists because something ran the tools on hardware to produce it.
    """
    reg = registry if registry is not None else Registry().load()
    stages = list(spec.stages)
    view = view_of(reg, stages or None)

    # Narrowed to what the toolkit actually has, so a typo'd stage cannot make the offer
    # raise. It shows up instead as a chain shorter than the campaign declared.
    declared = [t for t in stages if t in view] or list(view.ids)
    inlined = [t for t in declared if reg.get(t).pattern is Pattern.P6]
    scheduled = [t for t in declared if t not in inlined]
    minimal, _wiring = view.required_closure([o.name for o in spec.objectives], declared)

    replicas = max(1, spec.replicas)
    concurrency = max(1, spec.concurrency)
    cycles = max(1, spec.max_cycles)

    graph = _compose(reg, spec, declared, replicas)
    signature = graph.pattern_signature()
    trust_dir = Path(spec.trust_root) if spec.trust_root else Path(spec.root) / "_trust"
    ledger = TrustLedger.load(trust_dir / f"{spec.site.gpu_api}.jsonl")
    scrutiny = Scrutiny.for_pattern(ledger, signature)

    validator = Validator(reg, spec.site, BudgetLedger(limits=dict(spec.budget)),
                          tool_delivery=spec.tool_delivery)
    per_cycle = _estimate(validator, graph)
    floor = _estimate(validator, _compose(reg, spec, minimal, 1)) if minimal else {}

    cost: dict[str, CostRange] = {}
    for dim in sorted(set(per_cycle) | set(spec.budget)):
        expected = per_cycle.get(dim, 0.0)
        declared_limit = spec.budget.get(dim)
        cost[dim] = CostRange(
            floor=floor.get(dim, 0.0),
            expected=expected,
            ceiling=declared_limit if declared_limit is not None else expected * cycles,
            unit=dim,
            bounded_by_budget=declared_limit is not None)

    # `wall_hours` is for a caller that prorates an unreported spend against it. `expected`
    # is set equal to `ceiling` on purpose: too SMALL a wall figure makes a caller's
    # proration exceed 100% and cancel a campaign that is doing nothing wrong.
    per_cycle_wall = _wall_hours(view, scheduled)
    campaign_wall = per_cycle_wall * cycles / concurrency
    cost["wall_hours"] = CostRange(
        floor=_wall_hours(view, [t for t in minimal if t not in inlined]),
        expected=campaign_wall, ceiling=campaign_wall, unit="wall_hours")

    peak = concurrency * replicas
    startup = spec.backend_startup_timeout_s + spec.backend_shutdown_timeout_s
    resources = ResourceOffer(
        gpus=peak * max((view.tools[t].gpus for t in scheduled), default=0),
        cores=peak * max((view.tools[t].cores for t in scheduled), default=1),
        nodes=max(spec.site.nodes, 1),
        walltime_s_per_cycle=int(per_cycle_wall * H),
        walltime_s_ceiling=int(campaign_wall * H + startup))

    basis = CostBasis(notes=list(_BASIS_NOTES))
    if validation is not None:
        basis.measured_source = str(validation)
        basis.measured_ratio = _measured_ratios(Path(validation))
        basis.notes.append(
            f"`measured_ratio` is measured/declared per tool, from {validation}. A ratio "
            f"below 1.0 means the declared figure has headroom; above 1.0 means gate 5 is "
            f"refusing work that would in fact fit.")

    return CampaignOffer(
        campaign_id=spec.campaign_id,
        goal_text=spec.goal,
        toolkits=sorted({view.tools[t].toolkit for t in declared}),
        chain=ChainOffer(
            declared=declared, minimal=minimal, inlined=inlined,
            replicas=replicas, concurrency=concurrency,
            graph_nodes=len(graph.nodes),
            pattern_signature=signature,
            trusted=scrutiny.trusted,
            first_cycle_dry_run=scrutiny.force_dry_run,
            cost_cap_fraction=scrutiny.cost_cap_fraction),
        cost=cost,
        resources=resources,
        loop={"max_cycles": spec.max_cycles, "max_runs": spec.max_runs,
              "max_attempts": spec.max_attempts, "target_front": spec.target_front,
              "stagnation_limit": spec.stagnation_limit},
        report_interval_s=report_interval_s,
        own_budget=dict(spec.budget),
        goals=_goal_offer(reg, view, spec, declared, scheduled),
        basis=basis,
        warnings=_warnings(spec, view, declared, scheduled, minimal, scrutiny, per_cycle),
    )


def _measured_ratios(path: Path) -> dict[str, float]:
    """measured/declared per tool, out of a `validate_tasks.json` artifact."""
    doc = json.loads(path.read_text())
    out: dict[str, float] = {}
    for row in doc.get("tasks", []):
        for dim, ratio in (row.get("cost_ratio") or {}).items():
            out[f"{row.get('tool', '?')}.{dim}"] = float(ratio)
    return out


def _warnings(spec: Any, view: ToolkitView, declared: list[str], scheduled: list[str],
              minimal: list[str], scrutiny: Scrutiny,
              per_cycle: dict[str, float]) -> list[str]:
    """What these figures cannot see. Each entry is a recorded defect, not a disclaimer."""
    out = [
        "The estimator is PARAMETER-BLIND: `Validator.estimate` sums one declared figure per "
        "graph node and reads no parameter, so raising a breadth knob (`num_designs`, "
        "`batch_size`, `nstruct`) buys N draws and moves no number in this offer, nor in any "
        "gate (backlog H10).",
        "`chain.declared` is an upper bound, not a guarantee: admission composes against the "
        "whole registry and nothing restricts a submitted Stage to the campaign's own "
        "`stages:`. Every shipped planner is narrowed to it by construction, which is a "
        "property of the policies rather than a gate (backlog G21).",
        "Wall time is not stable between identical runs, so `wall_hours` bounds rather than "
        "predicts, and no figure here should be tuned as if it were repeatable (backlog A11).",
    ]
    if not scrutiny.trusted:
        out.append(
            f"This pattern is UNTRUSTED at this site and width, so its first cycle is forced "
            f"through a dry run and capped at {scrutiny.cost_cap_fraction:.0%} of the budget "
            f"still available. A chain whose estimate exceeds that cap is refused before a "
            f"task runs - which is how a campaign can spend nothing and produce nothing.")
    if missing := [t for t in spec.stages if t not in view]:
        out.append(
            f"The campaign declares {missing}, which this toolkit does not have; they are "
            f"absent from the chain and from every figure here.")
    if unmet := [o.name for o in spec.objectives if not view.producer_of(o.name, declared)]:
        out.append(
            f"No enabled tool reports {unmet}, so the campaign cannot measure "
            f"{'them' if len(unmet) > 1 else 'it'} and a node will never be feasible against "
            f"{'those objectives' if len(unmet) > 1 else 'that objective'}.")
    if blown := [d for d, c in per_cycle.items()
                 if d in spec.budget and c > spec.budget[d]]:
        out.append(
            f"One cycle's declared estimate already exceeds the campaign's own budget in "
            f"{blown}, so gate 5 refuses the first graph. The campaign would stop having "
            f"spent nothing.")
    if (spare := sorted(set(scheduled) - set(minimal))):
        out.append(
            f"The declared chain is wider than the objectives require: {spare} produce no "
            f"declared objective's metric. They are priced because the campaign declared "
            f"them, and a reasoner may decline to run them.")
    return out
