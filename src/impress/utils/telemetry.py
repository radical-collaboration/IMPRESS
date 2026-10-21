"""Telemetry for pipeline stages that never reach the workflow engine.

`auto_register_task(local_task=True)` registers the raw coroutine, so
asyncflow emits no lifecycle events for it. `wrap_local_task` times each call
and emits one `impress.LocalStage` event, so local stages show up in the same
trace as executable tasks.

`rhapsody.telemetry` is optional. Without it, or when telemetry was never
started, the wrapper only times the call and emits nothing.
"""

import functools
import time
from collections.abc import Callable
from typing import Any

try:
    from rhapsody.telemetry import define_event
    from rhapsody.telemetry.events import make_event

    # define_event requires a dotted namespace; a flat name raises ValueError.
    LocalStage = define_event(
        "impress.LocalStage",
        stage=str,
        pipeline=str,
        duration=float,
        status=str,
    )
except Exception:  # telemetry extra not installed: stay importable
    make_event = None
    LocalStage = None


def emit_local_stage(
    telemetry: Any, pipeline: str, stage: str, duration: float, status: str
) -> None:
    """Emit one `impress.LocalStage` event. A no-op when telemetry is off."""
    if LocalStage is None or telemetry is None:
        return
    try:
        telemetry.emit(
            make_event(
                LocalStage,
                session_id=telemetry.session_id,
                # Same value earlier traces carry, so they stay comparable.
                backend="rhapsody",
                stage=stage,
                pipeline=pipeline,
                duration=duration,
                status=status,
            )
        )
    except Exception:
        # Instrumentation must never take the pipeline down.
        pass


def wrap_local_task(pipeline: Any, func: Callable) -> Callable:
    """Wrap a local-task coroutine so each call emits an `impress.LocalStage`.

    The telemetry manager is looked up at call time through
    `pipeline.telemetry`, because tasks are registered before telemetry starts.
    `__name__` is preserved, since `auto_register_task` binds the task under it.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        t0 = time.monotonic()
        status = "completed"
        try:
            return await func(*args, **kwargs)
        except BaseException:
            status = "failed"
            raise
        finally:
            emit_local_stage(
                getattr(pipeline, "telemetry", None),
                pipeline.name,
                func.__name__,
                time.monotonic() - t0,
                status,
            )

    return wrapper
