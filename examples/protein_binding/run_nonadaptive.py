import asyncio
from typing import List

from rhapsody.backends import DragonExecutionBackendV3

from impress import PipelineSetup
from impress import ImpressManager
from impress.utils.logger import ImpressLogger
from impress.utils.telemetry import build_telemetry_config, make_default_subscriber
from protein_binding import ProteinBindingPipeline

import rhapsody, logging
rhapsody.enable_logging(level=logging.DEBUG)


async def impress_protein_bind_nonadaptive() -> None:
    backend = await DragonExecutionBackendV3()

    manager: ImpressManager = ImpressManager(
        execution_backend=backend,
        telemetry_config=build_telemetry_config(checkpoint_path="./telemetry/"),
        telemetry_subscribers=[make_default_subscriber(ImpressLogger())],
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
        manager.logger.info(f"tasks={summary.get('tasks', {})}", "manager")
        dur = summary.get("duration")
        if dur:
            manager.logger.info(
                f"mean task time: {dur['mean_seconds'] * 1000:.1f} ms", "manager"
            )

    await manager.flow.shutdown()


if __name__ == "__main__":
    asyncio.run(impress_protein_bind_nonadaptive())
