"""A fake ROME stream honouring `asteer.contracts.surrogate`, plus the ways one breaks.

**It satisfies the contract rather than imitating `rome.Stream`.** `SurrogateStream` is one
method wide, so the real stream, this fake and whatever item 9 writes in phase II all satisfy
it without inheriting from anything. The client cannot tell them apart, which is the only way
a test here says something about the real seam.

The failure classes get their own tiny types instead of flags, because each one is a distinct
thing a resident service does and the client collapses all of them to the same refusal. Naming
them separately is what makes the test read as four facts rather than one parametrised one.

What this is **not** is a substitute for driving ROME: `rome.Manager` with `DummyTrainer` and
`dummy_load`/`dummy_infer` runs the whole hot-swap loop on a laptop (measured 2026-11-19 —
`v0` through `v7`, the stream never restarted). That exercises the *reload*; this exercises the
*client*, which is a different question and the one EI.10 owns.
"""
from __future__ import annotations

from asteer.contracts.surrogate import SurrogateRequest, SurrogateResponse

__all__ = [
    "DownStream",
    "FakeStream",
    "ImpostorStream",
    "WrongShapeStream",
]


class FakeStream:
    """Answers with fixed values and sigmas, at a fixed version. Records what it was asked."""

    def __init__(self, model_id: str, values: dict[str, float],
                 sigmas: dict[str, float] | None = None, version: int = 3) -> None:
        self.model_id = model_id
        self.values = dict(values)
        self.sigmas = dict(sigmas or {})
        self.version = version
        #: Every request this stream saw, so a test can assert the client sent the node id and
        #: the campaign id rather than only that a number came back.
        self.seen: list[SurrogateRequest] = []

    def score(self, request: SurrogateRequest) -> SurrogateResponse:
        self.seen.append(request)
        return SurrogateResponse(
            request_id=request.request_id,
            model_id=self.model_id,
            version=self.version,
            values=dict(self.values),
            sigmas=dict(self.sigmas),
        )


class DownStream:
    """A stream that is bound and not answering: the outage the client must not paper over."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc or TimeoutError("no response in 30s")

    def score(self, request: SurrogateRequest) -> SurrogateResponse:
        raise self.exc


class WrongShapeStream:
    """A stream answering with something that is not a `SurrogateResponse`.

    The realistic cause is version skew across the seam — one side updated, the other not —
    which is exactly what importing one contract module is supposed to prevent and exactly
    what it cannot prevent across two deployed checkouts.
    """

    def score(self, request: SurrogateRequest) -> dict[str, object]:
        return {"values": {"dg_corrected": -9.1}, "version": 3}


class ImpostorStream:
    """A stream answering for a different model than the one that was asked.

    A misrouted binding, and the most dangerous of the four: the numbers are well-formed and
    attributed, just to the wrong weights. A score attributed to the wrong model supersedes
    nothing and trains the wrong corpus.
    """

    def __init__(self, answers_as: str) -> None:
        self.answers_as = answers_as

    def score(self, request: SurrogateRequest) -> SurrogateResponse:
        return SurrogateResponse(
            request_id=request.request_id,
            model_id=self.answers_as,
            version=1,
            values={"dg_corrected": -9.1},
        )
