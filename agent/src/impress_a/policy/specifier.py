"""The Specifier contract: `Goal -> Spec`, and `Spec -> Spec` at runtime.

One half of what used to be a single `decide(obs) -> Decision`. The split is not cosmetic: a
campaign had no representation of what it was trying to achieve, so "what should exist" and
"which tool makes it" were the same decision, made at the same moment, by the same rule. They
are different questions - one is about the science, the other about the Toolkit - and a
four-arm comparison that cannot tell them apart cannot say which half earns a model its cost.

Three rules this file encodes:

**A Specifier authors; it does not write.** `revise` returns a `SpecRevision`. The executor
applies it, in an `await`-free block, and is the only writer - so `specs` provenance is written
by the executor rather than by a reasoner, which is the structural reason an arm's own
bookkeeping is never the thing it is scored on.

**A generated objective is still a declaration against a property name.** Decision 0012 binds
objectives to names, never to sources, so that a measurement arriving months later supersedes
against the same name. `SpecObjective.targets` holds names; nothing here may invent a source.

**It may import `core` only.** Asserted by `tests/test_layering.py`. A Specifier that could
reach `tools` would stop emitting abstract intent and start naming adapters, and the control
models would stop being swappable - which is the whole point of having four of them. What a
Specifier is allowed to know about the Toolkit arrives as a `ToolkitView`, a `core` projection,
in phase 2.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..core.data import DataRegistry
from ..core.decision import CampaignObservation
from ..core.goal import Goal
from ..core.spec import Spec, SpecRevision


class SpecEvidence:
    """Everything a Specifier may look at, and nothing it may change.

    `observation` **is** the object `CampaignSession.observe()` returns - not a summary of it.
    ADR 0007 requires that an external caller and an in-process reasoner see the same evidence;
    extending that to a second consumer means passing the same type through, not minting a
    parallel one that drifts.
    """

    __slots__ = ("observation", "data")

    def __init__(self, observation: CampaignObservation, data: DataRegistry) -> None:
        self.observation = observation
        self.data = data

    @property
    def cycle(self) -> int:
        return self.observation.cycle

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (f"SpecEvidence(cycle={self.cycle}, realized={len(self.data.realized)}, "
                f"pending={len(self.data.pending())})")


@runtime_checkable
class Specifier(Protocol):
    """Goal in, Spec out; then revisions as data arrives."""

    name: str

    async def initial_spec(self, goal: Goal) -> Spec:
        """The first Spec. Called once, before anything is planned."""
        ...

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        """What to add, delete or re-status now. An empty revision is a valid answer.

        Called when the Listener signals that data has arrived. Returning
        `SpecRevision()` - empty - says "nothing has changed my mind", which must stay cheap:
        it is the common case.
        """
        ...

    async def satisfied(self, spec: Spec, ev: SpecEvidence) -> list[str]:
        """Objective ids whose satisfaction rules now hold.

        Separate from `revise` because satisfaction is a *finding*, not a decision: the
        default implementation reads the rules against realized data and the Specifier does
        not get a say. Overriding it is for a Specifier whose notion of "done" is richer than
        a rule - and then it owes an explanation in provenance, because the campaign's stop
        condition is being argued rather than computed.
        """
        ...


class BaseSpecifier:
    """Convenience base: the computed `satisfied`, and a `revise` that changes nothing.

    A subclass that only implements `initial_spec` is a complete, usable Specifier whose Spec
    is fixed for the campaign. That is deliberately the easy case.
    """

    name = "base"

    async def initial_spec(self, goal: Goal) -> Spec:
        raise NotImplementedError

    async def revise(self, spec: Spec, ev: SpecEvidence) -> SpecRevision:
        return SpecRevision()

    async def satisfied(self, spec: Spec, ev: SpecEvidence) -> list[str]:
        """Rule-driven and deterministic: ask the registry, not the model."""
        out = []
        for obj in spec.open_objectives():
            if ev.data.satisfies(obj.satisfied_when):
                out.append(obj.id)
        return out
