"""The ControlPolicy contract.

One interface, four control models. This is what makes them interchangeable without
touching the manager, state, toolkit or execution layer.

Shape informed by radical.adr's `Policy`/`@decide`/`Decision` (Phase 3), widened where
ADR's flat action bag could not express what we need: a typed `Decision` union with
Backtrack/RequestHuman, an `interpret` hook, and a mandatory `on_rejected`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.decision import CampaignObservation, Decision, Stop, ValidationFailure
from ..core.results import RunOutcome


@runtime_checkable
class ControlPolicy(Protocol):
    """One question at a time. Still the auditable contract, still the default.

    A policy may instead implement `conduct(session)` and drive itself - see
    `policy.driver.SequentialPolicyDriver`, which turns this protocol into that one.
    `conduct` is deliberately NOT a member here: requiring it would break every existing
    policy, and `runtime_checkable` makes a Protocol's membership list load-bearing for
    anyone doing an isinstance check.
    """

    name: str

    async def decide(self, obs: CampaignObservation) -> Decision: ...

    async def interpret(self, results: RunOutcome,
                        obs: CampaignObservation) -> str | None: ...

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision: ...


class BasePolicy:
    """Convenience base. `interpret` defaults to None - deterministic metric extraction
    by task agents is the default, and a policy overrides only when interpretation is
    itself a judgement call."""

    name = "base"

    async def decide(self, obs: CampaignObservation) -> Decision:
        raise NotImplementedError

    async def interpret(self, results: RunOutcome,
                        obs: CampaignObservation) -> str | None:
        return None

    async def on_rejected(self, decision: Decision,
                          failure: ValidationFailure) -> Decision:
        """Default: give up rather than loop. Real policies should do better."""
        return Stop(reason=f"rejected at {failure.gate} gate: {failure.reason}")
