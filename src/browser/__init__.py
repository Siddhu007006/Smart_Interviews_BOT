"""
Browser management module for Hive Automation Bot.

Exports:
- BrowserManager: Main browser lifecycle management
- ExtensionChecker: Hive Extension verification
"""

from .manager import BrowserManager
from .extension import ExtensionChecker

__all__ = ["BrowserManager", "ExtensionChecker"]
