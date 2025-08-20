from collections.abc import Awaitable
from typing import Annotated, Any, Callable, Optional

from pydantic import BaseModel, Field, field_validator

from .impress_pipeline import ImpressBasePipeline


class PipelineSetup(BaseModel):
    """Pydantic model for pipeline configuration."""

    name: str = Field(..., description="Name of the pipeline")
    type: Annotated[type[ImpressBasePipeline],
    Field(..., description="Pipeline class type")]
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Pipeline configuration",
    )
    adaptive_fn: Optional[Callable[[ImpressBasePipeline], Awaitable[None]]] = Field(
        default=None,
        description="Optional adaptive function for the pipeline",
    )
    kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional keyword arguments",
    )

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("type")
    @classmethod
    def validate_pipeline_type(cls, v: Any) -> type[ImpressBasePipeline]:
        """Validate that type is a subclass of ImpressBasePipeline."""
        if not isinstance(v, type) or not issubclass(v, ImpressBasePipeline):
            raise ValueError(
                f"Expected an ImpressBasePipeline subclass, got {type(v)}"
            )
        return v

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for backward compatibility."""
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "config": self.config,
        }
        if self.adaptive_fn is not None:
            result["adaptive_fn"] = self.adaptive_fn

        result.update(self.kwargs)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineSetup":
        """Create PipelineSetup from dictionary (for backward compatibility)."""
        known_fields = {"name", "type", "config", "adaptive_fn"}
        pipeline_data = {k: v for k, v in data.items() if k in known_fields}

        kwargs = {k: v for k, v in data.items() if k not in known_fields}
        pipeline_data["kwargs"] = kwargs

        return cls(**pipeline_data)
