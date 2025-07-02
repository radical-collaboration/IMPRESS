import asyncio
from abc import ABC, abstractmethod


class ImpressBasePipeline(ABC):
    def __init__(self, name: str, flow=None, **config):
        self.name = name
        self.flow = flow
        self.state = {}
        self.config = config
        self.kill_parent = False
        self.invoke_adaptive_step = False
        self._adaptive_barrier = asyncio.Event()

        # Call the registration method - subclasses must implement this
        self.register_pipeline_tasks()

    def auto_register_task(self):
        """Decorator to automatically register tasks with the flow"""
        if not self.flow:
            raise ValueError("Flow must be provided to use auto_register_task")

        def decorator(func):
            task = self.flow.executable_task(func)
            setattr(self, func.__name__, task)
            return task
        return decorator

    def set_adaptive_flag(self, value: bool = True):
        """Set the adaptive flag and manage the barrier state"""
        self.invoke_adaptive_step = value
        if value:
            self._adaptive_barrier.clear()

    async def trigger_and_wait_adaptive(self):
        """Trigger adaptive step and wait for completion"""
        self.set_adaptive_flag(True)
        await self.await_adaptive_unlock()

    async def await_adaptive_unlock(self) -> any:
        """Pause until manager completes adaptive step and returns result."""
        print(f"[{self.name}] Starting adaptive task")
        await self._adaptive_barrier.wait()
        print(f"[{self.name}] Exiting adaptive step.")

    @abstractmethod
    async def run(self):
        """Main execution method - must be implemented by subclasses"""
        pass

    @abstractmethod
    def register_pipeline_tasks(self):
        """Register pipeline tasks - must be implemented by subclasses"""
        pass

    # Optional methods that subclasses can override
    async def get_scores_map(self):
        """Optional: Return scores mapping"""
        return {}

    async def finalize(self):
        """Optional: Cleanup or finalization logic"""
        pass

    def get_current_config_for_next_pipeline(self):
        """Optional: Return config for next pipeline"""
        return {"name": "default_pipeline", "type": self.__class__}
    