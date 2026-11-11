"""The control plane as roles: Listener, Specifier, Planner, Deployer.

One `conduct(session)` implementation, so the manager needs no new wiring: it already races a
reasoner's `conduct` against the executor's pump, and a role pipeline is a reasoner that happens
to be four cooperating responsibilities rather than one.

**Written against `CampaignSession`, never against the executor.** That is the whole reason
phase 1 builds this in-process: the same code runs across a socket in phase 7, where the Spec
Loop and Planning Loop move into a control process with their own event loop. The one engine
stays on the execution process's loop - `WorkflowEngine.__init__` captures the loop it is built
on, and an engine built elsewhere dispatches nothing while looking healthy (jobs 22328172,
22328262, two full allocations) - but nothing here touches an engine, so nothing here is
constrained by that.

The four responsibilities, and where each one lives in `conduct`:

* **Listener** - `_listen`: collect finished runs, ingest them into the `DataRegistry`, ask the
  Specifier which objectives are now satisfied, apply that, and stop the campaign when the Spec
  is complete. It *asks* to stop; the executor decides whether the campaign has actually ended,
  because budget, stagnation and repeated failure are facts about state a reasoner cannot see.
* **Specifier** - `_respecify`: one `revise` per signal, applied through the session so the
  executor remains the only writer and `specs` provenance is executor-written.
* **Planner** - `plan`/`replan`, with bounded retry per experiment.
* **Deployer** - `_deploy`: submit, and hold at most `concurrency` experiments open.

Phase 1 keeps two pieces of scaffolding, both named and both deleted later: `_intent_for`,
which renders a Stage back into the `ExperimentIntent` the executor already accepts (phase 3
gives the executor `submit_stage` and this goes), and the `LegacyPlanner` overflow attributes,
which carry the three non-planning members of the old Decision union (phase 11 goes with
`ControlPolicy`).
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.data import DataRegistry, TaskFuture
from ..core.decision import ExperimentIntent
from ..core.goal import Goal
from ..core.session import CampaignSession, CampaignStopped, SubmissionRejected
from ..core.spec import ObjectiveStatus, Spec, SpecRevision, Stage
from ..policy.legacy import LegacyPlanner
from ..policy.planner import PlanningContext
from ..policy.specifier import SpecEvidence

log = logging.getLogger(__name__)


def _intent_for(stage: Stage, goal: Goal) -> ExperimentIntent:
    """Stage -> an equivalent intent. No longer on the submit path; kept for one test.

    `session.submit_stage` is the submit path now, so the executor composes the Stage directly
    and the round trip this performed is gone. It survives only as the fixture for
    `test_a_stage_round_trips_through_an_intent`, which is worth keeping as the record that
    the two paths describe the same graph - phase 11 deletes it with `ExperimentIntent`.
    """
    runs = stage.runs
    tools = [t.tool for t in runs if t.lineage == 0]
    params: dict[str, Any] = {}
    for t in runs:
        if t.params:
            params.setdefault(t.tool, {}).update(t.params)
    return ExperimentIntent(goal=goal.text, stages=tools, params=params,
                            replicas=stage.lineages)


class RolesDriver:
    """Listener + Specifier + Planner + Deployer over one `CampaignSession`."""

    name = "roles"

    def __init__(self, goal: Goal, specifier: Any, planner: Any, *, max_turns: int = 6,
                 max_attempts: int = 4, concurrency: int = 1,
                 publish: Any = None) -> None:
        self.goal = goal
        self.specifier = specifier
        self.planner = planner
        # Injected rather than discovered on the session. `publish_spec` is not a
        # `CampaignSession` member yet - it becomes one in phase 3, alongside `submit_stage`,
        # because ADR 0007 forbids an adapter carrying an operation the core protocol lacks and
        # `RemoteSession` cannot honour it until the plane does. Until then the driver declares
        # what it needs and the manager supplies the executor's own applier; duck-typing the
        # session for it would make "which objects answer this" unanswerable, which is the cost
        # `control/plane.py` paid for duck-typing `steer`.
        self.publish = publish
        self.max_turns = max_turns
        self.max_attempts = max_attempts
        self.concurrency = max(1, concurrency)
        self.data = DataRegistry()
        self.spec: Spec = Spec()

    # -- the loop ------------------------------------------------------------
    async def conduct(self, session: CampaignSession) -> None:
        outstanding: list[str] = []
        turn = 0
        branched = False
        try:
            self.spec = await self.specifier.initial_spec(self.goal)
            await self._publish(session, None)

            while turn < self.max_turns:
                obs = await session.observe()
                ev = SpecEvidence(obs, self.data)

                await self._respecify(session, ev)
                if self.spec.complete():
                    return await session.stop("every spec objective satisfied")

                ctx = PlanningContext(self.goal, obs, in_flight=list(outstanding),
                                      last_rejection=obs.last_rejection)
                stage = await self.planner.plan(self.spec, ctx)
                if stage is None:
                    acted = await self._handle_overflow(session, branched)
                    if acted == "branched":
                        branched = True
                        continue
                    return

                run_id = await self._deploy(session, stage, ctx, turn)
                if run_id is None:
                    return
                turn += 1
                branched = False
                outstanding.append(run_id)

                # Hold at most `concurrency` experiments open. At the default of 1 this waits
                # for each before asking again, which is the serial cycle the legacy driver
                # preserved and which parity depends on.
                while len(outstanding) >= self.concurrency:
                    await self._listen(session, outstanding.pop(0))

            await session.stop(f"max_cycles={self.max_turns} reached")
        except CampaignStopped:
            return      # the executor ended the campaign; it owns the reason

    # -- Listener ------------------------------------------------------------
    async def _listen(self, session: CampaignSession, run_id: str) -> None:
        """Collect one experiment, ingest it, and let the Planner see it.

        The observation is taken AFTER the outcome lands, so anything reading it sees the state
        the run produced rather than the state it started from.
        """
        outcome = await session.result(run_id)
        self.data.ingest(outcome)
        if isinstance(self.planner, LegacyPlanner):
            await self.planner.after_collect(outcome, await session.observe())

    # -- Specifier -----------------------------------------------------------
    async def _respecify(self, session: CampaignSession, ev: SpecEvidence) -> None:
        satisfied = await self.specifier.satisfied(self.spec, ev)
        rev = await self.specifier.revise(self.spec, ev)
        if satisfied:
            rev = rev.model_copy(update={
                "status_changes": {**rev.status_changes,
                                   **{oid: ObjectiveStatus.SATISFIED for oid in satisfied}}})
        if not rev.is_empty:
            await self._publish(session, rev)

    async def _publish(self, session: CampaignSession, rev: SpecRevision | None) -> None:
        """Hand the Spec, or one revision of it, to its only writer.

        `rev is None` means "this is the initial Spec". The executor applies; nothing here
        mutates campaign state, which is what keeps the single-writer discipline intact across
        a boundary that becomes a process boundary in phase 7.
        """
        payload = self.spec if rev is None else rev
        # `publish_spec` is a core-protocol operation as of phase 3, so it crosses a socket
        # with everything else and the injected fallback is only for a session that predates
        # it. Phase 7 drops the fallback.
        if hasattr(session, "publish_spec"):
            await session.publish_spec(payload)
        elif self.publish is not None:
            self.publish(payload)

    # -- Planner overflow (scaffolding) --------------------------------------
    async def _handle_overflow(self, session: CampaignSession, branched: bool) -> str | None:
        """Perform whichever non-planning action the wrapped legacy policy asked for."""
        p = self.planner
        if not isinstance(p, LegacyPlanner):
            await session.stop("planner produced no stage and no reason")
            return None
        if p.pending_stop is not None:
            reason, p.pending_stop = p.pending_stop, None
            await session.stop(reason)
            return None
        if p.pending_human is not None:
            question, context = p.pending_human
            p.pending_human = None
            await session.request_human(question, context)
            return None
        if p.pending_backtrack is not None:
            node_id, rationale = p.pending_backtrack
            p.pending_backtrack = None
            if branched:
                await session.stop(
                    "policy backtracked twice without running anything between")
                return None
            await session.backtrack(node_id, rationale)
            return "branched"
        await session.stop("planner produced no stage and no reason")
        return None

    # -- Deployer ------------------------------------------------------------
    async def _deploy(self, session: CampaignSession, stage: Stage,
                      ctx: PlanningContext, turn: int) -> str | None:
        """Submit one Stage, with bounded retry per experiment.

        Per experiment, not per cycle: that used to coincide because a cycle ran exactly one,
        and "per experiment" is what the rule always meant.
        """
        for _ in range(self.max_attempts):
            try:
                run_id = await session.submit_stage(stage)
            except SubmissionRejected as rejected:
                nxt = await self.planner.replan(stage, rejected.failure, self.spec, ctx)
                if nxt is None:
                    acted = await self._handle_overflow(session, True)
                    if acted is None:
                        return None
                    return None
                stage = nxt
                continue
            for task in stage.runs:
                self.data.expect(TaskFuture(
                    task_id=f"{run_id}/{task.task_id}", run_id=run_id, stage_id=stage.id,
                    objectives=list(task.objectives)))
            return run_id
        await session.stop(f"{self.max_attempts} attempts all rejected in cycle {turn}")
        return None


def goal_from_spec(spec: Any) -> Goal:
    """Build the caller's `Goal` from a `CampaignSpec`.

    The spec also carries how the campaign is *driven* - backend, concurrency, stagnation,
    cycle bounds - and none of that is the Goal. Keeping them apart is what makes
    `Goal -> Spec` a statement about the science rather than about the engine.
    """
    return Goal(text=spec.goal, objectives=list(spec.objectives),
                budget=dict(spec.budget))
