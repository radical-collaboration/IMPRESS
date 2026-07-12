"""Shared telemetry helpers for IMPRESS pipelines and example runners.

Wraps radical.asyncflow/rhapsody telemetry (flow.start_telemetry(),
telemetry.subscribe(), telemetry.emit()) so runner scripts and pipeline
task registration don't duplicate the same boilerplate.

`rhapsody.telemetry` is an optional dependency of the core `impress`
package (only example runners that use an HPC backend need it installed).
Everything here degrades gracefully to a no-op when it isn't available,
matching the existing opt-in telemetry design in ImpressManager.
"""

import functools
import time
from typing import Any, Callable, Optional

from .logger import ImpressLogger

try:
    from rhapsody.telemetry import define_event
    from rhapsody.telemetry.events import make_event

    _TELEMETRY_EVENTS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when rhapsody isn't installed
    _TELEMETRY_EVENTS_AVAILABLE = False
    define_event = None
    make_event = None

if _TELEMETRY_EVENTS_AVAILABLE:
    LocalTaskStarted = define_event(
        "impress.LocalTaskStarted",
        pipeline_name=str,
        task_name=str,
    )

    LocalTaskCompleted = define_event(
        "impress.LocalTaskCompleted",
        pipeline_name=str,
        task_name=str,
        duration_seconds=float,
    )

    LocalTaskFailed = define_event(
        "impress.LocalTaskFailed",
        pipeline_name=str,
        task_name=str,
        duration_seconds=float,
        error=str,
    )
else:  # pragma: no cover - exercised when rhapsody isn't installed
    LocalTaskStarted = None
    LocalTaskCompleted = None
    LocalTaskFailed = None


def build_telemetry_config(
    checkpoint_path: str = "./telemetry/",
    resource_poll_interval: float = 5.0,
    **overrides: Any,
) -> dict[str, Any]:
    """Build the kwargs dict forwarded to `flow.start_telemetry()`."""
    config: dict[str, Any] = {
        "checkpoint_path": checkpoint_path,
        "resource_poll_interval": resource_poll_interval,
    }
    config.update(overrides)
    return config


def make_default_subscriber(logger: ImpressLogger) -> Callable[[Any], None]:
    """Return a telemetry.subscribe() callback that logs task events via the logger."""

    def _on_task_event(event: Any) -> None:
        if getattr(event, "event_type", None) in ("TaskFailed", "TaskCompleted"):
            logger.task_event(event)

    return _on_task_event


def _emit_local_task_event(telemetry: Any, event_cls: Any, **fields: Any) -> None:
    if telemetry is None or not _TELEMETRY_EVENTS_AVAILABLE:
        return
    session_id = getattr(telemetry, "session_id", None)
    telemetry.emit(make_event(event_cls, session_id=session_id, **fields))


def wrap_local_task(pipeline: Any, func: Callable) -> Callable:
    """Wrap a local-task coroutine to emit LocalTask* telemetry events.

    Local tasks never go through `flow.executable_task`/`flow.function_task`,
    so asyncflow's automatic telemetry never sees them. It is safe to call
    `telemetry.emit()` directly here (unlike inside a flow task body) because
    local tasks run in-process and are never cloudpickled for subprocess
    execution.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        telemetry: Optional[Any] = getattr(pipeline, "telemetry", None)
        task_name = func.__name__
        _emit_local_task_event(
            telemetry,
            LocalTaskStarted,
            pipeline_name=pipeline.name,
            task_name=task_name,
        )
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            _emit_local_task_event(
                telemetry,
                LocalTaskFailed,
                pipeline_name=pipeline.name,
                task_name=task_name,
                duration_seconds=time.monotonic() - start,
                error=str(exc),
            )
            raise
        else:
            _emit_local_task_event(
                telemetry,
                LocalTaskCompleted,
                pipeline_name=pipeline.name,
                task_name=task_name,
                duration_seconds=time.monotonic() - start,
            )
            return result

    return wrapper
