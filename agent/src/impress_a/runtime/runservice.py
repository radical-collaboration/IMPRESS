"""Runs addressed by id, durable across the process that created them.

This is the seam that lets the reasoner leave. Everything a caller needs to drive a
campaign is expressed here as an operation on a run id: submit one, list them, ask what
one produced, cancel one, and - after a restart - find out which ones were left in the
air. None of it requires sharing memory with the executor, which is what makes an
out-of-process reasoner an adapter rather than a rewrite.

**Placed in `runtime`, not `exec`.** The plan filed it under `exec/`, but admission needs
the composer, the validator and the interlock, and `exec -> compose` is a direction the
import contract forbids (ADR 0010). Durable persistence - the part that genuinely belongs
to the execution layer - stays in `exec/ledger.py`.

**Admission is synchronous.** `submit` either returns a run id or raises
`SubmissionRejected`, in the same call. The alternative - accept everything, report
rejections later on the event stream - would break the one rule that makes free
composition affordable: a policy is told why its experiment was refused and gets another
attempt. With no turn structure there is nothing to bound those attempts against. It also
could not work anyway: the dry-run instantiates task agents, so admission has to happen
where the toolkit is installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.decision import ExperimentIntent
from ..core.results import RunOutcome, RunState, RunStatus
from .executor import CampaignExecutor


@dataclass
class Reattachment:
    """What a restart found waiting for it."""

    campaign_id: str
    policy: str | None = None
    expected_policy: str | None = None
    orphaned: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)

    @property
    def policy_matches(self) -> bool:
        """Whether the campaign is being resumed under the methodology it started with.

        ADR 0005 fixes the control model at launch so a result is attributable to one
        stated methodology. That was self-enforcing while a campaign lived and died
        inside a single process. Once a reasoner can reattach, nothing stops it
        reattaching as a different policy, and the ADR becomes a comment unless somebody
        checks - so this is that check.
        """
        return (self.policy is None or self.expected_policy is None
                or self.policy == self.expected_policy)


class RunService:
    """The addressable surface over a campaign's runs."""

    def __init__(self, executor: CampaignExecutor):
        self._ex = executor

    # -- submitting ----------------------------------------------------------
    async def submit(self, intent: ExperimentIntent) -> str:
        """Admit and dispatch. Returns a run id, or raises `SubmissionRejected`."""
        return await self._ex.submit(intent)

    # -- asking --------------------------------------------------------------
    def list_runs(self, state: RunState | None = None) -> list[RunStatus]:
        runs = [self._ex.status(rid) for rid in self._ex._runs]
        return [r for r in runs if state is None or r.state is state]

    async def result(self, run_id: str) -> RunOutcome:
        return await self._ex.result(run_id)

    def outcome(self, run_id: str) -> RunOutcome | None:
        """A finished run's result, from memory or from the log.

        Falling back to the ledger is what makes this answerable after a restart, when
        the run happened in a process that no longer exists.
        """
        if (known := self._ex._outcomes.get(run_id)) is not None:
            return known
        return self._ex.jobs.outcome(run_id)

    def cancel(self, run_id: str) -> None:
        self._ex.cancel(run_id)

    # -- restarting ----------------------------------------------------------
    def reattach(self, expected_policy: str | None = None) -> Reattachment:
        """Reconcile against whatever a previous process left behind.

        The job ledger has existed since the first prototype and was never read. Nothing
        consumed `open_jobs()`, so a crash simply lost track of work that may still have
        been running - and on HPC that work holds an allocation whether or not anyone
        remembers submitting it.
        """
        ledger = self._ex.jobs
        snapshot = ledger.snapshot()
        started = [e for e in ledger.entries()
                   if e.get("event") == "campaign_started"]
        return Reattachment(
            campaign_id=self._ex.spec.campaign_id,
            policy=started[-1].get("policy") if started else None,
            expected_policy=expected_policy,
            orphaned=sorted(j["job_id"] for j in ledger.open_jobs()),
            completed=sorted(rid for rid, rec in snapshot.items()
                             if rec.get("outcome")))
