from collections.abc import Awaitable
from typing import Any, Callable, Dict, Optional, Type

from pydantic import BaseModel, Field, field_validator

from .impress_pipeline import ImpressBasePipeline


class PipelineSetup(BaseModel):
    """Pydantic model for pipeline configuration."""

    name: str = Field(..., description="Name of the pipeline")
    type: Type[ImpressBasePipeline] = Field(..., description="Pipeline class type")
    config: Dict[str, Any] = Field(default_factory=dict, description="Pipeline configuration")
    adaptive_fn: Optional[Callable[[ImpressBasePipeline], Awaitable[None]]] = Field(
        default=None,
        description="Optional adaptive function for the pipeline"
    )
    # Support for additional keyword arguments
    kwargs: Dict[str, Any] = Field(default_factory=dict, description="Additional keyword arguments")

    class Config:
        # Allow arbitrary types (needed for Type[ImpressBasePipeline])
        arbitrary_types_allowed = True

    @field_validator('type')
    def validate_pipeline_type(cls, v):
        """Validate that type is a subclass of ImpressBasePipeline."""
        if not isinstance(v, type) or not issubclass(v, ImpressBasePipeline):
            raise ValueError(f"Expected an ImpressBasePipeline subclass, got {type(v)}")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for backward compatibility."""
        result = {
            'name': self.name,
            'type': self.type,
            'config': self.config,
        }
        if self.adaptive_fn:
            result['adaptive_fn'] = self.adaptive_fn

        # Merge kwargs into the result
        result.update(self.kwargs)
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PipelineSetup':
        """Create PipelineSetup from dictionary (for backward compatibility)."""
        # Extract known fields
        known_fields = {'name', 'type', 'config', 'adaptive_fn'}
        pipeline_data = {k: v for k, v in data.items() if k in known_fields}

        # Everything else goes to kwargs
        kwargs = {k: v for k, v in data.items() if k not in known_fields}
        pipeline_data['kwargs'] = kwargs

        return cls(**pipeline_data)
