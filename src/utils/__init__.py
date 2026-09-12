"""
Utilities module for Hive Automation Bot.

Exports:
- Configuration management (ConfigManager)
- Logging setup (setup_logging, get_logger, LogContext)
- Custom exceptions (HiveBotError and subclasses)
- Constants and enums
"""

from .config import ConfigManager
from .logging_config import setup_logging, get_logger, LogContext, get_current_operation
from .errors import (
    HiveBotError,
    AuthenticationError,
    DOMError,
    ProblemExtractionError,
    EditorError,
    SolverError,
    VerdictError,
    SubmissionError,
    StateError,
    NetworkError,
    TimeoutError,
    ConfigError,
    ExtensionError,
    BrowserError,
)
from .constants import (
    VerdictType,
    WorkflowState,
    EditorType,
    ProblemStatus,
    LOGS_DIR,
    STATE_DIR,
    CONFIG_DIR,
    HIVE_BOT_HOME,
    HIVE_BOT_PROFILE,
    HIVE_BOT_STATE_FILE,
)

__all__ = [
    "ConfigManager",
    "setup_logging",
    "get_logger",
    "LogContext",
    "get_current_operation",
    "HiveBotError",
    "AuthenticationError",
    "DOMError",
    "ProblemExtractionError",
    "EditorError",
    "SolverError",
    "VerdictError",
    "SubmissionError",
    "StateError",
    "NetworkError",
    "TimeoutError",
    "ConfigError",
    "ExtensionError",
    "BrowserError",
    "VerdictType",
    "WorkflowState",
    "EditorType",
    "ProblemStatus",
    "LOGS_DIR",
    "STATE_DIR",
    "CONFIG_DIR",
    "HIVE_BOT_HOME",
    "HIVE_BOT_PROFILE",
    "HIVE_BOT_STATE_FILE",
]
