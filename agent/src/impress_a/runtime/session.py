"""The in-process `CampaignSession`.

A thin translation from the session surface onto the executor. It deliberately adds
nothing: every operation here exists in `core.session.CampaignSession`, and the control
plane exposes the same set. An adapter that grew an extra operation would fork the
semantics between consumers, which is the whole reason the protocol is defined once.

This one shares an event loop with the executor, so it could reach in and touch campaign
state directly. It does not. Keeping it to request/response is what lets the same reasoner
run unchanged against an executor in another process.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..core.decision import CampaignObservation, ExperimentIntent
from ..core.results import RunOutcome, RunStatus
from ..core.session import CampaignStopped
from .executor import CampaignExecutor


class InProcessSession:
    def __init__(self, executor: CampaignExecutor):
        self._ex = executor

    async def observe(self, since: int | None = None) -> CampaignObservation:
        return self._ex.observe(self._ex.last_rejection, since=since)

    async def submit(self, intent: ExperimentIntent) -> str:
        return await self._ex.submit(intent)

    async def status(self, run_id: str) -> RunStatus:
        return self._ex.status(run_id)

    async def result(self, run_id: str) -> RunOutcome:
        return await self._ex.result(run_id)

    async def inflight(self) -> list[RunStatus]:
        return self._ex.inflight()

    async def as_completed(self, run_ids: list[str] | None = None
                           ) -> AsyncIterator[RunOutcome]:
        """Yield runs as they finish, soonest first.

        With `run_ids`, stops once those have all been delivered; without, runs until the
        campaign ends. Outcomes for runs already finished are delivered immediately, so
        waiting is never missed by a race between submitting and iterating.
        """
        wanted = set(run_ids) if run_ids is not None else None
        if wanted:
            for rid in list(wanted):
                if (done := self._ex._outcomes.get(rid)) is not None:
                    wanted.discard(rid)
                    yield done
        while wanted is None or wanted:
            if self._ex.stopped and not self._ex._inflight:
                if wanted:
                    raise CampaignStopped(self._ex.stop_reason)
                return
            outcome = await self._ex.next_completed()
            if outcome is None:                    # campaign ended while waiting
                if wanted:
                    raise CampaignStopped(self._ex.stop_reason)
                return
            if wanted is None or outcome.run_id in wanted:
                if wanted is not None:
                    wanted.discard(outcome.run_id)
                yield outcome

    async def cancel(self, run_id: str) -> None:
        self._ex.cancel(run_id)

    async def backtrack(self, node_id: str, rationale: str = "") -> str:
        return self._ex.backtrack(node_id, rationale)

    async def request_human(self, question: str,
                            context: dict[str, Any] | None = None) -> None:
        self._ex.request_human(question, context)

    async def stop(self, reason: str) -> None:
        self._ex.request_stop(reason)
