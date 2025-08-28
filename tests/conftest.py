# tests/conftest.py
import pytest
import shutil
from pathlib import Path

from unittest.mock import Mock
from impress import ImpressManager


def pytest_sessionfinish(session, exitstatus):
    root = Path(__file__).parent
    for pycache_dir in root.rglob("__pycache__"):
        shutil.rmtree(pycache_dir)


@pytest.fixture
def mock_execution_backend():
    """Mock execution backend"""
    return Mock()


@pytest.fixture
def impress_manager(mock_execution_backend):
    """Create an ImpressManager instance for testing"""
    manager = ImpressManager(mock_execution_backend, use_colors=False)
    manager.logger = Mock()  # Mock the logger
    return manager
