"""Model C's Planner half: the other role inbox, and the one where a timeout matters.

Routed by the `role` key inside the existing `steer` directive - see
`policy/specifiers/external.py` for why that is one field rather than a second plane
operation. A directive with no `role` arrives here, which is what every existing caller and
`tests/test_http_adapter.py` send.

**`on_timeout` is the whole safety question of arm C.** A Planner that hears nothing has a
cycle to fill, and the three answers are not equivalent:

| `on_timeout` | behaviour | when it is right |
|---|---|---|
| `stop` | plan nothing; the campaign ends | **the experiment**, always |
| `hold` | wait with no deadline | a human-in-the-loop session |
| `fallback` | the declared fallback plans instead | a long unattended run |

`fallback` is what makes "a model-C arm that silently fell back and was reported as model C"
possible, and a fallen-back C arm is byte-for-byte a D campaign - invisible in the campaign
log, which is why the four-arm design names it as one of its two dangerous failures. So it
exists, it is never the default here, and taking it writes a `caller_timeout` transition with
the fallback's own name in it. `impress-a run --model C` is refused outright rather than
timing out (backlog C6), so the shape that bit cannot recur from the CLI.

**Being external confers no privilege.** A directive is composed, type-checked, gated and
budget-checked exactly as any planner's Stage is, and a rejection comes back to the caller with
its gate and reason for another turn. The wiring is `ThresholdPlanner`'s, because which port an
artifact arrives on is correctness rather than strategy: a caller is choosing what to run, not
re-deciding what unifies with what.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ...core.decision import ValidationFailure
from ...core.spec import Spec, Stage
from ..planner import BasePlanner, PlanningContext
from .explicit import ThresholdPlanner

log = logging.getLogger(__name__)

ON_TIMEOUT = ("hold", "fallback", "stop")

#: Keys a planner directive may carry.
DIRECTIVE_KEYS = frozenset({"role", "kind", "stages", "replicas", "params", "parent_node",
                            "rationale", "reason"})


class ExternalPlanner(BasePlanner):
    """Blocks on a `{"role": "planner"}` inbox; the caller chooses the work."""

    name = "external-plan"

    def __init__(self, stages: list[str] | None = None, timeout_s: float = 5.0,
                 on_timeout: str = "stop", fallback: Any = None, sink: Any = None) -> None:
        if on_timeout not in ON_TIMEOUT:
            raise ValueError(f"on_timeout must be one of {ON_TIMEOUT}")
        if on_timeout == "fallback" and fallback is None:
            raise ValueError(
                "on_timeout='fallback' needs a declared fallback planner. A fallback that "
                "does not exist is a campaign that stops without saying why it stopped, and "
                "one that does exist must be named in the campaign log - a fallen-back model "
                "C arm is byte-for-byte a model D campaign")
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.timeout_s, self.on_timeout = timeout_s, on_timeout
        self.fallback, self.sink = fallback, sink
        self.directives = 0
        self.rejections: list[ValidationFailure] = []
        self._mechanics = ThresholdPlanner(stages=stages)

    @property
    def stages(self) -> list[str]:
        return self._mechanics.stages

    # -- called by the control plane, through `RolePair.steer` ---------------
    def steer(self, directive: dict[str, Any]) -> None:
        self.inbox.put_nowait(directive)

    # -- Planner -------------------------------------------------------------
    async def plan(self, spec: Spec, ctx: PlanningContext) -> Stage | None:
        directive = await self._next(ctx.cycle)
        if directive is None:
            if self.on_timeout == "fallback" and self.fallback is not None:
                return await self.fallback.plan(spec, ctx)
            return None
        return await self._to_stage(directive, spec, ctx)

    async def replan(self, stage: Stage, rejection: ValidationFailure,
                     spec: Spec, ctx: PlanningContext) -> Stage | None:
        """The caller is told why and gets another turn - no privilege, but a fair one."""
        self.rejections.append(rejection)
        if self.sink:
            self.sink("transitions", {"event": "directive_rejected", "role": "planner",
                                      "cycle": ctx.cycle, "gate": rejection.gate,
                                      "reason": rejection.reason})
        directive = await self._next(ctx.cycle)
        if directive is None:
            if self.on_timeout == "fallback" and self.fallback is not None:
                return await self.fallback.replan(stage, rejection, spec, ctx)
            return None
        nxt = await self._to_stage(directive, spec, ctx)
        if nxt is not None:
            nxt.attempt = stage.attempt + 1
        return nxt

    async def _next(self, cycle: int) -> dict[str, Any] | None:
        """The next directive, or None when the caller was silent and we are not holding."""
        if self.on_timeout == "hold":
            return await self.inbox.get()
        try:
            directive = await asyncio.wait_for(self.inbox.get(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            log.warning("external planner: no directive in %.1fs; on_timeout=%s",
                        self.timeout_s, self.on_timeout)
            if self.sink:
                self.sink("transitions", {
                    "event": "caller_timeout", "role": "planner", "cycle": cycle,
                    "policy": self.on_timeout,
                    "fallback": getattr(self.fallback, "name", None)
                    if self.on_timeout == "fallback" else None})
            return None
        self.directives += 1
        return directive

    async def _to_stage(self, directive: dict[str, Any], spec: Spec,
                        ctx: PlanningContext) -> Stage | None:
        """A directive as a Stage, wired by `ThresholdPlanner`.

        An unknown key is refused rather than ignored, because a caller whose typo was ignored
        has been told its directive was accepted. A refusal returns no Stage, which ends the
        campaign - deliberately harsher than the Specifier's, where a refused revision leaves
        the Spec as it was and nothing is lost.
        """
        unknown = sorted(set(directive) - DIRECTIVE_KEYS)
        if unknown:
            log.error("external planner: unknown directive key(s) %s", unknown)
            if self.sink:
                self.sink("transitions", {"event": "directive_refused", "role": "planner",
                                          "cycle": ctx.cycle,
                                          "reason": f"unknown key(s) {unknown}"})
            return None
        if directive.get("kind") == "stop":
            return None

        # Per call, never assigned back. A caller naming a subset chooses this cycle's
        # work; it does not permanently narrow the campaign, which is what assigning to the
        # mechanics' own `stages` did - one directive shrank every later cycle too, and the
        # campaign kept running while measuring less. See `ThresholdPlanner.plan`.
        stage = await self._mechanics.plan(
            spec, ctx, chain=list(directive["stages"]) if directive.get("stages") else None,
            lineages=max(1, int(directive.get("replicas") or 1)))
        if stage is None:
            return None

        params = directive.get("params") or {}
        for task in stage.tasks:
            if extra := params.get(task.tool):
                # The caller wins on any key it set: it is choosing the experiment. The gates
                # still judge it, which is what "no privilege" means.
                task.params = {**task.params, **extra}
        if directive.get("parent_node"):
            stage.parent_node = str(directive["parent_node"])
        stage.rationale = str(directive.get("rationale") or f"{self.name}: external directive")
        return stage


__all__ = ["DIRECTIVE_KEYS", "ON_TIMEOUT", "ExternalPlanner"]
