# mcp_service/app/utils/logger.py

import logging
from rich.logging import RichHandler
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import track as rich_track
from rich.theme import Theme
from rich.traceback import Traceback

# Define a custom log level for SUCCESS messages
SUCCESS_LEVEL_NUM = 25

# Add the custom level name "SUCCESS" if it doesn't exist
if logging.getLevelName(SUCCESS_LEVEL_NUM) == f"Level {SUCCESS_LEVEL_NUM}":
    logging.addLevelName(SUCCESS_LEVEL_NUM, "SUCCESS")

def success_log(self, message, *args, **kwargs):
    """Log 'message % args' with severity 'SUCCESS'."""
    if self.isEnabledFor(SUCCESS_LEVEL_NUM):
        self._log(SUCCESS_LEVEL_NUM, message, args, **kwargs)

# Add the 'success' method to the logging.Logger class if not present
if not hasattr(logging.Logger, 'success'):
    setattr(logging.Logger, 'success', success_log)


class ConsoleManager:
    """
    ConsoleManager is a singleton class that manages a Rich Console instance
    and provides a unified interface for logging and console output.
    """
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """Ensures that only one instance of ConsoleManager is created."""
        if not cls._instance:
            cls._instance = super(ConsoleManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        """Initializes the Rich Console and logger, but only once."""
        if self._initialized:
            return
        
        custom_theme = Theme({
            "logging.level.success": "bold green"
        })
        self._console = Console(theme=custom_theme)
        self._logger = self._setup_logger()
        # Ensure the logger instance has the 'success' method
        if not hasattr(self._logger, 'success'):
            setattr(self._logger, 'success', success_log.__get__(self._logger, logging.Logger))
        self._initialized = True

    def _setup_logger(self) -> logging.Logger:
        """Configures the logger with RichHandler."""
        logger = logging.getLogger("mcp_service")
        
        # Avoid adding handlers multiple times if the logger is already configured
        if logger.hasHandlers():
            return logger

        logger.setLevel(logging.INFO)
        handler = RichHandler(
            console=self._console,
            rich_tracebacks=True,
            tracebacks_show_locals=False,  # Set to False for production
            keywords=["INFO", "SUCCESS", "WARNING", "ERROR", "DEBUG", "CRITICAL"],
            show_path=False  
        )
        handler.setFormatter(logging.Formatter(fmt="%(message)s", datefmt="[%X]"))
        logger.addHandler(handler)
        return logger

    def info(self, message: str):
        """Logs an info message."""
        self._logger.info(message)

    def success(self, message: str):
        """Logs a success message using the custom 'success' level."""
        self._logger.success(message)

    def warning(self, message: str):
        """Logs a warning message."""
        self._logger.warning(message)

    def error(self, message: str):
        """Logs an error message."""
        self._logger.error(message)

    def exception(self, message: str):
        """Logs an exception message with traceback."""
        self._logger.exception(message)

    def rule(self, title: str, style: str = "cyan"):
        """Prints a horizontal rule with a title."""
        self._console.rule(f"[bold {style}]{title}[/bold {style}]", style=style)

    def display_data_as_table(self, data: dict, title: str):
        """Displays dictionary data in a formatted table within a panel."""
        table = Table(show_header=True, header_style="bold magenta", box=None, show_edge=False)
        table.add_column("Parameter", style="cyan", no_wrap=True, width=25)
        table.add_column("Value", style="white")

        for key, value in data.items():
            table.add_row(key, str(value))
        
        panel = Panel(table, title=f"[bold green]✓ {title}[/bold green]", border_style="green", expand=False)
        self._console.print(panel)

    def display_error_panel(self, title: str, error_message: str):
        """Displays an error message in a styled panel."""
        panel = Panel(error_message, title=f"[bold red]✗ {title}[/bold red]", border_style="red", expand=False)
        self._console.print(panel)

    def display_traceback(self):
        """Displays a formatted traceback for exceptions."""
        self._console.print(Traceback(show_locals=True))

    def track(self, *args, **kwargs):
        """Provides a progress bar using Rich's track function."""
        return rich_track(*args, console=self._console, **kwargs)

# Create a single, globally accessible instance of the logger
logger = ConsoleManager()


if __name__ == "__main__":
    # Example usage of the ConsoleManager
    logger.info("This is an info message.")
    logger.success("This is a success message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    
    data = {"Parameter 1": "Value 1", "Parameter 2": "Value 2"}
    logger.display_data_as_table(data, "Example Data Table")
    
    try:
        1 / 0  # This will raise an exception
    except ZeroDivisionError as e:
        logger.exception("An exception occurred")
        logger.display_traceback()
    logger.display_error_panel("Error Panel", "This is an error message displayed in a panel.")
    logger.rule("End of Example")
