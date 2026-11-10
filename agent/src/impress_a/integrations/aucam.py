"""One IMPRESS-A campaign as one AuCaM workflow.

AuCaM (`radical-project/campaign_manager`) is the canonical superstrate: it launches a
workflow as an `async def` taking a reporter, sizes it from a declared cost, bounds its
spending, may pause or cancel it, and reads its progress back through `reporter.emit()`.
Decision 0014 says what that makes it - a caller, and specifically NOT control model C, which
is a reasoner over `CampaignSession` that publishes Specs and submits Stages. AuCaM steers no
Spec and plans no Stage. It owns the process; IMPRESS-A keeps the engine, the outer loop and
the decision to stop.

**The only module in this package that imports AuCaM**, which `tests/test_layering.py`
asserts, so the dependency stays optional and one file wide.

Two things the caller must do with what it gets back, and neither is this module's to do:

* `workflow_config()` fills `declared_spending`, `spending_limit` and `resources`, because
  those are `WorkflowConfig` fields. A cost RANGE is not: `bounds` lives on `LaunchRequest`,
  so `launch_bounds()` hands it over separately for the caller's own controller to attach,
  where `SchedulingPolicy.size()` resolves it against learned costs this side never sees.
* `reward_fn()` exists because AuCaM's default bandit reward is `1.0 if returncode == 0 else
  0.0` - throughput, and its own comment says science scores belong to the controller. No
  shipped AuCaM policy can rank a dict, so the digest's scalar progress is what we report and
  this is what turns it into a reward.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from ..core.decision import CampaignDigest
from .reporting import PAUSE, RESUME, Bridge, run_with_sink

log = logging.getLogger("impress_a.aucam")

#: Dimensions AuCaM charges against a spending limit. `wall_hours` is excluded on purpose: it
#: is an input to AuCaM's proration, not a thing it bills, and offering it as a limit would
#: cancel a campaign for taking the time it declared it would take.
_BILLED = ("gpu_hours", "cpu_hours")


def _aucam() -> Any:
    """Import AuCaM, under whichever name this install exposes it.

    Its distribution is named `aucam`, but upstream's
    `[tool.setuptools.packages.find]` declares `include = ["src*"]`, so the importable
    package is the generic name `src` - which setuptools itself warns about at install time.
    This repository has `src/` at its root and `agent/src/` under it, neither a package, so a
    same-named namespace portion sits ahead of AuCaM's on the path whenever the working
    directory is either one. It resolves because a regular package beats a namespace portion,
    but when it does not, the error must say so rather than blame this adapter.
    """
    try:
        import src.aucam as mod  # noqa: PLC0415 - optional dependency
        return mod
    except ImportError as first:
        try:
            import aucam as mod  # noqa: PLC0415 - if upstream ever renames
            return mod
        except ImportError:
            try:
                import src  # noqa: PLC0415 - for the diagnostic only
                where = list(getattr(src, "__path__", []))
            except ImportError:
                where = []
            raise ImportError(
                f"AuCaM is not importable as `src.aucam` or `aucam` ({first}). Install the "
                f"extra: `pip install -e '.[aucam]'`. Note its import path is `src.aucam`, "
                f"not `aucam` - the distribution is named `aucam` but it ships a top-level "
                f"package called `src`. Resolved `src.__path__` = {where or '<not found>'}; "
                f"if that names a directory in THIS repository, a same-named namespace "
                f"package has shadowed it."
            ) from first


# ---------------------------------------------------------------------------
# What the caller needs before it launches anything
# ---------------------------------------------------------------------------


def launch_bounds(offer: Any) -> dict[str, tuple[float, float]]:
    """`{dimension: (floor, ceiling)}`, for the caller's own `LaunchRequest.bounds`.

    Separate from `workflow_config` because `bounds` is a `LaunchRequest` field and not a
    `WorkflowConfig` one - the controller attaches it per launch, and
    `SchedulingPolicy.size()` then picks a point inside it using its own learned costs, which
    after enough runs will be better than anything declared on this side.
    """
    return {dim: rng for dim, rng in offer.bounds().items() if dim in _BILLED}


def reward_fn(result: Any) -> float:
    """A `WorkflowResult` as a reward in [0, 1], for `BanditSchedulingPolicy(reward_fn=...)`.

    A cancelled or failed campaign scores 0 whatever it had found, because the bandit is
    choosing whether to launch this arm again and a run that could not finish is not evidence
    that it would. A completed one scores the progress its final digest reported.
    """
    if getattr(result, "returncode", 1) != 0:
        return 0.0
    score = getattr(result, "final_score", None)
    return float(score) if isinstance(score, (int, float)) else 0.0


def workflow_config(spec_path: str | Path, *, name: str | None = None, model: str = "D",
                    report_interval_s: float = 30.0, guard: bool = True,
                    offer: Any = None, **overrides: Any) -> Any:
    """An AuCaM `WorkflowConfig` for one whole IMPRESS-A campaign.

    Built from the same `impress-a offer` a caller could read for itself, so the numbers
    AuCaM sizes with are the numbers the offer declares - and `warnings` is logged here rather
    than discarded, because a caller that never read the offer still ought to hear that the
    estimate is parameter-blind.
    """
    from ..cli import load_spec  # noqa: PLC0415 - see module docstring
    from ..runtime.offer import offer_for_spec  # noqa: PLC0415

    aucam = _aucam()
    spec = load_spec(str(spec_path))
    offer = offer or offer_for_spec(spec, report_interval_s=report_interval_s)
    for warning in offer.warnings:
        log.warning("offer: %s", warning)

    declared = {d: offer.cost[d].expected for d in _BILLED if d in offer.cost}
    if "wall_hours" in offer.cost:
        # AuCaM prorates an unreported spend against this, so too SMALL a figure makes the
        # proration exceed 100% and cancel a campaign that is behaving normally. The offer
        # reports the ceiling for exactly this reason.
        declared["wall_hours"] = offer.cost["wall_hours"].expected

    config = {
        "name": name or offer.campaign_id,
        "block": make_impress_worker(spec_path, model=model, guard=guard,
                                     report_interval_s=report_interval_s),
        "declared_spending": declared,
        # Our own budget, which the campaign already enforces from the inside: gate 5 and the
        # interlock refuse an unaffordable graph BEFORE a task runs. AuCaM's cancel is a
        # backstop, not the mechanism.
        "spending_limit": {d: offer.cost[d].ceiling for d in _BILLED
                           if d in offer.cost and offer.cost[d].bounded_by_budget},
        "resources": {"cpus": offer.resources.cores, "gpus": offer.resources.gpus},
        "supports_pause": True,
        # The offer declares the report interval so a caller's staleness bound can be a
        # multiple of it. 4x and not AuCaM's stated 3x minimum, because 3x is the floor the
        # contract names rather than a margin, and a child of this process can spend minutes
        # in `import pyrosetta` alone off slow storage.
        "stale_timeout_s": 4 * report_interval_s,
        "max_wall_time_s": float(offer.resources.walltime_s_ceiling) or None,
    }
    config.update(overrides)
    return aucam.WorkflowConfig(**config)


# ---------------------------------------------------------------------------
# The workflow itself
# ---------------------------------------------------------------------------


class _ReporterSink:
    """A `CycleSink` that emits to AuCaM and reads its PAUSE/RESUME back.

    `score` is a float, not a dict: AuCaM's default bandit reward is throughput, and no
    shipped policy of theirs can rank a dict. The rich payload travels in `metrics`, where
    `cpu_hours`/`gpu_hours` are the keys AuCaM's own `_spent_so_far` reads - without them it
    falls back to prorating our declared cost by elapsed time, which is the least accurate of
    its three charging methods. Those keys carry the MEASURED figures, because the declared
    ones sit multiples above measurement on purpose and would hand the caller our headroom as
    if it were consumption (backlog G20).
    """

    def __init__(self, reporter: Any) -> None:
        self.reporter = reporter
        self.emitted = 0

    async def report(self, digest: CampaignDigest) -> None:
        metrics = digest.model_dump(mode="json")
        metrics.update(self._billed(digest))
        await self.reporter.emit(score=digest.progress, metrics=metrics,
                                 iteration=digest.cycle)
        self.emitted += 1

    @staticmethod
    def _billed(digest: CampaignDigest) -> dict[str, float]:
        """What AuCaM charges us for, under the names it looks for."""
        billed: dict[str, float] = {}
        for dim in _BILLED:
            if (value := digest.spend_measured.get(dim)) is not None:
                billed[dim] = value
        # `*_in_use` is what AuCaM checks a resource grant against. Declared, because what a
        # graph HOLDS is a property of its shape rather than of its measured cost.
        billed["cpus_in_use"] = float(digest.in_flight.get("cpu_hours", 0.0) > 0)
        billed["gpus_in_use"] = float(digest.in_flight.get("gpu_hours", 0.0) > 0)
        return billed

    async def poll(self) -> str | None:
        """Translate AuCaM's own signal vocabulary into the bridge's."""
        decision = await self.reporter.poll()
        if decision is None:
            return None
        name = getattr(decision, "name", str(decision)).upper()
        if "PAUSE" in name:
            return PAUSE
        if "RESUME" in name:
            return RESUME
        log.info("ignoring an AuCaM signal this adapter does not act on: %r", decision)
        return None


def _narrow_budget(spec: Any, limit: dict[str, float] | None) -> list[str]:
    """Make the caller's spending limit the campaign's own budget.

    This is the load-bearing line of the adapter. A limit enforced from OUTSIDE can only
    cancel a campaign after it has overspent; the same number as a budget is refused from the
    inside, by `reserve` and gate 5, before a task runs - and the campaign stops itself with a
    reason naming the dimension instead of being killed with work in flight. It is
    `core/budget.Commitment`'s own rule, `min(goal.budget[d], ...)`, applied one level up.
    """
    narrowed = []
    for dim, value in (limit or {}).items():
        if dim not in _BILLED:
            continue
        current = spec.budget.get(dim, math.inf)
        if value < current:
            spec.budget[dim] = float(value)
            narrowed.append(f"{dim} {current if current != math.inf else 'unbounded'}"
                            f" -> {value}")
    return narrowed


def _fit_resources(spec: Any, resources: dict[str, float] | None) -> None:
    """Size the campaign to the share of the node the caller actually gave us.

    `concurrency` is clamped by the GPUs on offer, because every P1 stage wants one and a
    lineage that cannot get one waits. `site.gpus_per_node` is deliberately NOT clamped down:
    gate 4 refuses a graph whose tool wants more GPUs than the site has, so lowering it would
    make the campaign refuse its own chain and produce nothing rather than run narrower.
    """
    if not resources:
        return
    if gpus := int(resources.get("gpus", 0) or 0):
        per_lineage = max(1, spec.replicas or 1)
        spec.concurrency = max(1, min(max(1, spec.concurrency), gpus // per_lineage or 1))
    log.info("fitted to the caller's grant %s: concurrency=%d replicas=%d",
             dict(resources), spec.concurrency, spec.replicas)


def make_impress_worker(spec_path: str | Path, *, model: str = "D", guard: bool = True,
                        report_interval_s: float = 30.0) -> Any:
    """An AuCaM block function running one whole IMPRESS-A campaign.

    The config is captured in this closure and the campaign is built inside the coroutine,
    which is the shape AuCaM's own `make_miniapps_worker` uses and is load-bearing here: the
    executor creates `asyncio.Event`s in `__init__` and calls
    `get_running_loop().create_future()` when it dispatches, so a manager built in the closure
    would bind to whatever loop imported this module.

    **It does not declare `flow`.** AuCaM passes its shared engine to a block that asks for
    one, and taking it would be wrong twice over: `WorkflowEngine.__init__` captures the loop
    it is built on, and the executor builds its own through the only sanctioned constructor,
    `exec.backend.make_engine_bounded`, which also bounds Dragon's synchronous startup. There
    is no "use this engine instead" seam, and inventing one here is how jobs 22328172 and
    22328262 spent their full allocations on an engine that dispatched nothing. The cost of
    not taking it is that our tasks are invisible to AuCaM's per-task telemetry, so its
    task-level charging never applies - which is why spending travels in our own reports.
    """
    from ..cli import _thread_caps, build_roles, load_spec  # noqa: PLC0415
    from ..manager import CampaignManager  # noqa: PLC0415
    from ..tools.registry import Registry  # noqa: PLC0415

    async def impress_a_campaign(reporter: Any, context: dict | None = None) -> None:
        import os  # noqa: PLC0415

        ctx = context or {}
        spec = load_spec(str(spec_path))
        if narrowed := _narrow_budget(spec, ctx.get("spending_limit")):
            log.info("the caller's spending limit is now this campaign's budget: %s",
                     "; ".join(narrowed))
        _fit_resources(spec, ctx.get("resources"))

        # The cgroup is shared with every sibling workflow under an enclosing manager, so
        # `sched_getaffinity` describes the allocation rather than our share of it.
        cpus = int((ctx.get("resources") or {}).get("cpus", 0) or 0)
        for var, val in _thread_caps(spec, cpus or None).items():
            os.environ.setdefault(var, val)

        mgr = CampaignManager(spec, build_roles(model, spec, guard), Registry().load())
        sink = _ReporterSink(reporter)
        result = await run_with_sink(mgr, sink, period_s=report_interval_s)
        log.info("campaign %s ended: %s (%d report(s) emitted)",
                 result.campaign_id, result.stop_reason, sink.emitted)

    impress_a_campaign.__name__ = f"impress_a_{Path(str(spec_path)).stem}".replace("-", "_")
    impress_a_campaign.__qualname__ = impress_a_campaign.__name__
    return impress_a_campaign


async def report_once(manager: Any, reporter: Any) -> CampaignDigest:
    """Emit one digest for a campaign somebody else is driving. For tests and for a caller
    that wants a reading at a moment of its own choosing rather than on our cadence."""
    return await Bridge(manager, _ReporterSink(reporter)).report_once()
