import asyncio
from typing import List

from rhapsody.backends import DragonExecutionBackendV3
from rhapsody.telemetry import define_event

from impress import PipelineSetup
from impress import ImpressManager
from protein_binding import ProteinBindingPipeline

import rhapsody, logging
rhapsody.enable_logging(level=logging.DEBUG)


def _on_task_event(event) -> None:
    if event.event_type == "TaskFailed":
        wid = getattr(event, "workflow_id", None)
        print(f"[TELEMETRY] TaskFailed  task={event.task_id}  workflow={wid}")


async def impress_protein_bind_nonadaptive() -> None:
    backend = await DragonExecutionBackendV3()

    manager: ImpressManager = ImpressManager(
        execution_backend=backend,
        telemetry_config={
            "checkpoint_path": "./telemetry/",
            "resource_poll_interval": 5.0,
        },
        telemetry_subscribers=[_on_task_event],
    )

    pipeline_setups: List[PipelineSetup] = [
        PipelineSetup(
            name=f"p{str(i)}",
            type=ProteinBindingPipeline,
        )
        for i in range(1, 17)
    ]

    await manager.start(pipeline_setups=pipeline_setups)

    if manager.telemetry:
        summary = manager.telemetry.summary()
        print(f"[TELEMETRY] tasks={summary.get('tasks', {})}")
        dur = summary.get("duration")
        if dur:
            print(f"[TELEMETRY] mean task time: {dur['mean_seconds'] * 1000:.1f} ms")

    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind_nonadaptive())
