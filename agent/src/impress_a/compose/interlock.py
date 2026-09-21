"""The self-promoting interlock (decision 0003).

Novel compositions are never blocked and never trusted on sight. A pattern - the graph's
SHAPE, not its parameter values - earns trusted status mechanically by accumulating clean
runs, and loses it on any failure. The trust ledger is site-scoped and spans campaigns,
because one campaign may not run a pattern N times.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class PatternRecord(BaseModel):
    signature: str
    tools: list[str] = Field(default_factory=list)
    clean_runs: int = 0
    trusted: bool = False
    demotions: int = 0


class TrustLedger(BaseModel):
    """Append-only on disk; site-scoped, not campaign-scoped."""

    promote_after: int = 3
    provisional_budget_fraction: float = 0.10
    patterns: dict[str, PatternRecord] = Field(default_factory=dict)
    path: str | None = None

    @classmethod
    def load(cls, path: str | Path, **kw) -> "TrustLedger":
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            data.update(kw)
            return cls(**data, path=str(p))
        return cls(path=str(p), **kw)

    def save(self) -> None:
        if self.path:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.path).write_text(self.model_dump_json(indent=2, exclude={"path"}))

    def record_for(self, sig: str, tools: list[str]) -> PatternRecord:
        if sig not in self.patterns:
            self.patterns[sig] = PatternRecord(signature=sig, tools=sorted(set(tools)))
        return self.patterns[sig]

    def is_trusted(self, sig: str) -> bool:
        r = self.patterns.get(sig)
        return bool(r and r.trusted)

    def on_clean_run(self, sig: str) -> bool:
        """Returns True if this run promoted the pattern."""
        r = self.patterns.get(sig)
        if r is None or r.trusted:
            return False
        r.clean_runs += 1
        if r.clean_runs >= self.promote_after:
            r.trusted = True
            self.save()
            return True
        self.save()
        return False

    def on_failure(self, sig: str) -> bool:
        """Demotion is symmetric: trust decays on evidence. Returns True if demoted."""
        r = self.patterns.get(sig)
        if r is None:
            return False
        was = r.trusted
        r.trusted = False
        r.clean_runs = 0
        if was:
            r.demotions += 1
        self.save()
        return was


class Scrutiny(BaseModel):
    """Extra constraints applied to a provisional pattern."""

    trusted: bool
    cost_cap_fraction: float | None = None
    force_dry_run: bool = True
    mark_suspect: bool = False

    @classmethod
    def for_pattern(cls, ledger: TrustLedger, sig: str) -> "Scrutiny":
        if ledger.is_trusted(sig):
            return cls(trusted=True, force_dry_run=False, mark_suspect=False)
        return cls(trusted=False,
                   cost_cap_fraction=ledger.provisional_budget_fraction,
                   force_dry_run=True, mark_suspect=True)
