"""The task registry: durable, append-only, and keyed by TASK rather than by run.

A second file beside `jobs/ledger.jsonl`, not a change to it. The run ledger folds on
`job_id`, and `RunService.outcome` recovery depends on that - re-keying it would trade one
missing index for another. So this is additive: `jobs/tasks.jsonl`, folded on `task_id`.

Why it has to exist at all: a task id used to be `r{r}_s{i}_{tool}`, unique only inside one
`TaskGraph`, and per-task data existed only nested inside a `RunOutcome`. To find one task you
had to know its run and scan a list. That makes DEFER, CANCEL and any form of per-task
tracking unexpressible, and asyncflow offers no help - it tags tasks with `workflow_id` and
exposes no lookup by it, so the caller's table is the only index that can exist.

Same append-only discipline and the same reason as `exec/ledger.py`: an `O_APPEND` write below
`PIPE_BUF` is atomic on POSIX, so an event log needs no lock, and two campaigns writing
concurrently cannot discard one another's records the way a read-modify-write of a whole file
would.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.spec import TaskRecord, TaskState

#: States a record can no longer leave.
TERMINAL = {s.value for s in TaskState if s.is_terminal}


class TaskLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- writing -------------------------------------------------------------
    def record(self, **fields: Any) -> None:
        """Append one event. `task_id` is required; everything else is the event's payload."""
        fields["ts"] = datetime.now(UTC).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(fields, default=str) + "\n")

    def record_task(self, rec: TaskRecord) -> None:
        self.record(task_id=rec.task_id, event="task", task=rec.model_dump(mode="json"))

    def record_state(self, task_id: str, state: TaskState, **extra: Any) -> None:
        self.record(task_id=task_id, event="state", state=state.value, **extra)

    # -- reading -------------------------------------------------------------
    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines()
                if line.strip()]

    def snapshot(self) -> dict[str, TaskRecord]:
        """Fold the log into the current record per task. Last write wins, per field."""
        out: dict[str, TaskRecord] = {}
        for e in self.entries():
            tid = e.get("task_id")
            if not tid:
                continue
            if e.get("event") == "task":
                out[tid] = TaskRecord(**e["task"])
            elif e.get("event") == "state" and tid in out:
                rec = out[tid]
                rec.state = TaskState(e["state"])
                for key in ("run_id", "outcome_ref"):
                    if e.get(key):
                        setattr(rec, key, e[key])
        return out

    def get(self, task_id: str) -> TaskRecord | None:
        return self.snapshot().get(task_id)

    def open_tasks(self) -> list[TaskRecord]:
        """Tasks that have not reached a terminal state.

        What a restart needs in order to know what it may still be holding - and on HPC that
        work holds an allocation whether or not anyone remembers submitting it.
        """
        return [r for r in self.snapshot().values() if r.state.value not in TERMINAL]

    def for_stage(self, stage_id: str) -> list[TaskRecord]:
        return [r for r in self.snapshot().values() if r.stage_id == stage_id]
