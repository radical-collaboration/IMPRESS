import asyncio

from abc import ABC, abstractmethod

class ImpressBasePipeline(ABC):
    def __init__(self, config: dict):
        self.state = {}
        self.config = config
        self.invoke_adaptive_step = False
        self._adaptive_barrier = asyncio.Event()

        # Start as "unblocked"
        self._adaptive_barrier.set()

    @abstractmethod
    def run(self):
        """Optional: override in subclass"""
        pass

    @abstractmethod
    def register_pipeline_tasks(self):
        """Optional: override in subclass"""
        pass
