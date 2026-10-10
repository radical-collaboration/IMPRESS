"""Durable run ledger.

Nothing in the stack provides this: asyncflow state is in-process and cleared at
shutdown, rhapsody has no persistence. Work outlives the agent, so without a persisted
record an agent restart orphans it.

Append-only and event-sourced. Current state is a last-write-wins fold over the log,
which is what makes it safe to write from more than one process: `O_APPEND` below
`PIPE_BUF` is atomic on POSIX, so concurrent writers interleave lines without a lock and
no writer can clobber another's record.

The log holds PAYLOADS, not just statuses. A resumed campaign that could only learn
*that* a run finished, and never what it produced, would have to re-run it - which for
this workload means paying for a GPU allocation twice.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.results import RunOutcome, RunState

#: States from which nothing further is expected. Anything else is still open, and a
#: restart has to decide what to do about it.
TERMINAL = {s.value for s in RunState if s.is_terminal}


class JobLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- writing -------------------------------------------------------------
    def record(self, **fields: Any) -> None:
        fields["ts"] = datetime.now(timezone.utc).isoformat()
        with self.path.open("a") as fh:
            fh.write(json.dumps(fields, default=str) + "\n")

    def record_outcome(self, run_id: str, outcome: RunOutcome, **extra: Any) -> None:
        """Persist a finished run in full, so a restart need not re-run it."""
        self.record(job_id=run_id, status=outcome.state.value,
                    outcome=outcome.model_dump(mode="json"), **extra)

    # -- reading -------------------------------------------------------------
    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line)
                for line in self.path.read_text().splitlines() if line.strip()]

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Current state per run: a last-write-wins fold over the log."""
        state: dict[str, dict[str, Any]] = {}
        for e in self.entries():
            if jid := e.get("job_id"):
                state[jid] = {**state.get(jid, {}), **e}
        return state

    def open_jobs(self) -> list[dict[str, Any]]:
        """Runs submitted but never resolved - what recovery must reconcile."""
        return [j for j in self.snapshot().values()
                if j.get("status") not in TERMINAL]

    def outcome(self, run_id: str) -> RunOutcome | None:
        """The persisted result of a finished run, if the log holds one."""
        rec = self.snapshot().get(run_id)
        if not rec or not rec.get("outcome"):
            return None
        return RunOutcome(**rec["outcome"])
