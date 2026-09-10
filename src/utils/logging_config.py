"""
Centralized logging configuration for Hive Automation Bot.

Provides:
- Console output (INFO level by default)
- File output (logs/hive_bot.log)
- Structured format with timestamps, levels, module names
- Context manager for operation tracking (LogContext)
"""

import logging
import logging.handlers
import sys
import io
from pathlib import Path
from contextvars import ContextVar
from typing import Optional, Dict, Any

from .constants import LOGS_DIR, LOG_FILE, LOG_LEVEL

# Context variable for operation tracking
_operation_context: ContextVar[Optional[str]] = ContextVar('operation', default=None)


def setup_logging(
    level: str = LOG_LEVEL,
    log_file: Optional[Path] = LOG_FILE,
    max_bytes: int = 100 * 1024 * 1024,  # 100MB
    backup_count: int = 3,
) -> logging.Logger:
    """
    Setup structured logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        max_bytes: Maximum size of log file before rotation
        backup_count: Number of backup log files to keep
        
    Returns:
        Configured root logger
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level.upper())

    # Clear existing handlers
    root_logger.handlers = []

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler — ensure UTF-8 encoding so Unicode chars (e.g. ✓) render
    # correctly on Windows regardless of the active code page (cp1252, etc.).
    # reconfigure() is the safe way in Python 3.7+ and works whether stdout is
    # a real file, a pipe, or a shell-owned stream.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # Non-critical: fallback to default encoding
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(level.upper())
    console_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # File gets everything
        file_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(file_handler)

    return root_logger


class LogContext:
    """
    Context manager for operation tracking in logs.
    
    Usage:
        with LogContext("Solving problem #123"):
            logger.info("Starting solver...")
            # All logs within this context will reference the operation
    """

    def __init__(self, operation: str):
        """
        Initialize LogContext.
        
        Args:
            operation: Description of the operation being tracked
        """
        self.operation = operation
        self.token = None

    def __enter__(self):
        """Enter context and set operation."""
        self.token = _operation_context.set(self.operation)
        logger = logging.getLogger(__name__)
        logger.debug(f"Entering: {self.operation}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and clear operation."""
        logger = logging.getLogger(__name__)
        if exc_type:
            logger.error(f"Error in {self.operation}: {exc_val}")
        else:
            logger.debug(f"Completed: {self.operation}")
        _operation_context.reset(self.token)
        return False


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def get_current_operation() -> Optional[str]:
    """Get the current operation context."""
    return _operation_context.get()


class ContextualFormatter(logging.Formatter):
    """
    Custom formatter that includes operation context in log messages.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with operation context."""
        operation = get_current_operation()
        if operation:
            record.msg = f"[{operation}] {record.msg}"
        return super().format(record)


# Initialize logging on module import
setup_logging()
