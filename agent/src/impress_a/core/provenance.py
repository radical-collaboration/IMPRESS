"""Append-only JSONL provenance.

Written before the action it describes completes. The log is truth; checkpoints are an
index. This is what makes a campaign reconstructable (Part A risk R8) and what makes the
model-D replay policy possible.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class ProvenanceLog:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _f(self, kind: str) -> Path:
        return self.root / f"{kind}.jsonl"

    def append(self, kind: str, record: dict[str, Any]) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        with self._f(kind).open("a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def read(self, kind: str) -> Iterator[dict[str, Any]]:
        p = self._f(kind)
        if not p.exists():
            return iter(())
        return (json.loads(l) for l in p.read_text().splitlines() if l.strip())

    def decisions(self) -> list[dict[str, Any]]:
        return list(self.read("decisions"))
