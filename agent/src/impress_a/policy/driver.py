"""Runs a `decide`-style policy as a reasoner.

Control models A, B, C and D answer one question at a time: "given this observation, what
next?" That contract is not obsolete - it is the auditable one, and it is what makes a
campaign's methodology attributable. This driver keeps it working unchanged by playing the
part the manager's loop used to play: observe, ask, submit, wait, repeat.

So `conduct` is an ADDITIONAL entry point, not a replacement. A policy that wants to hold
twelve experiments open implements `conduct`; a policy that wants to be asked one question
at a time implements `decide` and is driven by this. Both reach the same executor through
the same session, and the bounded retry survives intact for the second kind.

Imports `core` only, like every policy (ADR 0010) - it never learns what is executing its
intents.
"""
from __future__ import annotations

from typing import Any

from ..core.decision import Backtrack, ComposeAndRun, RequestHuman, Stop
from ..core.session import CampaignSession, CampaignStopped, SubmissionRejected


class SequentialPolicyDriver:
    """Adapts `decide`/`on_rejected`/`interpret` onto `CampaignSession`."""

    def __init__(self, policy: Any, max_turns: int = 10, max_attempts: int = 4,
                 concurrency: int = 1):
        self.policy = policy
        self.max_turns = max_turns
        self.max_attempts = max_attempts
        self.concurrency = max(1, concurrency)
        self.name = getattr(policy, "name", "?")

    async def conduct(self, session: CampaignSession) -> None:
        outstanding: list[str] = []
        try:
            for turn in range(self.max_turns):
                obs = await session.observe()
                decision = await self.policy.decide(obs)

                if isinstance(decision, Stop):
                    return await session.stop(decision.reason)
                if isinstance(decision, RequestHuman):
                    return await session.request_human(decision.question,
                                                       decision.context)
                if isinstance(decision, Backtrack):
                    await session.backtrack(decision.node_id, decision.rationale)
                    continue

                assert isinstance(decision, ComposeAndRun)
                run_id = await self._submit_with_retry(session, decision, turn)
                if run_id is None:
                    return
                outstanding.append(run_id)

                # Hold at most `concurrency` experiments open. At the default of 1 this
                # waits for each experiment before asking the policy again, which is the
                # serial cycle this driver exists to preserve.
                while len(outstanding) >= self.concurrency:
                    await self._collect(session, outstanding.pop(0))
            await session.stop(f"max_cycles={self.max_turns} reached")
        except CampaignStopped:
            return          # the executor ended the campaign; it owns the reason

    async def _collect(self, session: CampaignSession, run_id: str) -> None:
        """Wait for one experiment, then let the policy read it.

        `interpret` belongs to whoever collects the outcome. It used to be called by the
        executor, on its own reference to the policy object - which worked only while the
        two shared a process. Drive a reasoner through a remote session and the executor's
        policy is a placeholder, so the hook never fired and a policy that accumulates
        across runs silently stopped accumulating: `ThresholdPolicy._stalled` never
        advanced, so its stall-triggered `Backtrack` could never fire. Collecting is the
        reasoner's half of the seam, so the call lives here.

        The observation is taken AFTER the outcome lands, so `interpret` sees the campaign
        state the run produced rather than the state it started from.
        """
        outcome = await session.result(run_id)
        if hasattr(self.policy, "interpret"):
            await self.policy.interpret(outcome, await session.observe())

    async def _submit_with_retry(self, session: CampaignSession,
                                 decision: ComposeAndRun, turn: int) -> str | None:
        """Bounded retry, with the same semantics `on_rejected` always had.

        What changed is only its scope: it used to be "per cycle", which coincided with
        "per experiment" because a cycle ran exactly one. It is now per experiment, which
        is what that rule always meant.
        """
        for _ in range(self.max_attempts):
            try:
                return await session.submit(decision.intent)
            except SubmissionRejected as rejected:
                retry = await self.policy.on_rejected(decision, rejected.failure)
                if isinstance(retry, Stop):
                    await session.stop(retry.reason)
                    return None
                if not isinstance(retry, ComposeAndRun):
                    await session.stop(
                        "policy returned a non-runnable decision on rejection")
                    return None
                decision = retry
        await session.stop(
            f"{self.max_attempts} attempts all rejected in cycle {turn}")
        return None
