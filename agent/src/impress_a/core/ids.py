"""Process-scoped identity.

A bare `itertools.count` is unique only within one interpreter: two workers both emit
`g000001`, and a durable run record that outlives the process that wrote it cannot tell
them apart afterwards. Every generated id therefore carries a short per-process token.

The sequence stays leading so ids still sort by creation order within a process, which is
what makes a provenance log readable.
"""
from __future__ import annotations

import itertools
import uuid
from typing import Callable

#: Distinguishes ids minted by this interpreter from any other's. Regenerated per process
#: on purpose - it is an identity, not a seed, and must never be made reproducible.
PROCESS_TOKEN: str = uuid.uuid4().hex[:4]


def counter(prefix: str) -> Callable[[], str]:
    """Return a generator of process-unique ids: `<prefix><seq:06d>-<token>`."""
    seq = itertools.count(1)

    def _next() -> str:
        return f"{prefix}{next(seq):06d}-{PROCESS_TOKEN}"

    return _next
