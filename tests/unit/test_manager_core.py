from unittest.mock import Mock

import pytest

# Import the classes we're testing
from impress import ImpressBasePipeline, PipelineSetup
from impress.impress_manager import ImpressManager


class MockPipeline(ImpressBasePipeline):
    """Mock pipeline for testing"""

    def __init__(self, name: str, flow=None, **kwargs):
        self.name = name
        self.flow = flow
        self.kwargs = kwargs
        self.invoke_adaptive_step = False
        self.kill_parent = False
        self._adaptive_fn = None
        self._adaptive_barrier = None
        self._child_pipeline_request = None
        self._run_called = False
        self._run_duration = 0.1

    async def run(self):
        """Mock run method"""
        self._run_called = True
        return "completed"

    def get_child_pipeline_request(self):
        """Mock method to return child pipeline config"""
        if self._child_pipeline_request:
            request = self._child_pipeline_request
            self._child_pipeline_request = None
            return request
        return None

    def register_pipeline_tasks(self, flow):
        """Implementation of abstract method - no-op for testing"""
        pass


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


@pytest.fixture
def sample_pipeline_setup():
    """Sample pipeline setup"""
    return PipelineSetup(
        name="test_pipeline",
        type=MockPipeline,
        config={"param1": "value1"},
        kwargs={"param2": "value2"},
        adaptive_fn=None,
    )


class TestImpressManagerCore:
    def test_init(self, mock_execution_backend):
        """Test ImpressManager initialization"""
        manager = ImpressManager(mock_execution_backend, use_colors=True)

        assert manager.execution_backend == mock_execution_backend
        assert isinstance(manager.pipeline_tasks, dict)
        assert isinstance(manager.adaptive_tasks, dict)
        assert isinstance(manager.new_pipeline_buffer, list)
        assert len(manager.pipeline_tasks) == 0
        assert len(manager.adaptive_tasks) == 0
        assert len(manager.new_pipeline_buffer) == 0

    def test_normalize_pipeline_setup_dict(self, impress_manager):
        """Test normalizing dict to PipelineSetup"""
        setup_dict = {
            "name": "test",
            "type": MockPipeline,
            "config": {"key": "value"},
            "kwargs": {"kwarg": "value"},
            "adaptive_fn": None,
        }

        normalized = impress_manager._normalize_pipeline_setup(setup_dict)

        assert isinstance(normalized, PipelineSetup)
        assert normalized.name == "test"
        assert normalized.type == MockPipeline
        assert normalized.config == {"key": "value"}
        assert normalized.kwargs == {"kwargs": {"kwarg": "value"}}

    def test_normalize_pipeline_setup_object(
        self, impress_manager, sample_pipeline_setup
    ):
        """Test normalizing PipelineSetup object (no change)"""
        normalized = impress_manager._normalize_pipeline_setup(sample_pipeline_setup)

        assert normalized is sample_pipeline_setup

    def test_normalize_pipeline_setup_invalid(self, impress_manager):
        """Test normalizing invalid input raises ValueError"""
        with pytest.raises(ValueError, match="Expected dict or PipelineSetup"):
            impress_manager._normalize_pipeline_setup("invalid")
