"""Scoring and validation that runs beside a campaign rather than inside one.

In `src/` rather than `scripts/` because CI runs `pytest tests -q` and nothing else: a harness
that is not importable is a harness that is not tested, and the figures a comparison publishes
are exactly the code that must not be wrong.

**This layer may not import `policy` or `control`**, which is the one rule that matters here and
is asserted by `tests/test_layering.py`. A scorer that could reach a reasoner could score a
campaign by asking it, and the whole method rests on scoring from provenance, the ledgers and
the artifacts on disk - never from an arm's own bookkeeping.
"""
