"""Artifacts and properties.

`Property` implements decision 0012: a predicted value and a measured value for the same
quantity are the SAME type with different `source`/`authority`, not two quantities.
Objectives are declared against `name`, so a surrogate today and a robotic-lab assay
tomorrow are interchangeable without touching the campaign spec.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .types import ArtifactType


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactRef(BaseModel):
    """A typed handle to data on disk. Large binaries are never inlined."""

    type: ArtifactType
    path: str | None = None
    value: Any = None  # only for small in-memory artifacts (metrics)
    sha256: str | None = None

    def hash_file(self) -> "ArtifactRef":
        if self.path and Path(self.path).is_file():
            h = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
            self.sha256 = h
        return self


class SourceKind(str, Enum):
    PREDICTED = "predicted"
    MEASURED = "measured"


class PropertySource(BaseModel):
    """Where an answer came from. `authority` breaks ties; measurements outrank."""

    name: str
    kind: SourceKind = SourceKind.PREDICTED
    authority: int = 10
    latency_class: str = "inline"  # inline | job | external_long


# Conventional authority bands. Measurements outrank every prediction.
AUTHORITY_WEAK_PROXY = 5
AUTHORITY_ML_PREDICTOR = 10
AUTHORITY_PHYSICS = 20
AUTHORITY_LITERATURE = 50
AUTHORITY_ASSAY = 100


class Property(BaseModel):
    """One scientific quantity. Objectives reference `name`, never `source`."""

    name: str
    value: float | str | None
    unit: str | None = None
    source: PropertySource
    confidence: float | None = None
    observed_at: datetime = Field(default_factory=_now)
    provenance: dict[str, Any] = Field(default_factory=dict)
    superseded_by: str | None = None

    @property
    def is_measured(self) -> bool:
        return self.source.kind is SourceKind.MEASURED

    def outranks(self, other: "Property") -> bool:
        return self.source.authority > other.source.authority
