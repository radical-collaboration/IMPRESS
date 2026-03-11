from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Type

if TYPE_CHECKING:
    from .base import FlowgenticImpressBasePipeline


AdaptiveFn = Callable[["FlowgenticImpressBasePipeline"], Awaitable[None]]


@dataclass(slots=True)
class PipelineSetup:
    """Configuration contract for submitting a pipeline to the manager."""

    name: str
    type: Type["FlowgenticImpressBasePipeline"]
    config: dict[str, Any] = field(default_factory=dict)
    adaptive_fn: Optional[AdaptiveFn] = None
    kwargs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "config": self.config,
        }
        if self.adaptive_fn is not None:
            payload["adaptive_fn"] = self.adaptive_fn
        payload.update(self.kwargs)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineSetup":
        known_fields = {"name", "type", "config", "adaptive_fn"}
        kwargs = {k: v for k, v in data.items() if k not in known_fields}
        return cls(
            name=data["name"],
            type=data["type"],
            config=data.get("config", {}),
            adaptive_fn=data.get("adaptive_fn"),
            kwargs=kwargs,
        )
