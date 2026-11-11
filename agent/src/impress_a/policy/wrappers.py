"""Composable policy decorators.

Adopted from campaign_manager's `adr/policies/wrappers.py` (Phase 3, pattern #1). Wrapping
is how enforcement and provenance attach without touching policy internals - cleaner than
embedding checks inside each policy, and it implements Part B's "validation is external to
the policy".
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..core.decision import CampaignObservation, ComposeAndRun, Decision, Stop
from ..core.spec import Spec, SpecRevision

log = logging.getLogger(__name__)


class PolicyWrapper:
    def __init__(self, inner):
        self.inner = inner
        self.name = f"{type(self).__name__.lower()}({getattr(inner,'name','?')})"

    async def decide(self, obs: CampaignObservation) -> Decision:
        return await self.inner.decide(obs)

    async def interpret(self, results, obs):
        return await self.inner.interpret(results, obs)

    async def on_rejected(self, decision, failure):
        return await self.inner.on_rejected(decision, failure)


class LoggingPolicy(PolicyWrapper):
    """Provenance decorator: records every decision with its rationale."""

    def __init__(self, inner, sink: Callable[[str, dict[str, Any]], None]):
        super().__init__(inner)
        self.sink = sink

    async def decide(self, obs: CampaignObservation) -> Decision:
        d = await self.inner.decide(obs)
        self.sink("decisions", {"policy": getattr(self.inner, "name", "?"),
                                "cycle": obs.cycle, "decision": d.model_dump()})
        return d


class RuleCorrectionsPolicy(PolicyWrapper):
    """Unconditional external guard.

    Applies rule-based corrections to EVERY decision before it reaches composition -
    the separation-of-authority pattern from the flowgentic demo (Phase 3, pattern #3),
    made composable.
    """

    def __init__(self, inner, max_replicas: int = 16,
                 forbid_tools: tuple[str, ...] = ()):
        super().__init__(inner)
        self.max_replicas, self.forbid_tools = max_replicas, forbid_tools
        self.corrections: list[str] = []

    async def decide(self, obs: CampaignObservation) -> Decision:
        d = await self.inner.decide(obs)
        if isinstance(d, ComposeAndRun):
            if d.intent.replicas > self.max_replicas:
                self.corrections.append(
                    f"cycle {obs.cycle}: replicas {d.intent.replicas} -> {self.max_replicas}")
                d.intent.replicas = self.max_replicas
            bad = [t for t in d.intent.stages if t in self.forbid_tools]
            if bad:
                self.corrections.append(f"cycle {obs.cycle}: removed {bad}")
                d.intent.stages = [t for t in d.intent.stages if t not in self.forbid_tools]
                if not d.intent.stages:
                    return Stop(reason="all requested stages forbidden by guard")
        return d


# ---------------------------------------------------------------------------
# Role twins. The wrappers above decorate a `decide`; these decorate a half.
# ---------------------------------------------------------------------------

class LoggingSpecifier:
    """Provenance decorator for a Specifier half.

    Separate from the executor's own `specs` record rather than redundant with it: the
    executor records the revision it APPLIED, this records that this half AUTHORED it, and
    the four-arm experiment's Specifier attribution reads the second to tell a model that
    proposed nothing from one whose proposals were refused.
    """

    def __init__(self, inner: Any, sink: Callable[[str, dict[str, Any]], None]):
        self.inner = inner
        self.sink = sink
        self.name = f"logging({getattr(inner, 'name', '?')})"

    async def initial_spec(self, goal):
        spec = await self.inner.initial_spec(goal)
        self.sink("decisions", {"specifier": getattr(self.inner, "name", "?"),
                                "event": "initial_spec",
                                "objectives": [o.statement
                                               for o in spec.objectives.values()]})
        return spec

    async def revise(self, spec, ev):
        rev = await self.inner.revise(spec, ev)
        if not rev.is_empty:
            self.sink("decisions", {"specifier": getattr(self.inner, "name", "?"),
                                    "event": "revise", "cycle": ev.cycle,
                                    "new": [o.statement for o in rev.new_objectives],
                                    "deleted": list(rev.deleted),
                                    "rationale": rev.rationale})
        return rev

    async def satisfied(self, spec, ev):
        return await self.inner.satisfied(spec, ev)


class StageGuard:
    """Unconditional external guard for a Planner half.

    The decision-level guard above cannot be reused: it corrects an `ExperimentIntent`, and a
    `Stage` is a different object with lineages and per-task parameters. What it checks is
    narrower than its predecessor on purpose, because two of the three corrections
    `RuleCorrectionsPolicy` made are now enforced where they cannot be bypassed:

    * the **replica cap** is applied by the executor against the campaign's own `replicas`,
      so a Stage asking wider is trimmed whether or not a guard is attached - and `--no-guard`
      no longer turns that off, which it should never have;
    * a **task serving no objective** is refused by the Reviewer's coverage gate, with the
      gate and the task named.

    What remains here is `forbid_tools`, which nothing else enforces until phase 10's gate 6
    refuses a mock-toolkit node under `tool_delivery: real`. A guard is the wrong place for
    that check and gate 6 is the right one - `--no-guard` disables this and cannot disable a
    gate - so this is a stopgap and says so.

    It **refuses rather than edits**. Dropping a forbidden tool from a chain leaves a hole
    where a producer was, which is the truncation that took the only producer of two of four
    objectives off job 22675512; and a planner's Stage is wired by port, so removing a task
    leaves the tasks that consumed it pointing at nothing.
    """

    def __init__(self, inner: Any, forbid_tools: tuple[str, ...] = (),
                 max_lineages: int = 16):
        self.inner = inner
        self.forbid_tools = tuple(forbid_tools)
        self.max_lineages = max_lineages
        self.name = f"guard({getattr(inner, 'name', '?')})"
        self.refusals: list[str] = []

    @property
    def stages(self) -> list[str]:
        return getattr(self.inner, "stages", [])

    def steer(self, directive: dict[str, Any]) -> None:
        """Pass an external directive through, so wrapping model C still answers `steer`."""
        self.inner.steer(directive)

    def _check(self, stage: Any) -> Any:
        if stage is None:
            return None
        if bad := sorted({t.tool for t in stage.runs} & set(self.forbid_tools)):
            self.refusals.append(f"stage {stage.id}: forbidden tool(s) {bad}")
            log.error("guard: refusing stage %s - forbidden tool(s) %s. Not edited out: "
                      "removing a task leaves the tasks wired to it pointing at nothing",
                      stage.id, bad)
            return None
        if stage.lineages > self.max_lineages:
            keep = self.max_lineages
            self.refusals.append(
                f"stage {stage.id}: lineages {stage.lineages} -> {keep}")
            log.warning("guard: trimming stage %s from %d lineages to %d",
                        stage.id, stage.lineages, keep)
            stage.tasks = [t for t in stage.tasks if t.lineage < keep]
        return stage

    async def plan(self, spec, ctx):
        return self._check(await self.inner.plan(spec, ctx))

    async def replan(self, stage, rejection, spec, ctx):
        return self._check(await self.inner.replan(stage, rejection, spec, ctx))


class NullSpecifier:
    """An empty Spec, so `complete()` is trivially true and the Listener stops at once.

    Today's `NullPolicy` semantics with no special case anywhere else: `Spec.complete()` is
    "nothing is open", an empty Spec satisfies that, and the campaign ends through the
    designed path rather than through a `Stop` the driver has to recognise.
    """

    name = "null-spec"

    async def initial_spec(self, goal):
        del goal
        return Spec()

    async def revise(self, spec, ev):
        del spec, ev
        return SpecRevision()

    async def satisfied(self, spec, ev):
        del spec, ev
        return []


class NullPlanner:
    """Never asked, because the Spec is already complete. Answers anyway, with nothing."""

    name = "null-plan"
    stages: list[str] = []

    async def plan(self, spec, ctx):
        del spec, ctx
        return None

    async def replan(self, stage, rejection, spec, ctx):
        del stage, rejection, spec, ctx
        return None


class NullPolicy:
    """No-op baseline. Stops immediately - useful as a control and in smoke tests."""

    name = "null"

    async def decide(self, obs: CampaignObservation) -> Decision:
        return Stop(reason="null policy")

    async def interpret(self, results, obs):
        return None

    async def on_rejected(self, decision, failure):
        return Stop(reason="null policy")
