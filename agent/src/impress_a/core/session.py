"""The handle a reasoner holds on a running campaign.

The loop used to call the reasoner: `decide()` was invoked once per cycle, between
graphs, and could not be reached again until the work it asked for had finished. This
inverts that. The reasoner runs on its own and calls the campaign - submitting as many
experiments as it wants, then collecting them in whatever order it likes.

Two properties are deliberate and load-bearing:

* **It lives in `core`.** A policy may not import `tools` or `exec` (ADR 0010), so
  anything a reasoner touches has to be typed here or the seam rots.
* **It is request/response, and nothing live crosses it.** Every argument and every
  return value is serializable. An in-process reasoner does not need that; a reasoner on
  a login node talking to an executor inside a batch allocation does, and designing the
  surface any other way would quietly rule that out.

Note what is NOT here. There is no `Await` or `Cancel` member of the `Decision` union:
waiting is something the reasoner does by calling `result` or `as_completed`, not
something it asks the loop to do on its behalf. One control-flow vocabulary, not two.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from .decision import CampaignObservation, ExperimentIntent, ValidationFailure
from .results import RunOutcome, RunStatus

RunId = str


class SubmissionRejected(Exception):
    """An experiment did not pass admission.

    Raised by `submit`, synchronously with the request, so a reasoner learns why in the
    same breath as it asks - which is what keeps the bounded-retry contract intact now
    that dispatch no longer happens there. `failure.transient` distinguishes "this graph
    is wrong" from "the resources are busy right now"; answering the second by shrinking
    the experiment is how a policy accidentally degrades itself.
    """

    def __init__(self, failure: ValidationFailure):
        self.failure = failure
        super().__init__(f"rejected at {failure.gate} gate: {failure.reason}")


class CampaignStopped(Exception):
    """The campaign ended while the reasoner was waiting on something.

    Raised into every outstanding `result`/`as_completed` call rather than leaving them
    pending. A terminating executor that simply stops answering deadlocks its reasoner.
    """


@runtime_checkable
class CampaignSession(Protocol):
    """What a reasoner may do. The control plane exposes the same operations."""

    async def observe(self, since: int | None = None) -> CampaignObservation:
        """The same observation a policy's `decide` receives (ADR 0007)."""
        ...

    async def submit(self, intent: ExperimentIntent) -> RunId:
        """Admit and dispatch one experiment. Raises `SubmissionRejected`."""
        ...

    async def status(self, run_id: RunId) -> RunStatus: ...

    async def result(self, run_id: RunId) -> RunOutcome:
        """Wait for one run. Raises `CampaignStopped` if the campaign ends first."""
        ...

    def as_completed(self, run_ids: list[RunId] | None = None
                     ) -> AsyncIterator[RunOutcome]:
        """Yield runs as they finish, soonest first - not in submission order."""
        ...

    async def inflight(self) -> list[RunStatus]: ...

    async def cancel(self, run_id: RunId) -> None:
        """Advisory. Reclaims queued work; running work finishes regardless."""
        ...

    async def backtrack(self, node_id: str, rationale: str = "") -> str:
        """Branch a new lineage from an earlier node. Returns the new node id."""
        ...

    async def request_human(self, question: str,
                            context: dict[str, Any] | None = None) -> None: ...

    async def stop(self, reason: str) -> None:
        """Ask the campaign to end. The executor decides when it actually has."""
        ...
