"""Durable external-job ledger (P4/P8).

Nothing in the stack provides this: asyncflow state is in-process and cleared at
shutdown, rhapsody has no persistence. External work outlives the agent, so without a
persisted record an agent restart orphans it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JobLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, **fields: Any) -> None:
        fields["ts"] = datetime.now(timezone.utc).isoformat()
        with self.path.open("a") as fh:
            fh.write(json.dumps(fields, default=str) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def open_jobs(self) -> list[dict[str, Any]]:
        """Jobs submitted but never resolved - what recovery must reconcile."""
        state: dict[str, dict[str, Any]] = {}
        for e in self.entries():
            if jid := e.get("job_id"):
                state[jid] = {**state.get(jid, {}), **e}
        return [j for j in state.values() if j.get("status") not in ("done", "failed", "cancelled")]
