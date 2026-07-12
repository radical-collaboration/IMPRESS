import io
from types import SimpleNamespace

from impress.utils.logger import ImpressLogger


def _make_logger():
    stream = io.StringIO()
    return ImpressLogger(use_colors=False, output_stream=stream), stream


class TestLoggerTaskEvent:
    def test_task_failed_written_via_error(self, capsys):
        logger, stream = _make_logger()
        event = SimpleNamespace(
            event_type="TaskFailed",
            task_id="task.0007",
            workflow_id="p1",
            error_type="RuntimeError",
        )

        logger.task_event(event)

        captured = capsys.readouterr()
        assert stream.getvalue() == ""  # error() writes to stderr, not output_stream
        assert "task.0007" in captured.err
        assert "p1" in captured.err
        assert "RuntimeError" in captured.err
        assert "[ERROR]" in captured.err

    def test_task_completed_written_via_debug(self):
        logger, stream = _make_logger()
        event = SimpleNamespace(
            event_type="TaskCompleted",
            task_id="task.0007",
            workflow_id="p1",
            duration_seconds=0.25,
        )

        logger.task_event(event)

        output = stream.getvalue()
        assert "task.0007" in output
        assert "p1" in output
        assert "250ms" in output
        assert "[DEBUG]" in output

    def test_unrelated_event_type_is_noop(self):
        logger, stream = _make_logger()
        event = SimpleNamespace(event_type="ResourceUpdate")

        logger.task_event(event)

        assert stream.getvalue() == ""
