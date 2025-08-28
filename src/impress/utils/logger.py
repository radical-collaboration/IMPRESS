import sys
from datetime import datetime
from enum import Enum


class Colors:
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
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ImpressLogger:
    def __init__(self, name="ImpressManager", use_colors=True, output_stream=None):
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
        formatted = self._format_message(
            LogLevel.DEBUG, component, message, pipeline_name
        )
        self._write_log(formatted)

    def info(self, message, component="manager", pipeline_name=None):
        formatted = self._format_message(
            LogLevel.INFO, component, message, pipeline_name
        )
        self._write_log(formatted)

    def warning(self, message, component="manager", pipeline_name=None):
        formatted = self._format_message(
            LogLevel.WARNING, component, message, pipeline_name
        )
        self._write_log(formatted)

    def error(self, message, component="manager", pipeline_name=None):
        formatted = self._format_message(
            LogLevel.ERROR, component, message, pipeline_name
        )
        self._write_log(formatted, to_stderr=True)

    def critical(self, message, component="manager", pipeline_name=None):
        formatted = self._format_message(
            LogLevel.CRITICAL, component, message, pipeline_name
        )
        self._write_log(formatted, to_stderr=True)

    def pipeline_started(self, pipeline_name):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline started: {colored_name}"
        self.info(message, "manager")

    def pipeline_completed(self, pipeline_name):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline completed: {colored_name}"
        self.info(message, "manager")

    def pipeline_killed(self, pipeline_name):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Pipeline killed: {colored_name}"
        self.warning(message, "pipeline")

    def adaptive_started(self, pipeline_name):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function started for: {colored_name}"
        self.info(message, "adaptive")

    def adaptive_completed(self, pipeline_name):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function completed for: {colored_name}"
        self.info(message, "adaptive")

    def adaptive_failed(self, pipeline_name, error):
        colored_name = self._colorize(pipeline_name, Colors.BRIGHT_WHITE)
        message = f"Adaptive function failed for {colored_name}: {error}"
        self.error(message, "adaptive")

    def child_pipeline_submitted(self, child_name, parent_name):
        colored_child = self._colorize(child_name, Colors.BRIGHT_WHITE)
        colored_parent = self._colorize(parent_name, Colors.BRIGHT_WHITE)
        message = f"Submitting child pipeline: {colored_child} from {colored_parent}"
        self.info(message, "manager")

    def manager_starting(self, pipeline_count):
        colored_count = self._colorize(str(pipeline_count), Colors.BRIGHT_WHITE)
        message = f"Starting with {colored_count} initial pipelines"
        self.info(message, "manager")

    def manager_exiting(self):
        self.info("All pipelines finished. Exiting.", "manager")

    def activity_summary(self, active_pipelines, active_adaptive, buffered_pipelines):
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
        pipeline_component = f"PIPELINE-{self.name.upper()}"
        formatted = self._format_message(level, pipeline_component, message)
        stderr_levels = [LogLevel.ERROR, LogLevel.CRITICAL]
        self._write_log(formatted, to_stderr=level in stderr_levels)

    def separator(self, title=None):
        if title:
            separator = f"{'=' * 20} {title} {'=' * 20}"
        else:
            separator = "=" * 50
        colored_sep = self._colorize(separator, Colors.BRIGHT_BLUE)
        self._write_log(colored_sep)
