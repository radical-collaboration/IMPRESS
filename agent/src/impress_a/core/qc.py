"""QC reports as first-class campaign state.

Part A's dominant finding was that the toolkit fails *silently*. A node whose QC verdict
is FAIL is never eligible for the Pareto front, whatever its scores - that coupling is
the main structural consequence of Part A (Part B doc 03).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GateOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_RUN = "not_run"


class GateResult(BaseModel):
    gate: str
    outcome: GateOutcome
    observed: Any = None
    threshold: Any = None
    detail: str = ""


class QCVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SUSPECT = "suspect"  # surfaced to the policy, never silently promoted


class QCReport(BaseModel):
    gates: list[GateResult] = Field(default_factory=list)
    verdict: QCVerdict = QCVerdict.PASS
    notes: list[str] = Field(default_factory=list)

    @property
    def eligible_for_front(self) -> bool:
        """FAIL is never rankable. SUSPECT is rankable but carries its flag."""
        return self.verdict is not QCVerdict.FAIL

    def add(self, r: GateResult) -> "QCReport":
        self.gates.append(r)
        if r.outcome is GateOutcome.FAIL:
            self.verdict = QCVerdict.FAIL
        return self

    def mark_suspect(self, why: str) -> "QCReport":
        if self.verdict is not QCVerdict.FAIL:
            self.verdict = QCVerdict.SUSPECT
        self.notes.append(why)
        return self
