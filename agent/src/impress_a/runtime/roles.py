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

Both pieces of phase 1's scaffolding are gone (phase 11). `_intent_for` rendered a Stage back
into an `ExperimentIntent` because the executor had no other submit path; `submit_stage` is that
path now. And the `LegacyPlanner` overflow attributes carried the three non-planning members of
the old `Decision` union - Stop, Backtrack, RequestHuman - which have no equivalent here because
in this design they are not decisions a planner makes: stopping is the Listener's request and the
executor's call, and branching from an earlier node is a `SpecObjective.parent_node`.

So a Planner that returns no Stage has exactly one meaning, and `conduct` acts on it directly:
there is nothing left to plan. A Specifier that wants the campaign to end says so by leaving no
objective open, which makes `Spec.complete()` true - the designed path, with no special case.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.data import DataRegistry, TaskFuture
from ..core.goal import Goal
from ..core.session import CampaignSession, CampaignStopped, SubmissionRejected
from ..core.spec import ObjectiveStatus, Spec, SpecRevision, Stage
from ..policy.planner import PlanningContext
from ..policy.specifier import SpecEvidence

log = logging.getLogger(__name__)


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
                    # One meaning, and the Planner contract says it: "I have nothing to plan."
                    # The old union had three other ways to answer - Stop, Backtrack,
                    # RequestHuman - and none of them is a planning decision in this design:
                    # stopping is the executor's call on the Listener's request, and branching
                    # from an earlier node is a `SpecObjective.parent_node`.
                    return await session.stop(
                        f"{getattr(self.planner, 'name', 'planner')} planned nothing at "
                        f"cycle {turn}")

                run_id = await self._deploy(session, stage, ctx, turn)
                if run_id is None:
                    return
                turn += 1
                outstanding.append(run_id)

                # Hold at most `concurrency` experiments open. At the default of 1 this waits
                # for each before asking again, which is the serial cycle the deleted driver
                # held and which every parity test was written against.
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
        # No `after_collect` hook. The old `interpret` existed because a `decide` policy
        # accumulated state across runs and the executor had to tell it a result had landed;
        # the Listener owns ingestion now, which is `policy/driver.py`'s own ruling about who
        # collects an outcome, surviving the driver's deletion.

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
        """Hand the Spec, or one revision of it, to its only writer - and apply it here too.

        `rev is None` means "this is the initial Spec". The executor is the only writer of the
        APPLIED Spec, which is what the Reviewer's coverage gate reads; this driver keeps its
        own view of it, which is what `conduct` tests for completeness.

        **Both have to be updated, and that is not obvious in one process.** In-process the
        executor's `set_spec` stores the very object this driver holds, so a revision applied
        there mutated this one too - by aliasing, not by design. Across a socket the executor
        holds a deserialized copy, the local view never changed, `spec.complete()` was never
        true, and a campaign whose objectives were all satisfied ran on to its cycle limit.
        The in-process path passed for the wrong reason until the split exposed it.

        The returned generation is compared rather than ignored: two views of the Spec that
        disagree about how many revisions have been applied is the shape of that same bug
        coming back.
        """
        payload = self.spec if rev is None else rev
        if rev is not None:
            self.spec.apply(rev)
        applied = None
        if hasattr(session, "publish_spec"):
            applied = await session.publish_spec(payload)
        elif self.publish is not None:
            applied = self.publish(payload)
        if applied is not None and applied != self.spec.generation:
            log.warning(
                "spec generation diverged: the executor applied %s, this driver holds %s - "
                "the two views of the Spec are no longer the same revision",
                applied, self.spec.generation)

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
                    # `None` from `replan` means "I have no better Stage", which ends the
                    # campaign with the gate that refused it named - rather than with
                    # "planned nothing", which would say the planner never tried.
                    await session.stop(
                        f"rejected at {rejected.failure.gate}: {rejected.failure.reason}")
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
