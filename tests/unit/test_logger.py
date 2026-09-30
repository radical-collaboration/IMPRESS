import io
import sys

from impress.utils.logger import ImpressLogger, LogLevel


class TestImpressLoggerInit:
    def test_default_init(self):
        logger = ImpressLogger()
        assert logger.name == "ImpressManager"
        assert logger.use_colors is True
        assert logger.output_stream is sys.stdout
        assert logger.min_level == LogLevel.DEBUG

    def test_custom_stream(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream)
        assert logger.output_stream is stream

    def test_custom_min_level(self):
        logger = ImpressLogger(min_level=LogLevel.WARNING)
        assert logger.min_level == LogLevel.WARNING

    def test_custom_name(self):
        logger = ImpressLogger(name="my_pipeline")
        assert logger.name == "my_pipeline"


class TestLogLevelFiltering:
    def test_is_enabled_at_exact_level(self):
        logger = ImpressLogger(min_level=LogLevel.INFO)
        assert logger._is_enabled(LogLevel.INFO) is True

    def test_is_enabled_above_min(self):
        logger = ImpressLogger(min_level=LogLevel.INFO)
        assert logger._is_enabled(LogLevel.WARNING) is True
        assert logger._is_enabled(LogLevel.ERROR) is True
        assert logger._is_enabled(LogLevel.CRITICAL) is True

    def test_is_disabled_below_min(self):
        logger = ImpressLogger(min_level=LogLevel.INFO)
        assert logger._is_enabled(LogLevel.DEBUG) is False

    def test_debug_suppressed_at_info_level(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, min_level=LogLevel.INFO, use_colors=False
        )
        logger.debug("should not appear")
        assert stream.getvalue() == ""

    def test_info_written_at_info_level(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, min_level=LogLevel.INFO, use_colors=False
        )
        logger.info("should appear")
        assert "should appear" in stream.getvalue()

    def test_warning_suppressed_below_min(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, min_level=LogLevel.ERROR, use_colors=False
        )
        logger.warning("should not appear")
        assert stream.getvalue() == ""

    def test_all_levels_write_at_debug_min(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, min_level=LogLevel.DEBUG, use_colors=False
        )
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        output = stream.getvalue()
        assert "d" in output
        assert "i" in output
        assert "w" in output
        assert "e" in output
        assert "c" in output

    def test_critical_only_at_critical_min(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, min_level=LogLevel.CRITICAL, use_colors=False
        )
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        output = stream.getvalue()
        assert "d" not in output
        assert "i" not in output
        assert "w" not in output
        assert "e" not in output
        assert "c" in output


class TestOutputStreamRespected:
    def test_error_writes_to_output_stream_not_stderr(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.error("an error")
        assert "an error" in stream.getvalue()

    def test_critical_writes_to_output_stream(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.critical("critical msg")
        assert "critical msg" in stream.getvalue()

    def test_custom_stream_receives_all_output(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.info("info line")
        logger.error("error line")
        logger.warning("warn line")
        output = stream.getvalue()
        assert "info line" in output
        assert "error line" in output
        assert "warn line" in output


class TestColors:
    def test_no_ansi_when_colors_off(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.info("hello")
        assert "\033[" not in stream.getvalue()

    def test_ansi_present_when_colors_on(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=True)
        logger.info("hello")
        assert "\033[" in stream.getvalue()

    def test_colorize_returns_plain_when_off(self):
        logger = ImpressLogger(use_colors=False)
        result = logger._colorize("text", "\033[31m")
        assert result == "text"

    def test_colorize_wraps_when_on(self):
        logger = ImpressLogger(use_colors=True)
        result = logger._colorize("text", "\033[31m")
        assert result.startswith("\033[31m")
        assert "text" in result


class TestHighLevelMethods:
    def _make_logger(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        return logger, stream

    def test_pipeline_started(self):
        logger, stream = self._make_logger()
        logger.pipeline_started("my_pipe")
        assert "my_pipe" in stream.getvalue()

    def test_pipeline_completed(self):
        logger, stream = self._make_logger()
        logger.pipeline_completed("my_pipe")
        assert "my_pipe" in stream.getvalue()

    def test_pipeline_failed(self):
        logger, stream = self._make_logger()
        logger.pipeline_failed("bad_pipe", ValueError("oops"))
        out = stream.getvalue()
        assert "bad_pipe" in out
        assert "oops" in out

    def test_pipeline_killed(self):
        logger, stream = self._make_logger()
        logger.pipeline_killed("dead_pipe")
        assert "dead_pipe" in stream.getvalue()

    def test_adaptive_started(self):
        logger, stream = self._make_logger()
        logger.adaptive_started("p1")
        assert "p1" in stream.getvalue()

    def test_adaptive_completed(self):
        logger, stream = self._make_logger()
        logger.adaptive_completed("p1")
        assert "p1" in stream.getvalue()

    def test_adaptive_failed(self):
        logger, stream = self._make_logger()
        logger.adaptive_failed("p1", "bad fn")
        out = stream.getvalue()
        assert "p1" in out
        assert "bad fn" in out

    def test_child_pipeline_submitted(self):
        logger, stream = self._make_logger()
        logger.child_pipeline_submitted("child", "parent")
        out = stream.getvalue()
        assert "child" in out
        assert "parent" in out

    def test_manager_starting(self):
        logger, stream = self._make_logger()
        logger.manager_starting(5)
        assert "5" in stream.getvalue()

    def test_manager_exiting(self):
        logger, stream = self._make_logger()
        logger.manager_exiting()
        assert stream.getvalue() != ""

    def test_activity_summary_suppressed_at_info(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, use_colors=False, min_level=LogLevel.INFO
        )
        logger.activity_summary(3, 1, 2)
        assert stream.getvalue() == ""  # activity_summary is DEBUG level

    def test_activity_summary_written_at_debug(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            output_stream=stream, use_colors=False, min_level=LogLevel.DEBUG
        )
        logger.activity_summary(3, 1, 2)
        out = stream.getvalue()
        assert "3" in out


class TestPipelineLog:
    def test_pipeline_log_default_info(self):
        stream = io.StringIO()
        logger = ImpressLogger("pipe1", output_stream=stream, use_colors=False)
        logger.pipeline_log("step done")
        assert "step done" in stream.getvalue()

    def test_pipeline_log_suppressed_below_min(self):
        stream = io.StringIO()
        logger = ImpressLogger(
            "pipe1", output_stream=stream, use_colors=False, min_level=LogLevel.WARNING
        )
        logger.pipeline_log("step done", level=LogLevel.INFO)
        assert stream.getvalue() == ""

    def test_pipeline_log_debug_level(self):
        stream = io.StringIO()
        logger = ImpressLogger("pipe1", output_stream=stream, use_colors=False)
        logger.pipeline_log("debug step", level=LogLevel.DEBUG)
        assert "debug step" in stream.getvalue()

    def test_pipeline_log_includes_pipeline_name_component(self):
        stream = io.StringIO()
        logger = ImpressLogger("mypipe", output_stream=stream, use_colors=False)
        logger.pipeline_log("event")
        assert "PIPELINE-MYPIPE" in stream.getvalue()


class TestSeparator:
    def test_separator_no_title(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.separator()
        assert "=" in stream.getvalue()

    def test_separator_with_title(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.separator("HELLO WORLD")
        assert "HELLO WORLD" in stream.getvalue()

    def test_separator_ends_with_newline(self):
        stream = io.StringIO()
        logger = ImpressLogger(output_stream=stream, use_colors=False)
        logger.separator()
        assert stream.getvalue().endswith("\n")
