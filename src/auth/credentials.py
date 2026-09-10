"""
Credentials management for Hive Authentication.

Handles loading and validation of credentials from configuration.
"""

from dataclasses import dataclass
from typing import Optional

from src.utils import get_logger, ConfigManager, ConfigError

logger = get_logger(__name__)


@dataclass
class Credentials:
    """
    User credentials for Hive platform.
    
    Attributes:
        username: Hive account username or email
        password: Hive account password
        login_url: URL of Hive login page
    """

    username: str
    password: str
    login_url: str

    def __repr__(self) -> str:
        """Secure representation without exposing password."""
        return (
            f"Credentials(username={self.username!r}, "
            f"login_url={self.login_url!r})"
        )

    @classmethod
    def from_config(cls, config_manager: ConfigManager) -> "Credentials":
        """
        Load credentials from configuration manager.
        
        Args:
            config_manager: ConfigManager instance
            
        Returns:
            Credentials instance
            
        Raises:
            ConfigError: If required credentials are missing
        """
        logger.debug("Loading credentials from configuration")

        # Load username
        username = config_manager.get("auth.username")
        if not username:
            raise ConfigError(
                "Username not configured. Set HIVE_USERNAME environment variable "
                "or configure auth.username in config file"
            )

        # Load password
        password = config_manager.get("auth.password")
        if not password:
            raise ConfigError(
                "Password not configured. Set HIVE_PASSWORD environment variable "
                "or configure auth.password in config file"
            )

        # Load login URL
        login_url = config_manager.get("auth.login_url")
        if not login_url:
            raise ConfigError(
                "Login URL not configured. Set HIVE_LOGIN_URL environment variable "
                "or configure auth.login_url in config file"
            )

        logger.info(f"Credentials loaded for user: {username}")

        return cls(
            username=username,
            password=password,
            login_url=login_url,
        )

    @classmethod
    def from_env_vars(
        cls,
        username: Optional[str] = None,
        password: Optional[str] = None,
        login_url: Optional[str] = None,
    ) -> "Credentials":
        """
        Create credentials from explicit parameters.
        
        Args:
            username: Hive username
            password: Hive password
            login_url: Hive login URL
            
        Returns:
            Credentials instance
            
        Raises:
            ConfigError: If any required field is missing
        """
        if not username:
            raise ConfigError("Username is required")
        if not password:
            raise ConfigError("Password is required")
        if not login_url:
            raise ConfigError("Login URL is required")

        logger.info(f"Credentials created for user: {username}")

        return cls(
            username=username,
            password=password,
            login_url=login_url,
        )
