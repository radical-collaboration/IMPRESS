"""Multi-dimensional budget ledger.

Several independent dimensions, any of which can terminate a campaign. Cost is also a
declared objective, so the policy is pushed toward cheap experiments rather than merely
stopped at the wall.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetLedger(BaseModel):
    limits: dict[str, float] = Field(default_factory=dict)
    spent: dict[str, float] = Field(default_factory=dict)

    def remaining(self, dim: str) -> float:
        if dim not in self.limits:
            return float("inf")
        return self.limits[dim] - self.spent.get(dim, 0.0)

    def would_exceed(self, cost: dict[str, float]) -> list[str]:
        """Return the dimensions this cost would blow. Empty list = affordable."""
        return [d for d, c in cost.items() if c > self.remaining(d)]

    def charge(self, cost: dict[str, float]) -> None:
        for d, c in cost.items():
            self.spent[d] = self.spent.get(d, 0.0) + c

    def exhausted(self) -> list[str]:
        return [d for d in self.limits if self.remaining(d) <= 0]

    def fraction_used(self, dim: str) -> float:
        lim = self.limits.get(dim)
        if not lim:
            return 0.0
        return self.spent.get(dim, 0.0) / lim
