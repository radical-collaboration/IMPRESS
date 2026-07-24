import asyncio
from abc import ABC, abstractmethod
from typing import Any

from ..utils.logger import ImpressLogger


class ImpressBasePipeline(ABC):
    """
    Abstract base class for all IMPRESS pipelines.

    Subclasses implement `register_pipeline_tasks()` to bind task methods
    (via `auto_register_task()`), `run()` to define the pipeline's control
    flow, and `finalize()` for cleanup. The base class provides the adaptive
    execution protocol (`run_adaptive_step()`) and the child-pipeline
    request mechanism (`submit_child_pipeline_request()` /
    `get_child_pipeline_request()`) used by `ImpressManager` to support
    dynamic, self-spawning pipeline trees.

    Attributes:
        name: Pipeline instance name.
        flow: The `radical.asyncflow` `WorkflowEngine` used to submit
            executable tasks.
        state: Free-form dict for passing data between pipeline stages.
        config: Extra keyword arguments captured at construction time.
        kill_parent: When set to True, the manager cancels this pipeline's
            task on its next poll.
        invoke_adaptive_step: When True, the manager runs this pipeline's
            adaptive function on its next poll.
        incoming_child_pipeline_request: Pending child-pipeline submission
            request, populated by `submit_child_pipeline_request()`.
    """

    def __init__(self, name: str, flow=None, **config):
        """
        Initialize the pipeline and register its tasks.

        Args:
            name: Pipeline instance name.
            flow: The `radical.asyncflow` `WorkflowEngine` used to submit
                executable tasks.
            **config: Additional configuration stored in `self.config` and
                available to subclasses.
        """
        self.name = name
        self.flow = flow
        self.state = {}
        self.config = config
        self.kill_parent = False
        self.invoke_adaptive_step = False
        self.incoming_child_pipeline_request = {}
        self._adaptive_barrier = asyncio.Event()

        # Call the registration method - subclasses must implement this
        self.register_pipeline_tasks()

        self.logger = ImpressLogger(self.name)

    def submit_child_pipeline_request(self, pipeline_config):
        """
        Submit a request to spawn a child pipeline.

        Args:
            pipeline_config (dict): Configuration for the new pipeline including
                                  'name', 'type', 'config', and 'adaptive_fn'
        """
        self.incoming_child_pipeline_request = pipeline_config

    def get_child_pipeline_request(self):
        """
        Get and clear any pending spawn request for child pipelines.

        Returns:
            dict or None: The spawn request configuration if one exists, None otherwise.
                         After calling this method, the spawn request is cleared.
        """
        if self.incoming_child_pipeline_request:
            request = self.incoming_child_pipeline_request

            # reset the value to avoid submission request duplication
            self.incoming_child_pipeline_request = None
            return request

        return None

    def auto_register_task(self, local_task=False, **task_kwargs):
        """
        Decorator factory that binds a task function as a callable pipeline method.

        Used inside `register_pipeline_tasks()` to register the coroutines
        that make up a pipeline's stages.

        Args:
            local_task: If False (default), wraps the function via
                `self.flow.executable_task(**task_kwargs)`, turning it into
                an HPC-executable task submitted through the workflow
                engine. If True, the function is registered as-is and runs
                as a plain local coroutine (e.g. for CPU-only analysis
                steps).
            **task_kwargs: Forwarded to `self.flow.executable_task()` when
                `local_task` is False.

        Returns:
            A decorator that binds the wrapped function to `self` under its
            own name (so it becomes callable as `await self.<func_name>()`).
        """

        def decorator(func):
            if not local_task:
                task = self.flow.executable_task(**task_kwargs)(func)
            else:
                task = func
            setattr(self, func.__name__, task)
            return task

        return decorator

    async def run_adaptive_step(self, wait: bool = True):
        """Trigger adaptive step and optionally wait for completion.

        Args:
            wait: If True, waits for adaptive step completion.
                If False, triggers and returns immediately.
        """
        self._set_adaptive_flag(True)
        if wait:
            await self._await_adaptive_unlock()

    def _set_adaptive_flag(self, value: bool = True):
        """Set the adaptive flag and manage the barrier state"""
        self.invoke_adaptive_step = value
        if value:
            self._adaptive_barrier.clear()

    async def _await_adaptive_unlock(self) -> Any:
        """Pause until manager completes adaptive step and returns result."""
        await self._adaptive_barrier.wait()

    @abstractmethod
    async def run(self):
        """
        Main execution method; must be implemented by subclasses.

        Drives the pipeline's control flow: calling task methods registered
        in `register_pipeline_tasks()`, and calling
        `await self.run_adaptive_step(...)` at decision points where the
        pipeline should evaluate intermediate results and optionally spawn
        child pipelines.
        """
        pass

    @abstractmethod
    def register_pipeline_tasks(self):
        """
        Register pipeline tasks; must be implemented by subclasses.

        Called once, synchronously, from `__init__` before anything else
        runs. Implementations use `@self.auto_register_task()` to bind task
        coroutines as callable methods on `self` for use in `run()`.
        """
        pass

    # Optional methods that subclasses can override
    async def get_scores_map(self):
        """
        Return a mapping of scores for this pipeline.

        Optional extension point; subclasses may override this to expose
        fitness/quality scores to external callers. Returns an empty dict
        by default.

        Returns:
            dict: Mapping of score name to value.
        """
        return {}

    @abstractmethod
    async def finalize(self):
        """
        Cleanup or finalization logic; must be implemented by subclasses.

        Called by subclass-specific adaptive logic (typically after
        spawning a child pipeline) to update or clear tracking state on the
        parent pipeline. May be a no-op for pipelines with no cleanup to
        perform.
        """
        pass

    def get_current_config_for_next_pipeline(self):
        """
        Build a default configuration dict for a follow-on pipeline.

        Optional extension point; subclasses can override this to build the
        config dict passed to `submit_child_pipeline_request()`. Returns a
        generic default pointing at the same pipeline class.

        Returns:
            dict: Configuration with at least `name` and `type` keys.
        """
        return {"name": "default_pipeline", "type": self.__class__}
