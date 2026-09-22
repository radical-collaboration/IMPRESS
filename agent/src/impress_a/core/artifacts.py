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


#: Above this, hashing costs more than the provenance is worth; size is recorded either
#: way so a missing digest is visibly a decision rather than an omission.
MAX_HASH_BYTES = 64 * 1024 * 1024


class ArtifactRef(BaseModel):
    """A typed handle to data on disk. Large binaries are never inlined.

    This is what a tool hands the next tool, and it is deliberately serializable: a
    reasoner that lives in another process - the point of the whole decoupling - can
    hold one, compare it, and pass it back without the file ever crossing the wire. The
    digest is what makes that safe, since a path alone says nothing about whether the
    bytes behind it are still the ones the campaign reasoned about.
    """

    type: ArtifactType
    path: str | None = None
    value: Any = None  # only for small in-memory artifacts (metrics)
    sha256: str | None = None
    bytes: int | None = None

    def hash_file(self) -> "ArtifactRef":
        """Record size, and content digest for anything small enough to be worth it."""
        if not self.path:
            return self
        f = Path(self.path)
        if not f.is_file():
            return self
        self.bytes = f.stat().st_size
        if self.bytes <= MAX_HASH_BYTES:
            self.sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
        return self

    @property
    def located(self) -> str | None:
        """Whatever a consumer should actually open or use."""
        return self.path if self.path is not None else self.value


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
