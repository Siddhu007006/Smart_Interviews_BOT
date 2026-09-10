"""
Browser management module for Hive Automation Bot.

Exports:
- BrowserManager: Main browser lifecycle management
- ExtensionChecker: Hive Extension verification
- ExtensionInstaller: Automated first-run extension download + install
"""

from .manager import BrowserManager
from .extension import ExtensionChecker
from .extension_installer import ExtensionInstaller, EXTENSION_ID

__all__ = ["BrowserManager", "ExtensionChecker", "ExtensionInstaller", "EXTENSION_ID"]
