import sys
from datetime import datetime
from enum import Enum


class Colors:
    """ANSI escape code constants used to colorize console log output."""

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


class LogLevel(Enum):
    """Severity levels supported by `ImpressLogger`."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ImpressLogger:
    """
    Hand-rolled, optionally colorized console logger used internally by
    `ImpressManager` and `ImpressBasePipeline`.

    Provides generic level-based logging methods (`debug`, `info`,
    `warning`, `error`, `critical`) as well as semantic convenience methods
    for specific pipeline/manager lifecycle events (e.g.
    `pipeline_started`, `adaptive_completed`). `error` and `critical`
    messages are always written to stderr; all other levels write to
    `output_stream` (default `sys.stdout`).
    """

    def __init__(self, name="ImpressManager", use_colors=True, output_stream=None):
        """
        Initialize the logger.

        Args:
            name: Logical name attached to `pipeline_log()` messages
                (typically the owning pipeline or manager name).
            use_colors: Whether to wrap output in ANSI color codes.
            output_stream: Stream to write non-error/critical messages to.
                Defaults to `sys.stdout`.
        """
        self.name = name
        self.use_colors = use_colors
        self.output_stream = output_stream or sys.stdout

        self.level_colors = {
            LogLevel.DEBUG: Colors.BRIGHT_BLACK,
            LogLevel.INFO: Colors.BRIGHT_CYAN,
            LogLevel.WARNING: Colors.BRIGHT_YELLOW,
            LogLevel.ERROR: Colors.BRIGHT_RED,
            LogLevel.CRITICAL: Colors.RED + Colors.BOLD,
        }

        self.component_colors = {
            "pipeline": Colors.BRIGHT_GREEN,
            "adaptive": Colors.BRIGHT_MAGENTA,
            "manager": Colors.BRIGHT_BLUE,
            "workflow": Colors.CYAN,
            "task": Colors.YELLOW,
            "error": Colors.RED,
            "success": Colors.GREEN,
            "stage": Colors.BRIGHT_CYAN,
            "step": Colors.CYAN,
            "resource": Colors.MAGENTA,
            "data": Colors.BRIGHT_YELLOW,
            "validation": Colors.BRIGHT_MAGENTA,
            "checkpoint": Colors.BRIGHT_GREEN,
            "metric": Colors.BRIGHT_WHITE,
        }

    def _colorize(self, text, color):
        return f"{color}{text}{Colors.RESET}" if self.use_colors else text

    def _format_message(self, level, component, message, pipeline_name=None):
        timestamp = self._colorize(
            datetime.now().strftime("%H:%M:%S.%f")[:-3], Colors.DIM
        )
        level_color = self.level_colors.get(level, Colors.WHITE)
        colored_level = self._colorize(f"[{level.value}]", level_color)

        # Handle pipeline-specific components
        if component.lower().startswith("pipeline-"):
            component_color = Colors.BRIGHT_GREEN
        else:
            component_color = self.component_colors.get(component.lower(), Colors.WHITE)

        colored_component = self._colorize(f"[{component.upper()}]", component_color)

        pipeline_part = ""
        if pipeline_name:
            pipeline_colored = self._colorize(f"[{pipeline_name}]", Colors.BRIGHT_WHITE)
            pipeline_part = f" {pipeline_colored}"

        return (
            f"{timestamp} {colored_level} {colored_component}{pipeline_part} {message}"
        )

    def _write_log(self, message, to_stderr=False):
        stream = sys.stderr if to_stderr else self.output_stream
        stream.write(message + "\n")
        stream.flush()

    def debug(self, message, component="manager", pipeline_name=None):
        """Log a DEBUG-level message.

        Args:
            message: Message text to log.
            component: Named component tag used for color-coding (e.g.
                "manager", "pipeline", "adaptive").
            pipeline_name: Optional pipeline name to include in the log line.
        """
        formatted = self._format_message(
            LogLevel.DEBUG, component, message, pipeline_name
        )
        self._write_log(formatted)

    def info(self, message, component="manager", pipeline_name=None):
        """Log an INFO-level message.

        Args:
            message: Message text to log.
            component: Named component tag used for color-coding.
            pipeline_name: Optional pipeline name to include in the log line.
        """
        formatted = self._format_message(
            LogLevel.INFO, component, message, pipeline_name
        )
        self._write_log(formatted)

    def warning(self, message, component="manager", pipeline_name=None):
        """Log a WARNING-level message.

        Args:
            message: Message text to log.
            component: Named component tag used for color-coding.
            pipeline_name: Optional pipeline name to include in the log line.
        """
        formatted = self._format_message(
            LogLevel.WARNING, component, message, pipeline_name
        )
        self._write_log(formatted)

    def error(self, message, component="manager", pipeline_name=None):
        """Log an ERROR-level message to stderr.

        Args:
            message: Message text to log.
            component: Named component tag used for color-coding.
            pipeline_name: Optional pipeline name to include in the log line.
        """
        formatted = self._format_message(
            LogLevel.ERROR, component, message, pipeline_name
        )
        self._write_log(formatted, to_stderr=True)

    def critical(self, message, component="manager", pipeline_name=None):
        """Log a CRITICAL-level message to stderr.

        Args:
            message: Message text to log.
            component: Named component tag used for color-coding.
            pipeline_name: Optional pipeline name to include in the log line.
        """
        formatted = self._format_message(
            LogLevel.CRITICAL, component, message, pipeline_name
        )
        self._write_log(formatted, to_stderr=True)

    def pipeline_started(self, pipeline_name):
        """Log that a pipeline has started.

        Args:
            pipeline_name: Name of the pipeline that started.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline started: {colored_name}"
        self.info(message, "manager")

    def pipeline_completed(self, pipeline_name):
        """Log that a pipeline has completed.

        Args:
            pipeline_name: Name of the pipeline that completed.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline completed: {colored_name}"
        self.info(message, "manager")

    def pipeline_killed(self, pipeline_name):
        """Log that a pipeline was killed via `kill_parent`.

        Args:
            pipeline_name: Name of the pipeline that was killed.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline killed: {colored_name}"
        self.warning(message, "pipeline")

    def adaptive_started(self, pipeline_name):
        """Log that a pipeline's adaptive function has started.

        Args:
            pipeline_name: Name of the pipeline whose adaptive function
                started.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function started for: {colored_name}"
        self.info(message, "adaptive")

    def adaptive_completed(self, pipeline_name):
        """Log that a pipeline's adaptive function has completed.

        Args:
            pipeline_name: Name of the pipeline whose adaptive function
                completed.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function completed for: {colored_name}"
        self.info(message, "adaptive")

    def adaptive_failed(self, pipeline_name, error):
        """Log that a pipeline's adaptive function raised an exception.

        Args:
            pipeline_name: Name of the pipeline whose adaptive function
                failed.
            error: String description of the error.
        """
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function failed for {colored_name}: {error}"
        self.error(message, "adaptive")

    def child_pipeline_submitted(self, child_name, parent_name):
        """Log that a child pipeline has been submitted by its parent.

        Args:
            child_name: Name of the newly submitted child pipeline.
            parent_name: Name of the parent pipeline that submitted it.
        """
        colored_child = self._colorize(child_name, Colors.BRIGHT_WHITE)
        colored_parent = self._colorize(parent_name, Colors.BRIGHT_WHITE)
        message = f"Submitting child pipeline: {colored_child} from {colored_parent}"
        self.info(message, "manager")

    def manager_starting(self, pipeline_count):
        """Log that the manager is starting with an initial pipeline count.

        Args:
            pipeline_count: Number of initial pipelines being submitted.
        """
        colored_count = self._colorize(str(pipeline_count), Colors.BRIGHT_WHITE)
        message = f"Starting with {colored_count} initial pipelines"
        self.info(message, "manager")

    def manager_exiting(self):
        """Log that the manager has finished and is exiting."""
        self.info("All pipelines finished. Exiting.", "manager")

    def activity_summary(self, active_pipelines, active_adaptive, buffered_pipelines):
        """Log a summary of the manager's current activity.

        Args:
            active_pipelines: Number of currently running pipeline tasks.
            active_adaptive: Number of currently running adaptive tasks.
            buffered_pipelines: Number of child pipelines buffered for
                submission.
        """
        colored_pipelines = self._colorize(str(active_pipelines), Colors.BRIGHT_GREEN)
        colored_adaptive = self._colorize(str(active_adaptive), Colors.BRIGHT_MAGENTA)
        colored_buffered = self._colorize(str(buffered_pipelines), Colors.BRIGHT_YELLOW)
        summary = (
            f"Active: {colored_pipelines} pipelines, "
            f"{colored_adaptive} adaptive tasks, "
            f"{colored_buffered} buffered"
        )
        self.debug(summary, "manager")

    def pipeline_log(self, message, level=LogLevel.INFO):
        """Log a message tagged with this logger's pipeline name.

        Used by `ImpressBasePipeline` subclasses to log from within a
        pipeline's own `run()` method, tagging output as
        `PIPELINE-<name>` rather than a manager component.

        Args:
            message: Message text to log.
            level: Severity level; ERROR/CRITICAL are written to stderr.
        """
        pipeline_component = f"PIPELINE-{self.name.upper()}"
        formatted = self._format_message(level, pipeline_component, message)
        stderr_levels = [LogLevel.ERROR, LogLevel.CRITICAL]
        self._write_log(formatted, to_stderr=level in stderr_levels)

    def separator(self, title=None):
        """Write a horizontal separator line, optionally with a title.

        Args:
            title: Optional text to center within the separator.
        """
        if title:
            separator = f"{'=' * 20} {title} {'=' * 20}"
        else:
            separator = "=" * 50
        colored_sep = self._colorize(separator, Colors.BRIGHT_BLUE)
        self._write_log(colored_sep)
