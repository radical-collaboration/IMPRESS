import inspect
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Optional, Union

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .impress_pipeline import ImpressBasePipeline


def _is_flow_task(fn: Callable) -> bool:
    """True for the task object a flow task decorator returned.

    asyncflow marks the functions it registers with `__task_description__`,
    but it sets the mark on the *function being decorated*, before
    `functools.wraps` copies it onto the wrapper
    (`workflow_manager.py:559-561`). So the mark alone cannot tell the task
    apart from the bare function it was declared from: once a callback has
    been declared anywhere, both carry it.

    What separates them is that the decorator returns a plain function
    (`def wrapped`, `:562`) which hands back a future, while the body it
    wraps is an `async def`. `inspect.iscoroutinefunction` does not follow
    `__wrapped__`, so it still reports the bare function as a coroutine
    function through `functools.wraps`.
    """
    return hasattr(fn, "__task_description__") and not inspect.iscoroutinefunction(fn)


class PipelineSetup(BaseModel):
    """Pydantic model for pipeline configuration."""

    name: str = Field(..., description="Name of the pipeline")
    type: Annotated[type[ImpressBasePipeline], Field(..., description="Pipeline class type")]
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Pipeline configuration",
    )
    adaptive_fn: Optional[Callable[[ImpressBasePipeline], Union[Awaitable[None], None]]] = Field(
        default=None,
        description=(
            "Optional adaptive function for the pipeline. Must be an engine "
            "task the caller declared with flow.function_task(...), on a "
            "thread-pool backend. ImpressManager awaits it and chooses "
            "nothing."
        ),
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
            raise ValueError(f"Expected an ImpressBasePipeline subclass, got {type(v)}")
        return v

    @field_validator("adaptive_fn")
    @classmethod
    def validate_adaptive_fn(
        cls, v: Optional[Callable], info: ValidationInfo
    ) -> Optional[Callable]:
        """Reject an `adaptive_fn` that is not a declared engine task.

        The manager has no path of its own to run a callback on, so this
        fails at construction rather than letting the call fail inside the
        adaptive task, where the error is caught, logged, and the pipeline
        continues as though a decision had been made.

        Checking here rather than at submission also covers a child config,
        which reaches `from_dict()` before the manager sees it.
        """
        if v is None or _is_flow_task(v):
            return v

        # `name` is declared first, so it has been validated by now; it is
        # absent only if it failed its own validation.
        name = info.data.get("name", "<unnamed>")
        hint = (
            "Declare it on a thread-pool backend, e.g. "
            "flow.function_task(backend='local')(adaptive_decision), and "
            "pass the result as adaptive_fn."
        )

        if hasattr(v, "__task_description__"):
            # Marked, but still a coroutine function: this is the bare body,
            # not the task the decorator returned. Declaring it anywhere
            # marks it, so the mark alone does not catch this.
            raise TypeError(
                f"adaptive_fn for pipeline {name!r} is the undecorated "
                f"function, not the engine task declared from it. Pass the "
                f"object flow.function_task(...) returned — a child config "
                f"must carry the task, not the bare function."
            )

        kind = "coroutine function" if inspect.iscoroutinefunction(v) else "callable"
        raise TypeError(
            f"adaptive_fn for pipeline {name!r} is a plain {kind}, not an engine task. {hint}"
        )

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
