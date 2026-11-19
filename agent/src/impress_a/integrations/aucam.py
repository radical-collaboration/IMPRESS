"""One IMPRESS-A campaign as one AuCaM workflow.

AuCaM (`radical-project/campaign_manager`) is the canonical superstrate: it launches a
workflow as an `async def` taking a reporter, gives it a spending limit and resources, bounds
its spending, may pause or cancel it, and reads its progress back through `reporter.emit()`.
Decision 0014 says what that makes it - a caller, and specifically NOT control model C, which
is a reasoner over `CampaignSession` that publishes Specs and submits Stages. AuCaM steers no
Spec and plans no Stage. It owns the process and the engine (CON-1): the caller builds its
`CampaignManager` over `impress_backends()`, so AuCaM's one engine has our `compute` and
`local` routes, and our tasks run - and are cancelled - inside AuCaM's block for this
workflow. IMPRESS-A keeps the outer loop and the decision to stop.

**The only module in this package that imports AuCaM**, which `tests/test_layering.py`
asserts, so the dependency stays optional and one file wide.

Two things the caller must do with what it gets back, and neither is this module's to do:

* `workflow_config()` fills `spending_limit` (the offer's ceiling per billed dimension),
  `budget_floor`, `resources` and `max_wall_time_s`. AuCaM starts from that limit and, once
  it has learned the type's cost, sizes later launches itself (learned cost + margin); a
  caller that wants a different amount for one launch sets `LaunchRequest.spending_limit`.
* `reward_fn()` exists because AuCaM's default bandit reward is `1.0 if returncode == 0 else
  0.0` - throughput, and its own comment says science scores belong to the controller. No
  shipped AuCaM policy can rank a dict, so the digest's scalar progress is what we report and
  this is what turns it into a reward.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.decision import CampaignDigest
from .reporting import PAUSE, RESUME, Bridge, deliver, run_with_sink

log = logging.getLogger("impress_a.aucam")

#: Dimensions AuCaM charges against a spending limit. `wall_hours` is not one: AuCaM refuses
#: it in `spending_limit`, and run time is bounded by `max_wall_time_s` instead.
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


async def impress_backends(spec_path: str | Path) -> list[Any]:
    """The backends to build AuCaM's engine over: `CampaignManager(backend=await
    impress_backends(spec))`.

    `[compute, local]`, plus `ai` when the campaign's reasoner is a locally hosted model -
    the routes our tasks are sent to by name, `compute` first so it is the engine's default.
    Built from the spec's `backend` and `backend_config`, bounded by its
    `backend_startup_timeout_s` exactly as a standalone campaign's own engine is. Await it on
    the loop AuCaM will run on: a backend binds to the loop its async init runs on.

    AuCaM does not shut down backends it was given, so the caller shuts them down when it is
    done with the manager (`await b.shutdown()` for each).
    """
    from ..cli import load_spec  # noqa: PLC0415 - see module docstring
    from ..runtime.executor import engine_routes  # noqa: PLC0415

    return await engine_routes(load_spec(str(spec_path)))


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


def _spending_limit(offer: Any) -> dict[str, float]:
    """The offer's ceiling for each billed dimension it costs anything in."""
    limit = {d: float(offer.cost[d].ceiling) for d in _BILLED
             if d in offer.cost and offer.cost[d].ceiling > 0}
    if not limit:
        raise ValueError(
            f"offer {offer.campaign_id!r} has no positive cost in {_BILLED}; AuCaM needs a "
            f"spending_limit in at least one of them")
    return limit


def workflow_config(spec_path: str | Path, *, name: str | None = None, model: str = "D",
                    report_interval_s: float = 30.0, guard: bool = True,
                    offer: Any = None, on_message: Any = None, **overrides: Any) -> Any:
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

    config = {
        "name": name or offer.campaign_id,
        "block": make_impress_worker(spec_path, model=model, guard=guard,
                                     report_interval_s=report_interval_s,
                                     on_message=on_message),
        # Our own budget, which the campaign already enforces from the inside: gate 5 and the
        # interlock refuse an unaffordable graph BEFORE a task runs. AuCaM's cancel is a
        # backstop, not the mechanism.
        # AuCaM requires a spending limit for every workflow type: it is both the starting
        # limit per launch and what it holds against the campaign while we run. The ceiling
        # is our own budget where the spec sets one, else expected cost x max cycles.
        "spending_limit": _spending_limit(offer),
        # Minimum viable budget: the cost of one minimal cycle.  When AuCaM would pass a
        # spending_limit below this, the launch is pointless — gate 5 would reject it
        # immediately.  AuCaM drops it at the scheduler level (unfit_dropped++) instead.
        "budget_floor": {d: offer.cost[d].floor for d in _BILLED
                         if d in offer.cost and offer.cost[d].floor > 0},
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
    falls back to charging the resources we were given x elapsed time, which is the least
    accurate of its three charging methods. Those keys carry the MEASURED figures, because the
    declared ones sit multiples above measurement on purpose and would hand the caller our
    headroom as if it were consumption (backlog G20).
    """

    def __init__(self, reporter: Any, extras: Sequence[Mapping[str, Any]] = ()) -> None:
        self.reporter = reporter
        self.emitted = 0
        #: Caller fields, merged into EVERY report, in order, after the billed keys. Read at
        #: report time rather than copied here, so a caller that keeps the mapping can change
        #: a value mid-campaign and the next report carries it.
        self.extras = tuple(extras)
        self._warned_clash = False

    async def report(self, digest: CampaignDigest) -> None:
        metrics = digest.model_dump(mode="json")
        for extra in self.extras:
            metrics.update(extra)
        # Billed LAST, so a caller's field can neither drop nor overwrite what AuCaM charges
        # from. A collision is the caller's bug and silence would make it an accounting hole,
        # so it is logged - once, because this runs every report.
        billed = self._billed(digest)
        if not self._warned_clash and (clash := set(billed) & self._extra_keys):
            log.warning("ignoring caller metric(s) %s: these are the keys AuCaM charges from",
                        sorted(clash))
            self._warned_clash = True
        metrics.update(billed)
        await self.reporter.emit(score=digest.progress, metrics=metrics,
                                 iteration=digest.cycle)
        self.emitted += 1

    @property
    def _extra_keys(self) -> set[str]:
        return {key for extra in self.extras for key in extra}

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

    async def messages(self) -> list[tuple[str, Any]]:
        """AuCaM's `PolicyResult.messages` to this workflow, as `(name, payload)`."""
        take = getattr(self.reporter, "messages", None)
        if take is None:
            return []
        return [(m.name, m.payload) for m in await take()]


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
                        report_interval_s: float = 30.0, on_message: Any = None,
                        spec_patch: Any = None, extra_metrics: Any = None) -> Any:
    """An AuCaM block function running one whole IMPRESS-A campaign.

    The config is captured in this closure and the campaign is built inside the coroutine,
    which is the shape AuCaM's own `make_miniapps_worker` uses and is load-bearing here: the
    executor creates `asyncio.Event`s in `__init__` and calls
    `get_running_loop().create_future()` when it dispatches, so a manager built in the closure
    would bind to whatever loop imported this module.

    **It declares `flow`** (CON-1), so AuCaM passes its one engine and the campaign runs on
    it: its tasks are inside AuCaM's block for this workflow, so cancelling the workflow
    cancels them, and AuCaM sees them in its own telemetry and load. The engine must carry
    our routes - build AuCaM's manager over `impress_backends()` - and the executor checks
    that at start rather than at the first task. It was built on AuCaM's running loop, which
    is the loop this coroutine runs on, so the loop hazard that jobs 22328172 and 22328262
    hit (an engine built on a throwaway loop) does not arise. Called with no `flow`, the
    campaign builds its own engine as it does standalone.

    Spending still travels in our own reports: AuCaM charges per task only once AsyncFlow
    puts a task's requested resources on its events (X1), and the measured figures are the
    better ones meanwhile.

    **Messages from AuCaM's controller** (`PolicyResult.messages`) go to
    `on_message(manager, name, payload)` - e.g. `("model", {...})` when a fine-tuned model is
    promoted. The type's sticky values arrive in `context["messages"]` and are applied before
    the campaign starts; later ones while it runs, through the bridge (`Bridge`). What a
    message means to the campaign - which model a role uses, say - is the handler's to decide.

    **Two seams for a caller running several campaigns from one spec file**, both optional and
    both inert when unset. They exist because AuCaM's ASD prototype campaign rebuilt this
    worker body by hand to get them, importing three private names from this module
    (`campaigns/asd_campaign/README.md`, its gap 5).

    * `spec_patch(spec, context)` runs after `load_spec` and **before** the budget and
      resource fitting, which is where a per-launch identity goes: `spec.campaign_id` and
      `spec.root`, because two launches from one YAML otherwise write into the same run
      directory and the second clobbers the first. It may return a mapping, which is then
      merged into every report of **that launch** - the way a caller gets a value it computed
      while patching, such as the directory the run will write to, back out through telemetry.
    * `extra_metrics` is a mapping, or a callable taking the context and returning one,
      merged into every report. A callable is called once per launch, so use it for anything
      per-launch; a bare mapping is shared by every launch of this worker, which is right for
      a constant tag and wrong for anything else.

    Both are merged **after** the billed keys and read at report time, not copied. Two
    consequences worth stating, because each is a silent failure otherwise:

    * **A caller's fields cannot touch AuCaM's accounting.** `cpu_hours`, `gpu_hours` and
      `*_in_use` are written last, every report, so a caller can neither drop them by emitting
      a report of its own instead nor overwrite them by naming one; a collision is logged
      once and ignored. Merging here is what makes that impossible rather than discouraged.
    * **A field changed mid-campaign is picked up.** The mapping is read at each report, so a
      caller whose `on_message` handler records a newly promoted model version sees it on the
      next report rather than at the next launch. A caller that wants a value frozen at launch
      should pass a copy.
    """
    from ..cli import build_roles, load_spec  # noqa: PLC0415
    from ..manager import CampaignManager  # noqa: PLC0415
    from ..tools.registry import Registry  # noqa: PLC0415

    async def impress_a_campaign(reporter: Any, context: dict | None = None,
                                 flow: Any = None) -> None:
        ctx = context or {}
        spec = load_spec(str(spec_path))

        # Before the budget and the resources, so a patch that changes the campaign's
        # identity cannot be undone by them, and a patch can read what they will act on.
        extras: list[Mapping[str, Any]] = []
        if extra_metrics is not None:
            extras.append(extra_metrics(ctx) if callable(extra_metrics) else extra_metrics)
        if spec_patch is not None and (patched := spec_patch(spec, ctx)) is not None:
            extras.append(patched)

        if narrowed := _narrow_budget(spec, ctx.get("spending_limit")):
            log.info("the caller's spending limit is now this campaign's budget: %s",
                     "; ".join(narrowed))
        _fit_resources(spec, ctx.get("resources"))

        # The cgroup is shared with every sibling workflow under an enclosing manager, so
        # `sched_getaffinity` describes the allocation rather than our share of it: the
        # caller's own grant sizes each command's thread caps instead. Per command, not via
        # this process's environment, which every sibling workflow would also inherit.
        cpus = int((ctx.get("resources") or {}).get("cpus", 0) or 0)

        mgr = CampaignManager(spec, build_roles(model, spec, guard), Registry().load(),
                              flow=flow)
        mgr.executor.cpu_share = cpus or None
        for msg_name, payload in (ctx.get("messages") or {}).items():
            deliver(mgr, on_message, msg_name, payload)
        sink = _ReporterSink(reporter, extras)
        result = await run_with_sink(mgr, sink, period_s=report_interval_s,
                                     on_message=on_message)
        log.info("campaign %s ended: %s (%d report(s) emitted)",
                 result.campaign_id, result.stop_reason, sink.emitted)

    impress_a_campaign.__name__ = f"impress_a_{Path(str(spec_path)).stem}".replace("-", "_")
    impress_a_campaign.__qualname__ = impress_a_campaign.__name__
    return impress_a_campaign


async def report_once(manager: Any, reporter: Any) -> CampaignDigest:
    """Emit one digest for a campaign somebody else is driving. For tests and for a caller
    that wants a reading at a moment of its own choosing rather than on our cadence."""
    return await Bridge(manager, _ReporterSink(reporter)).report_once()
