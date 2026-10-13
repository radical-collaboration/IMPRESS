"""`CampaignSession`, implemented over the control plane instead of over memory.

`core/session.py` describes the handle a reasoner holds on a running campaign, and says
in its own docstring what it is for: "a reasoner on a login node talking to an executor
inside a batch allocation". Everything the surface needed for that was already true -
every argument and every return value is serializable - but nothing implemented it. A
`ControlPlaneClient` spoke the plane's vocabulary, not the session's, so a driver or a
policy pointed at it had to poll, and `SequentialPolicyDriver` could not be pointed at it
at all. This is the class that closes that gap.

The point is NOT that a remote reasoner becomes possible. It is that the reasoner does
not change. `SequentialPolicyDriver` driving an unmodified `ThresholdPolicy` runs against
this exactly as it runs against `runtime.session.InProcessSession`, because the two
implement the same protocol and nothing above them can tell which one it holds.

Two mechanisms from the in-process side had to be given a wire equivalent, and neither is
a new idea - each is the same idea with a socket in the middle:

* **`result()` races the run against the campaign ending.** In-process that is
  `CampaignExecutor.result`, which waits on the run's future and the halt event together
  and raises `CampaignStopped` if the halt wins. Here it is a long poll: the server does
  that same race with a deadline on it, and answers with the outcome, with "the campaign
  has ended", or with "nothing yet - ask again". The deadline is the transport's problem;
  re-issuing is this class's; the reasoner just blocks in `result()`.

* **`as_completed()` consumes a queue.** In-process that is `_completed`, an in-memory
  `asyncio.Queue` which by construction cannot be seen from another process. Its wire
  equivalent is the event stream that already existed: the executor mirrors each
  resolution onto provenance as it happens, so subscribing to `/events` yields the same
  sequence of completions, in the order they FINISHED, with the campaign's end arriving
  as one more record rather than as a sentinel nobody can read.

Imports `core` only, like anything a reasoner touches (ADR 0010). The client is taken
duck-typed rather than imported so that this module loads without the `http` extra, and
so that a future MCP client serves as well as the HTTP one - the transport is the part
that is supposed to be replaceable.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..core.decision import CampaignObservation, ExperimentIntent, ValidationFailure
from ..core.results import RunOutcome, RunStatus
from ..core.session import CampaignStopped, SubmissionRejected


class RemoteSession:
    """A `CampaignSession` whose executor is at the other end of a control plane.

    `client` is any `CampaignControlPlane` - `control.http.ControlPlaneClient` in
    practice, but `control.plane.InProcessControlPlane` works too, which is the cheapest
    way to check that nothing here depends on the transport.
    """

    def __init__(self, client: Any, campaign_id: str, *, wait_s: float = 30.0,
                 event_timeout_s: float = 5.0):
        self._client = client
        self._cid = campaign_id
        #: How long one long poll may block before the transport makes us ask again.
        self._wait_s = wait_s
        #: How long an idle event subscription is held open before it is renewed.
        self._event_timeout_s = event_timeout_s
        # Cursor and delivery set stand in for the in-memory completion queue: a run is
        # handed to this session once, and a later `as_completed` resumes where the
        # previous one stopped instead of replaying the campaign from the beginning.
        self._cursor = 0
        self._delivered: set[str] = set()
        self._ended = False
        self._stop_reason = "campaign ended"

    # -- observe --------------------------------------------------------------
    async def observe(self, since: int | None = None) -> CampaignObservation:
        return await self._client.observe(self._cid, since)

    # -- submit ---------------------------------------------------------------
    async def submit(self, intent: ExperimentIntent) -> str:
        """Admission stays SYNCHRONOUS across the wire.

        The far side composes, runs the five gates and the dry-run, and answers in this
        call - accepted with an id, or refused with the gate and the reason. It has to
        happen there rather than here: the dry-run instantiates task agents, so admission
        only has an answer where the toolkit is installed. Deferring the refusal to the
        event stream would sever it from the request that caused it and leave the bounded
        retry with nothing to bound.
        """
        answer = await self._client.submit_run(self._cid,
                                               intent.model_dump(mode="json"))
        if answer.get("accepted"):
            return answer["run_id"]
        if (failure := answer.get("failure")) is not None:
            raise SubmissionRejected(ValidationFailure(**failure))
        # Refused without a gate: the campaign ended between the ask and the answer.
        raise CampaignStopped(answer.get("reason", "campaign has ended"))

    # -- collect --------------------------------------------------------------
    async def status(self, run_id: str) -> RunStatus:
        return await self._client.status(self._cid, run_id)

    async def inflight(self) -> list[RunStatus]:
        return await self._client.inflight(self._cid)

    async def result(self, run_id: str) -> RunOutcome:
        """Wait for one run. Raises `CampaignStopped` if the campaign ends first.

        The loop is the long poll's, not a poll of the run: each request blocks on the
        far side until there is something to say, and only comes back empty because a
        connection cannot be held open for the length of a folding job. A caller sees one
        blocking call either way.
        """
        while True:
            answer = await self._client.await_run_result(self._cid, run_id,
                                                         self._wait_s)
            state = answer.get("state")
            if state == "ready":
                return RunOutcome(**answer["outcome"])
            if state == "stopped":
                self._ended = True
                self._stop_reason = answer.get("reason", self._stop_reason)
                raise CampaignStopped(self._stop_reason)
            if state == "unknown":
                raise KeyError(f"unknown run {run_id}")
            # "pending": the deadline expired, not the run. Ask again.

    async def as_completed(self, run_ids: list[str] | None = None
                           ) -> AsyncIterator[RunOutcome]:
        """Yield runs as they finish, soonest first - matching `InProcessSession`.

        With `run_ids`, stops once those have all been delivered; without, runs until the
        campaign ends. Outcomes for runs that have ALREADY finished are fetched directly
        before the stream is joined, so a race between submitting and iterating cannot
        lose one - the same guarantee the in-process version gets from draining its queue
        of anything already sitting in it.

        The campaign ending arrives as a record on the same stream rather than as a
        sentinel on a queue, which is the only structural difference: if runs are still
        wanted when it lands, this raises `CampaignStopped` rather than leaving the
        caller waiting on results that are never coming.
        """
        wanted = set(run_ids) if run_ids is not None else None
        if wanted:
            for rid in sorted(wanted):
                body = await self._client.run_result(self._cid, rid)
                if body is not None:
                    wanted.discard(rid)
                    self._delivered.add(rid)
                    yield RunOutcome(**body)

        while wanted is None or wanted:
            if self._ended:
                if wanted:
                    raise CampaignStopped(self._stop_reason)
                return
            stream = self._client.events(self._cid, since=self._cursor, stream=True,
                                         timeout=self._event_timeout_s)
            try:
                async for event in stream:
                    self._cursor = int(event.get("seq", self._cursor - 1)) + 1
                    if self._is_end(event):
                        self._ended = True
                        self._stop_reason = event.get("reason") or self._stop_reason
                        break
                    rid = self._finished_run(event)
                    if rid is None or rid in self._delivered:
                        continue
                    if wanted is not None and rid not in wanted:
                        continue
                    # Blocking, not a peek: a run is announced as it is folded into
                    # campaign state, an instant before its outcome is published, and a
                    # bare read would miss it by that instant.
                    outcome = await self.result(rid)
                    self._delivered.add(rid)
                    if wanted is not None:
                        wanted.discard(rid)
                    yield outcome
                    if wanted is not None and not wanted:
                        return
            finally:
                await stream.aclose()
        # Everything asked for has been delivered.

    @staticmethod
    def _is_end(event: dict[str, Any]) -> bool:
        """The wire form of `_completed.put_nowait(None)`.

        `campaign_ended` is written once drain has resolved everything still in flight,
        so it is genuinely "nothing further will arrive". `terminated` is accepted too
        because it is the record a campaign has always written on its way out.
        """
        return (event.get("kind") == "transitions"
                and event.get("event") in ("campaign_ended", "terminated"))

    @staticmethod
    def _finished_run(event: dict[str, Any]) -> str | None:
        run = event.get("run")
        return run if event.get("kind") == "executions" and run else None

    # -- steer ----------------------------------------------------------------
    async def cancel(self, run_id: str) -> None:
        """Advisory, and no less advisory for having crossed a socket: queued work is
        reclaimed, running work is not, and the backend does not report which."""
        await self._client.cancel_run(self._cid, run_id)

    async def backtrack(self, node_id: str, rationale: str = "") -> str:
        return await self._client.backtrack(self._cid, node_id, rationale)

    async def request_human(self, question: str,
                            context: dict[str, Any] | None = None) -> None:
        await self._client.request_human(self._cid, question, context)

    async def stop(self, reason: str) -> None:
        """Ask the campaign to end. The executor still decides when it actually has."""
        await self._client.stop(self._cid, reason)
