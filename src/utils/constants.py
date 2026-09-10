"""
Global constants for the Hive Automation Bot.
"""

from pathlib import Path
from enum import Enum

# File paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_DIR = PROJECT_ROOT / "state"
CONFIG_DIR = PROJECT_ROOT / "config"

# Home directory paths
HOME_DIR = Path.home()
HIVE_BOT_HOME = HOME_DIR / ".hive_bot"
HIVE_BOT_PROFILE = HIVE_BOT_HOME / "chrome_profile"
HIVE_BOT_STATE_FILE = HIVE_BOT_HOME / "state.json"

# Browser defaults
DEFAULT_BROWSER_TIMEOUT_MS = 30000
DEFAULT_LOGIN_TIMEOUT_S = 60
DEFAULT_HEADLESS = False

# Browser profile
BROWSER_PROFILE_PATH = HIVE_BOT_PROFILE

# Logging
LOG_FILE = LOGS_DIR / "hive_bot.log"
MAX_LOG_SIZE_MB = 100
LOG_LEVEL = "INFO"

# Verdict types
class VerdictType(str, Enum):
    """Possible verdict types for submissions"""
    ACCEPTED = "Accepted"
    WRONG_ANSWER = "Wrong Answer"
    RUNTIME_ERROR = "Runtime Error"
    TIME_LIMIT_EXCEEDED = "Time Limit Exceeded"
    COMPILATION_ERROR = "Compilation Error"
    MEMORY_LIMIT = "Memory Limit Exceeded"
    UNKNOWN = "Unknown"


class WorkflowState(str, Enum):
    """Bot workflow states"""
    IDLE = "idle"
    LOGGING_IN = "logging_in"
    ON_PROBLEM_LIST = "on_problem_list"
    LOADING_PROBLEM = "loading_problem"
    SOLVING = "solving"
    SUBMITTING = "submitting"
    VERDICT_PARSING = "verdict_parsing"
    RETRY_WAITING = "retry_waiting"
    COMPLETE = "complete"
    ERROR = "error"


class EditorType(str, Enum):
    """Supported code editor types"""
    MONACO = "monaco"
    CODEMIRROR = "codemirror"
    ACE = "ace"
    TINYMCE = "tinymce"
    GENERIC = "generic"


class ProblemStatus(str, Enum):
    """Problem status types"""
    UNSOLVED = "unsolved"
    SOLVED = "solved"
    FAILED = "failed"
    ATTEMPTING = "attempting"


# Ensure directories exist
def ensure_directories():
    """Ensure all required directories exist"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HIVE_BOT_HOME.mkdir(parents=True, exist_ok=True)


# Call on module import
ensure_directories()
