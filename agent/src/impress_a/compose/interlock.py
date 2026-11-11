"""The self-promoting interlock (decision 0003).

Novel compositions are never blocked and never trusted on sight. A pattern - the graph's
SHAPE, not its parameter values - earns trusted status mechanically by accumulating clean
runs, and loses it on any failure. The trust ledger is site-scoped and spans campaigns,
because one campaign may not run a pattern N times.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PatternRecord(BaseModel):
    signature: str
    tools: list[str] = Field(default_factory=list)
    clean_runs: int = 0
    trusted: bool = False
    demotions: int = 0
    #: True when trust was GRANTED rather than earned. Never conflated with `trusted`: a
    #: figure derived from an asserted-trusted admission must be reportable as such, or
    #: "this pattern earned trust over three clean runs" becomes a claim nobody can check.
    asserted: bool = False
    #: Who granted it, why, and against which commit. Empty for earned trust.
    asserted_by: str = ""
    asserted_reason: str = ""
    asserted_at: str = ""
    git_sha: str = ""


class TrustLedger(BaseModel):
    """Append-only on disk; site-scoped, not campaign-scoped.

    Genuinely append-only, as the docstring always claimed. It used to rewrite the whole
    file on every update, which is a lost update waiting to happen: the file is shared
    across campaigns by design, so two campaigns promoting patterns concurrently would
    silently discard one another's evidence. An `O_APPEND` write below `PIPE_BUF` is
    atomic on POSIX, so an event log needs no lock.

    `patterns` is an in-memory fold of that log. It is deliberately NOT re-folded before
    every read: an in-process caller may clear or adjust it to model a novel pattern, and
    a silent reload would undo that. A multi-process reader (the run service) calls
    `reload()` explicitly when it wants another process's evidence.
    """

    promote_after: int = 3
    provisional_budget_fraction: float = 0.10
    patterns: dict[str, PatternRecord] = Field(default_factory=dict)
    path: str | None = None

    @classmethod
    def load(cls, path: str | Path, **kw) -> TrustLedger:
        led = cls(path=str(Path(path)), **kw)
        led.reload()
        return led

    # -- the log -------------------------------------------------------------
    def reload(self) -> None:
        """Rebuild `patterns` by folding the event log."""
        if not self.path:
            return
        p = Path(self.path)
        self.patterns = {}
        if not p.exists():
            # Carry forward a snapshot written by the pre-log format, so upgrading does
            # not silently discard trust a site has already earned.
            legacy = p.with_suffix(".json")
            if legacy.exists():
                data = json.loads(legacy.read_text())
                self.patterns = {k: PatternRecord(**v)
                                 for k, v in data.get("patterns", {}).items()}
            return
        for line in p.read_text().splitlines():
            if line.strip():
                self._apply(json.loads(line))

    def _apply(self, e: dict) -> None:
        sig = e.get("signature")
        if not sig:
            return
        r = self.patterns.get(sig)
        if r is None:
            r = self.patterns[sig] = PatternRecord(signature=sig, tools=e.get("tools", []))
        event = e.get("event")
        if event == "clean" and not r.trusted:
            r.clean_runs += 1
            if r.clean_runs >= self.promote_after:
                r.trusted = True
        elif event == "failure":
            if r.trusted:
                r.demotions += 1
            r.trusted = False
            r.clean_runs = 0
            r.asserted = False      # a demoted assertion was wrong; it does not survive it
        elif event == "asserted":
            r.trusted = True
            r.asserted = True
            r.asserted_by = e.get("by", "")
            r.asserted_reason = e.get("reason", "")
            r.asserted_at = e.get("ts", "")
            r.git_sha = e.get("git_sha", "")
        elif event == "revoked":
            r.trusted = False
            r.asserted = False
            r.clean_runs = 0

    def _append(self, event: str, sig: str, **extra: Any) -> None:
        if not self.path:
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(UTC).isoformat(),
               "event": event, "signature": sig, **extra}
        with p.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    # -- evidence ------------------------------------------------------------
    def record_for(self, sig: str, tools: list[str]) -> PatternRecord:
        if sig not in self.patterns:
            self.patterns[sig] = PatternRecord(signature=sig, tools=sorted(set(tools)))
            self._append("seen", sig, tools=sorted(set(tools)))
        return self.patterns[sig]

    def is_trusted(self, sig: str) -> bool:
        r = self.patterns.get(sig)
        return bool(r and r.trusted)

    def on_clean_run(self, sig: str) -> bool:
        """Returns True if this run promoted the pattern."""
        r = self.patterns.get(sig)
        if r is None or r.trusted:
            return False
        self._append("clean", sig)
        r.clean_runs += 1
        if r.clean_runs >= self.promote_after:
            r.trusted = True
            return True
        return False

    def assert_trusted(self, sig: str, tools: list[str], *, reason: str, by: str = "",
                       git_sha: str = "") -> PatternRecord:
        """Grant trust to a pattern whose Tasks are proven outside this system.

        The pre-loaded Toolkit is the six-stage chain from
        `examples/small_molecule_binding`, which has months of multi-node campaigns behind it.
        Spending an allocation re-earning trust for it buys nothing: promotion costs three
        consecutive clean runs under a forced dry-run, a 10%-of-available cost cap and
        one-instance-in-flight, and backlog A10 is the case where that is not merely wasteful
        but impossible - replica multiplicity is part of the signature, so width 4 can never
        earn trust under a realistic budget and would stay serialised behind the
        one-in-flight rule forever.

        **This widens the residual risk ADR 0003 accepts.** 0003 accepts that a *consistent*
        novel silent failure will promote; an asserted pattern never receives the examination
        and delay the interlock buys at all. The justification is external evidence plus a
        passing `impress-a validate-tasks` on the same hardware - never fiat - and
        `asserted_reason` is where that justification is recorded.

        **Not three forged `clean` events.** That would also produce a trusted record, and
        would be indistinguishable from earned evidence afterwards - corrupting the one log
        the interlock reasons from. Hence a distinct event kind.

        Demotion still applies: `on_failure` clears `asserted` along with `trusted`, because a
        demoted assertion was wrong and should not survive being disproved.
        """
        if not reason.strip():
            raise ValueError("an assertion needs a reason: it is the justification on the "
                             "record, and the thing a later reader will ask for")
        r = self.record_for(sig, tools)
        self._append("asserted", sig, tools=sorted(set(tools)), reason=reason, by=by,
                     git_sha=git_sha)
        r.trusted = True
        r.asserted = True
        r.asserted_by = by
        r.asserted_reason = reason
        r.git_sha = git_sha
        return r

    def revoke(self, sig: str, *, reason: str) -> bool:
        """Withdraw an assertion. Returns False if the pattern was not trusted."""
        r = self.patterns.get(sig)
        if r is None or not r.trusted:
            return False
        self._append("revoked", sig, reason=reason)
        r.trusted = False
        r.asserted = False
        r.clean_runs = 0
        return True

    def on_failure(self, sig: str) -> bool:
        """Demotion is symmetric: trust decays on evidence. Returns True if demoted.

        Clears `asserted` as well as `trusted`, and must: a demoted assertion was wrong, and
        should not survive being disproved. It also has to match what `_apply` does when the
        log is re-folded, or the live record and `reload()` would answer differently - the kind
        of divergence that shows up as a pattern being trusted in one process and not in the
        next.
        """
        r = self.patterns.get(sig)
        if r is None:
            return False
        was = r.trusted
        self._append("failure", sig)
        r.trusted = False
        r.asserted = False
        r.clean_runs = 0
        if was:
            r.demotions += 1
        return was


class Scrutiny(BaseModel):
    """Extra constraints applied to a provisional pattern."""

    trusted: bool
    cost_cap_fraction: float | None = None
    force_dry_run: bool = True
    mark_suspect: bool = False

    @classmethod
    def for_pattern(cls, ledger: TrustLedger, sig: str) -> Scrutiny:
        if ledger.is_trusted(sig):
            return cls(trusted=True, force_dry_run=False, mark_suspect=False)
        return cls(trusted=False,
                   cost_cap_fraction=ledger.provisional_budget_fraction,
                   force_dry_run=True, mark_suspect=True)
