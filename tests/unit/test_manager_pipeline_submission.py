from unittest.mock import Mock, patch

# Import the classes we're testing
from impress import PipelineSetup

from .test_manager_core import MockPipeline


class TestPipelineSubmission:
    @patch("impress.impress_manager.asyncio.create_task")
    def test_submit_new_pipelines_dict(self, mock_create_task, impress_manager):
        """Test submitting new pipelines from dict"""
        impress_manager.flow = Mock()

        mock_task = Mock()
        mock_create_task.return_value = mock_task

        pipeline_setup = {
            "name": "test_pipeline",
            "type": MockPipeline,
            "config": {"param1": "value1"},
            "kwargs": {"param2": "value2"},
        }

        impress_manager.submit_new_pipelines([pipeline_setup])

        assert len(impress_manager.pipeline_tasks) == 1
        mock_create_task.assert_called_once()

    @patch("impress.impress_manager.asyncio.create_task")
    def test_submit_new_pipelines_setup_object(self, mock_create_task, impress_manager):
        """Test submitting new pipelines from PipelineSetup object"""
        impress_manager.flow = Mock()

        mock_task = Mock()
        mock_create_task.return_value = mock_task

        pipeline_setup = PipelineSetup(
            name="test_pipeline",
            type=MockPipeline,
            config={"param1": "value1"},
            kwargs={"param2": "value2"},
        )

        impress_manager.submit_new_pipelines([pipeline_setup])

        assert len(impress_manager.pipeline_tasks) == 1
        mock_create_task.assert_called_once()

    @patch("impress.impress_manager.asyncio.create_task")
    def test_submit_multiple_pipelines(self, mock_create_task, impress_manager):
        """Test submitting multiple pipelines at once"""
        impress_manager.flow = Mock()

        mock_task = Mock()
        mock_create_task.return_value = mock_task

        pipeline_setups = [
            {"name": "pipeline_1", "type": MockPipeline, "config": {}, "kwargs": {}},
            {"name": "pipeline_2", "type": MockPipeline, "config": {}, "kwargs": {}},
        ]

        impress_manager.submit_new_pipelines(pipeline_setups)

        assert len(impress_manager.pipeline_tasks) == 2
        assert mock_create_task.call_count == 2
