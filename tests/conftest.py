# tests/conftest.py
import functools
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest

from impress import ImpressManager


def pytest_sessionfinish(session, exitstatus):
    root = Path(__file__).parent
    for pycache_dir in root.rglob("__pycache__"):
        shutil.rmtree(pycache_dir)


class MockWorkflowEngine:
    """Mock workflow engine.

    `function_task` mirrors asyncflow's decorator closely enough for the
    manager's contract: it accepts both `@flow.function_task` and
    `@flow.function_task(backend=...)`, and swallows the call-time
    `workflow_id`. It runs the body on the loop, so tests that care *where*
    a body runs use `LocalBackendFlow` in test_manager_adaptive_logic instead.

    Two details of asyncflow's own shape matter, because `PipelineSetup`
    tells a declared task from a bare function by them
    (`workflow_manager.py:559-562`):

    - the mark goes on the function being decorated, not on the wrapper,
      so a decorated body carries it too and `functools.wraps` copies it;
    - the wrapper is a plain `def` returning an awaitable, not an
      `async def`. A mock that returned a coroutine function would be
      rejected as a bare function by the validator it is meant to satisfy.
    """

    def __init__(self):
        self.registered = []

    def function_task(self, possible_func=None, *, backend=None, **_kwargs):
        def decorator(func):
            # getattr, because a Mock has no __name__.
            self.registered.append((getattr(func, "__name__", "task"), backend))

            # On `func`, as asyncflow does, before wraps copies it over.
            func.__task_description__ = {}

            @functools.wraps(func)
            def flow_task(*args, workflow_id=None, **kwargs):
                return func(*args, **kwargs)

            return flow_task

        if callable(possible_func):
            return decorator(possible_func)
        return decorator

    async def shutdown(self, skip_execution_backend=False):
        pass


class RecordingEngine(MockWorkflowEngine):
    """Mock engine that counts shutdown() calls.

    The manager must never call shutdown() on an injected flow — teardown
    belongs to whoever created it.
    """

    def __init__(self):
        super().__init__()
        self.shutdown_calls = 0

    async def shutdown(self, skip_execution_backend=False):
        self.shutdown_calls += 1


@pytest.fixture
def mock_flow():
    """Mock workflow engine injected into the manager"""
    return MockWorkflowEngine()


@pytest.fixture
def impress_manager(mock_flow):
    """Create an ImpressManager instance for testing"""
    manager = ImpressManager(mock_flow, use_colors=False)
    manager.logger = Mock()  # Mock the logger
    return manager
