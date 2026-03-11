from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from flowgentic.langGraph.main import LangraphIntegration

from .base import FlowgenticImpressBasePipeline
from .io import write_json
from .setup import PipelineSetup


class FlowgenticImpressManager:
    """Manager loop that mirrors IMPRESS behavior using Flowgentic integration."""

    def __init__(self, execution_backend: Any, base_path: Path) -> None:
        self.execution_backend = execution_backend
        self.base_path = base_path

        self.pipeline_tasks: dict[FlowgenticImpressBasePipeline, asyncio.Task] = {}
        self.adaptive_tasks: dict[FlowgenticImpressBasePipeline, asyncio.Task] = {}
        self.new_pipeline_buffer: list[PipelineSetup] = []

        self._summary: dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "completed_pipelines": [],
            "spawn_requests": [],
        }

    def _normalize_pipeline_setup(self, setup: Union[dict[str, Any], PipelineSetup]) -> PipelineSetup:
        if isinstance(setup, PipelineSetup):
            return setup
        if isinstance(setup, dict):
            return PipelineSetup.from_dict(setup)
        raise ValueError(f"Invalid pipeline setup type: {type(setup)!r}")

    def submit_new_pipelines(
        self,
        pipeline_setups: list[Union[dict[str, Any], PipelineSetup]],
        integration: LangraphIntegration,
    ) -> None:
        for setup_input in pipeline_setups:
            setup = self._normalize_pipeline_setup(setup_input)
            pipeline_kwargs = {**setup.config, **setup.kwargs}

            pipeline = setup.type(name=setup.name, integration=integration, **pipeline_kwargs)
            pipeline._adaptive_fn = setup.adaptive_fn

            task = asyncio.create_task(pipeline.run())
            self.pipeline_tasks[pipeline] = task

    async def _run_adaptive_fn(self, pipeline: FlowgenticImpressBasePipeline) -> None:
        try:
            adaptive_fn = getattr(pipeline, "_adaptive_fn", None)
            if adaptive_fn:
                await adaptive_fn(pipeline)
        finally:
            pipeline.invoke_adaptive_step = False
            pipeline._adaptive_barrier.set()

    async def start(self, pipeline_setups: list[Union[dict[str, Any], PipelineSetup]]) -> dict[str, Any]:
        async with LangraphIntegration(backend=self.execution_backend) as integration:
            self.submit_new_pipelines(pipeline_setups=pipeline_setups, integration=integration)

            while True:
                any_activity = False
                completed_pipelines: list[FlowgenticImpressBasePipeline] = []

                for pipeline, pipeline_future in list(self.pipeline_tasks.items()):
                    if pipeline.invoke_adaptive_step and pipeline not in self.adaptive_tasks:
                        adaptive_task = asyncio.create_task(self._run_adaptive_fn(pipeline))
                        self.adaptive_tasks[pipeline] = adaptive_task
                        any_activity = True

                    config = pipeline.get_child_pipeline_request()
                    if config:
                        self.new_pipeline_buffer.append(PipelineSetup.from_dict(config))
                        self._summary["spawn_requests"].append(
                            {
                                "parent": pipeline.name,
                                "child": config.get("name"),
                                "pass": getattr(pipeline, "passes", None),
                            }
                        )
                        any_activity = True

                    if getattr(pipeline, "kill_parent", False) and not pipeline_future.done():
                        pipeline_future.cancel()
                        completed_pipelines.append(pipeline)
                        continue

                    if pipeline_future.done():
                        if pipeline in self.adaptive_tasks and not self.adaptive_tasks[pipeline].done():
                            continue
                        completed_pipelines.append(pipeline)

                for pipeline in completed_pipelines:
                    pipeline_future = self.pipeline_tasks.pop(pipeline, None)
                    if pipeline in self.adaptive_tasks:
                        adaptive_task = self.adaptive_tasks[pipeline]
                        if not adaptive_task.done():
                            continue
                        self.adaptive_tasks.pop(pipeline, None)

                    status = "completed"
                    error: Optional[str] = None
                    if pipeline_future is not None and pipeline_future.cancelled():
                        status = "cancelled"
                    elif pipeline_future is not None:
                        exc = pipeline_future.exception()
                        if exc is not None:
                            status = "failed"
                            error = str(exc)

                    self._summary["completed_pipelines"].append(
                        {
                            "name": pipeline.name,
                            "status": status,
                            "passes_executed": getattr(
                                pipeline, "last_completed_pass", getattr(pipeline, "passes", None)
                            ),
                            "remaining_targets": len(getattr(pipeline, "fasta_list_2", [])),
                            "error": error,
                        }
                    )

                finished_adaptive = [p for p, t in self.adaptive_tasks.items() if t.done()]
                for pipeline in finished_adaptive:
                    self.adaptive_tasks.pop(pipeline, None)

                if self.new_pipeline_buffer:
                    buffered = list(self.new_pipeline_buffer)
                    self.new_pipeline_buffer.clear()
                    self.submit_new_pipelines(buffered, integration=integration)
                    any_activity = True

                if not self.pipeline_tasks and not self.new_pipeline_buffer and not self.adaptive_tasks:
                    break

                if not any_activity:
                    await asyncio.sleep(0.1)

        self._summary["finished_at"] = datetime.now().isoformat()
        summary_path = self.base_path / "run_summary.json"
        write_json(summary_path, self._summary)

        return self._summary
