from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional


class FlowgenticImpressBasePipeline(ABC):
    """Base adaptive pipeline contract used by Flowgentic manager."""

    def __init__(self, name: str, integration: Any, **config: Any) -> None:
        self.name = name
        self.integration = integration
        self.state: dict[str, Any] = {}
        self.config = config

        self.kill_parent = False
        self.invoke_adaptive_step = False

        self._adaptive_barrier = asyncio.Event()
        self._incoming_child_pipeline_request: Optional[dict[str, Any]] = None

    def submit_child_pipeline_request(self, pipeline_config: dict[str, Any]) -> None:
        self._incoming_child_pipeline_request = pipeline_config

    def get_child_pipeline_request(self) -> Optional[dict[str, Any]]:
        if self._incoming_child_pipeline_request:
            request = self._incoming_child_pipeline_request
            self._incoming_child_pipeline_request = None
            return request
        return None

    async def run_adaptive_step(self, wait: bool = True) -> None:
        self._set_adaptive_flag(True)
        if wait:
            await self._await_adaptive_unlock()

    def _set_adaptive_flag(self, value: bool = True) -> None:
        self.invoke_adaptive_step = value
        if value:
            self._adaptive_barrier.clear()

    async def _await_adaptive_unlock(self) -> None:
        await self._adaptive_barrier.wait()

    @abstractmethod
    async def run(self) -> None:
        pass

    @abstractmethod
    def finalize(self, sub_iter_seqs: dict[str, Any]) -> None:
        pass
