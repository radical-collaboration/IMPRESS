from datetime import datetime
from enum import Enum

class Colors:
    """ANSI color codes for terminal output"""
    # Basic colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Styles
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class ImpressLogger:
    def __init__(self, name="ImpressManager", use_colors=True):
        self.name = name
        self.use_colors = use_colors
        
        # Color mapping for different log levels
        self.level_colors = {
            LogLevel.DEBUG: Colors.BRIGHT_BLACK,
            LogLevel.INFO: Colors.BRIGHT_CYAN,
            LogLevel.WARNING: Colors.BRIGHT_YELLOW,
            LogLevel.ERROR: Colors.BRIGHT_RED,
            LogLevel.CRITICAL: Colors.RED + Colors.BOLD
        }
        
        # Component-specific colors
        self.component_colors = {
            'pipeline': Colors.BRIGHT_GREEN,
            'adaptive': Colors.BRIGHT_MAGENTA,
            'manager': Colors.BRIGHT_BLUE,
            'workflow': Colors.CYAN,
            'task': Colors.YELLOW,
            'error': Colors.RED,
            'success': Colors.GREEN
        }

    def _get_timestamp(self):
        """Get formatted timestamp"""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _colorize(self, text, color):
        """Apply color to text if colors are enabled"""
        if not self.use_colors:
            return text
        return f"{color}{text}{Colors.RESET}"

    def _format_message(self, level, component, message, pipeline_name=None):
        """Format log message with colors and structure"""
        timestamp = self._get_timestamp()
        
        # Color the timestamp
        colored_timestamp = self._colorize(timestamp, Colors.DIM)
        
        # Color the log level
        level_color = self.level_colors.get(level, Colors.WHITE)
        colored_level = self._colorize(f"[{level.value}]", level_color)
        
        # Color the component
        component_color = self.component_colors.get(component.lower(), Colors.WHITE)
        colored_component = self._colorize(f"[{component.upper()}]", component_color)
        
        # Format pipeline name if provided
        pipeline_part = ""
        if pipeline_name:
            colored_pipeline = self._colorize(f"[{pipeline_name}]", Colors.BRIGHT_WHITE)
            pipeline_part = f" {colored_pipeline}"
        
        # Combine all parts
        return f"{colored_timestamp} {colored_level} {colored_component}{pipeline_part} {message}"

    def debug(self, message, component="manager", pipeline_name=None):
        """Log debug message"""
        formatted = self._format_message(LogLevel.DEBUG, component, message, pipeline_name)
        print(formatted)

    def info(self, message, component="manager", pipeline_name=None):
        """Log info message"""
        formatted = self._format_message(LogLevel.INFO, component, message, pipeline_name)
        print(formatted)

    def warning(self, message, component="manager", pipeline_name=None):
        """Log warning message"""
        formatted = self._format_message(LogLevel.WARNING, component, message, pipeline_name)
        print(formatted)

    def error(self, message, component="manager", pipeline_name=None):
        """Log error message"""
        formatted = self._format_message(LogLevel.ERROR, component, message, pipeline_name)
        print(formatted)

    def critical(self, message, component="manager", pipeline_name=None):
        """Log critical message"""
        formatted = self._format_message(LogLevel.CRITICAL, component, message, pipeline_name)
        print(formatted)

    def pipeline_started(self, pipeline_name):
        """Log pipeline start"""
        message = f"Pipeline started: {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}"
        self.info(message, "pipeline")

    def pipeline_completed(self, pipeline_name):
        """Log pipeline completion"""
        message = f"Pipeline completed: {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}"
        self.info(message, "pipeline")

    def pipeline_killed(self, pipeline_name):
        """Log pipeline termination"""
        message = f"Pipeline killed: {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}"
        self.warning(message, "pipeline")

    def adaptive_started(self, pipeline_name):
        """Log adaptive function start"""
        message = f"Adaptive function started for: {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}"
        self.info(message, "adaptive")

    def adaptive_completed(self, pipeline_name):
        """Log adaptive function completion"""
        message = f"Adaptive function completed for: {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}"
        self.info(message, "adaptive")

    def adaptive_failed(self, pipeline_name, error):
        """Log adaptive function failure"""
        message = f"Adaptive function failed for {self._colorize(pipeline_name, Colors.BRIGHT_WHITE)}: {error}"
        self.error(message, "adaptive")

    def child_pipeline_submitted(self, child_name, parent_name):
        """Log child pipeline submission"""
        message = f"Submitting child pipeline: {self._colorize(child_name, Colors.BRIGHT_WHITE)} from {self._colorize(parent_name, Colors.BRIGHT_WHITE)}"
        self.info(message, "manager")

    def manager_starting(self, pipeline_count):
        """Log manager startup"""
        message = f"Starting with {self._colorize(str(pipeline_count), Colors.BRIGHT_WHITE)} initial pipelines"
        self.info(message, "manager")

    def manager_exiting(self):
        """Log manager exit"""
        message = "All pipelines finished. Exiting."
        self.info(message, "manager")

    def activity_summary(self, active_pipelines, active_adaptive, buffered_pipelines):
        """Log activity summary"""
        summary = (f"Active: {self._colorize(str(active_pipelines), Colors.BRIGHT_GREEN)} pipelines, "
                  f"{self._colorize(str(active_adaptive), Colors.BRIGHT_MAGENTA)} adaptive tasks, "
                  f"{self._colorize(str(buffered_pipelines), Colors.BRIGHT_YELLOW)} buffered")
        self.debug(summary, "manager")

    def separator(self, title=None):
        """Print a decorative separator"""
        if title:
            separator = f"{'='*20} {title} {'='*20}"
        else:
            separator = "="*50
        
        colored_separator = self._colorize(separator, Colors.BRIGHT_BLUE)
        print(colored_separator)
