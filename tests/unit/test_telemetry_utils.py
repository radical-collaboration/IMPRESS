from types import SimpleNamespace
from unittest.mock import Mock

from impress.utils.logger import ImpressLogger
from impress.utils.telemetry import build_telemetry_config, make_default_subscriber


class TestBuildTelemetryConfig:
    def test_defaults(self):
        config = build_telemetry_config()

        assert config == {
            "checkpoint_path": "./telemetry/",
            "resource_poll_interval": 5.0,
        }

    def test_override_checkpoint_path_only(self):
        config = build_telemetry_config(checkpoint_path="./custom/")

        assert config["checkpoint_path"] == "./custom/"
        assert config["resource_poll_interval"] == 5.0

    def test_extra_overrides_pass_through(self):
        config = build_telemetry_config(span_processors=["x"])

        assert config["span_processors"] == ["x"]


class TestMakeDefaultSubscriber:
    def test_task_failed_routes_to_logger(self):
        logger = Mock(spec=ImpressLogger)
        subscriber = make_default_subscriber(logger)
        event = SimpleNamespace(event_type="TaskFailed", task_id="t1")

        subscriber(event)

        logger.task_event.assert_called_once_with(event)

    def test_task_completed_routes_to_logger(self):
        logger = Mock(spec=ImpressLogger)
        subscriber = make_default_subscriber(logger)
        event = SimpleNamespace(event_type="TaskCompleted", task_id="t1")

        subscriber(event)

        logger.task_event.assert_called_once_with(event)

    def test_unrelated_event_type_is_noop(self):
        logger = Mock(spec=ImpressLogger)
        subscriber = make_default_subscriber(logger)
        event = SimpleNamespace(event_type="ResourceUpdate")

        subscriber(event)

        logger.task_event.assert_not_called()
