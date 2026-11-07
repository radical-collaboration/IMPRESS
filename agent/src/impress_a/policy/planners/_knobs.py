"""What a tool's parameters are *for*, read from the one sentence a spec gives about each.

`ParamCard.trades` is the only prose a reasoner gets - "quality vs wall-clock", "coverage vs
GPU-hours", "diversity vs recovery" - and `core/toolkit.py` carries it for exactly this. Read
across every shipped tool the vocabulary is small and consistent, and it sorts the parameters
into four kinds that a planner must treat differently:

| kind | example | what raising it does | may a planner raise it? |
|---|---|---|---|
| **quality** | `diffusion_steps`, `recycles` | the same draw, harder | yes: the refinement axis |
| **diversity** | `temperature` | a different draw, same cost | yes, and nearly free |
| **breadth** | `num_designs`, `batch_size`, `nstruct` | more draws, more cost | **no** |
| **identity** | `seed` | a different lineage | **no** |

Breadth is excluded on evidence, not taste. `rfd3_design`'s own spec records that `num_designs`
stays at 1 because its adapter still keeps index 0, so raising it pays N times for one design;
the tools whose adapters DO select from their ensemble already carry 8 as their declared
default, set deliberately in phase 8 and re-derived against the cost models. A planner's job is
not to re-litigate that per cycle. Identity is excluded because moving `seed` would break the
independence of the replica lineages the arm is being credited for.

A sentence naming two kinds - "sampling vs quality" - is **ambiguous and therefore refused**. A
planner resolving an ambiguity in a spec by guessing is how a GPU bill doubles.

Shared between the planner halves on purpose: which parameter means what is a property of the
Toolkit, not of a control model, and two readings of one `trades` sentence would be two things
to keep in step. What differs between arms is which kind they move and how far, which is the
decision; this is the vocabulary the decision is expressed in.
"""
from __future__ import annotations

import math
from typing import Any

from ...core.toolkit import ParamCard

QUALITY_TERMS = ("quality", "accuracy", "convergence")
DIVERSITY_TERMS = ("diversity",)
BREADTH_TERMS = ("coverage", "sampling", "samples", "candidates", "passes", "batch")
IDENTITY_TERMS = ("draw", "seed", "lineage")

#: kind -> the words that name it. Ordered, but every kind is checked: a sentence matching two
#: is ambiguous and gets no answer at all.
_KINDS = (("quality", QUALITY_TERMS), ("diversity", DIVERSITY_TERMS),
          ("breadth", BREADTH_TERMS), ("identity", IDENTITY_TERMS))


def kind_of(param: ParamCard) -> str | None:
    """`"quality" | "diversity" | "breadth" | "identity"`, or None if the spec does not say.

    None for a parameter with no `trades` sentence, and None for one whose sentence names two
    kinds. Both mean "this planner has nothing to say about it", which leaves the declared
    default - or the campaign's own `params` - in force, and that is the safe answer.
    """
    trades = (param.trades or "").lower()
    hits = [name for name, terms in _KINDS if any(term in trades for term in terms)]
    return hits[0] if len(hits) == 1 else None


def tunable(param: ParamCard, frozen: dict[str, str], name: str) -> bool:
    """Whether a planner may propose a value for this parameter at all.

    A frozen parameter is one the composer may not propose and gate 3 refuses, so proposing
    one turns every Stage into a rejection. A parameter with no declared bounds has no range to
    move within, and one with no default has nothing to move from.
    """
    return (name not in frozen and param.type in ("int", "float")
            and param.min is not None and param.max is not None
            and param.default is not None)


def at_fraction(param: ParamCard, fraction: float) -> Any:
    """The value `fraction` of the way from the declared minimum to the declared maximum.

    Expressed against the full declared range rather than as a multiple of the default,
    because the default is where a *campaign* starts and the range is what the *tool* says it
    supports - and a multiple of a default of 1 cannot express "a little" at all.

    `None` when the result would not move the value, so a planner never emits a parameter it
    is not actually changing: an unchanged value in a Stage reads as a decision that was made.
    """
    lo, hi = float(param.min), float(param.max)
    value = lo + (hi - lo) * max(0.0, min(1.0, fraction))
    if param.type == "int":
        value = int(min(hi, max(lo, math.floor(value + 0.5))))
        return value if value != int(float(param.default)) else None
    value = round(value, 6)
    return value if value != float(param.default) else None


def step_up(param: ParamCard, steps: int, of: int) -> Any:
    """`steps` of `of` steps from the default toward the declared maximum.

    The declared max is a limit, not a target: arriving there on the first refinement leaves
    nothing left to escalate and no record of which step helped. `None` once there is no
    headroom left to use, or when the step is too small to change an integer.
    """
    base = float(param.default)
    headroom = float(param.max) - base
    if headroom <= 0 or steps <= 0:
        return None
    value = min(float(param.max), base + headroom * (steps / max(1, of)))
    if param.type == "int":
        out = int(min(float(param.max), math.ceil(value)))
        return out if out > int(base) else None
    out = round(value, 6)
    return out if out > base else None


__all__ = ["BREADTH_TERMS", "DIVERSITY_TERMS", "IDENTITY_TERMS", "QUALITY_TERMS",
           "at_fraction", "kind_of", "step_up", "tunable"]
