# tests/conftest.py
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
    """Mock workflow engine"""

    async def shutdown(self, skip_execution_backend=False):
        pass


class RecordingEngine(MockWorkflowEngine):
    """Mock engine that counts shutdown() calls.

    The manager must never call shutdown() on an injected flow — teardown
    belongs to whoever created it.
    """

    def __init__(self):
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
