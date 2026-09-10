"""
Authentication module for Hive Automation Bot.

Exports:
- Credentials: User credential management
- AuthManager: Hive platform authentication and login
"""

from .credentials import Credentials
from .login import AuthManager

__all__ = ["Credentials", "AuthManager"]
