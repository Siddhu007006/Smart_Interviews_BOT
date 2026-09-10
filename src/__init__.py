"""
Hive Automation Bot - Main source package.

Components:
- utils: Configuration, logging, errors, constants
- browser: Playwright browser management
- auth: Authentication and login
- hive: Hive platform interaction
- editor: Code editor integration (Phase 2+)
- solver: AI code solving (Phase 2+)
- state: State management and persistence
- bot: Main orchestrator
"""

__version__ = "0.1.0"
__author__ = "Hive Bot Team"

from src.bot import HiveBot
from src.utils import ConfigManager, setup_logging, get_logger

__all__ = ["HiveBot", "ConfigManager", "setup_logging", "get_logger"]
