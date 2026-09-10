"""
Configuration management system for Hive Automation Bot.

Loads configuration from (in priority order):
1. Environment variables (highest priority)
2. User config file (~/.hive_bot/config.yaml)
3. Default bundled config (config/default_config.yaml)
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
import logging
from dotenv import load_dotenv

from .constants import CONFIG_DIR, HIVE_BOT_HOME
from .errors import ConfigError


class ConfigManager:
    """
    Manages configuration loading and validation.
    
    Priority order (highest to lowest):
    1. Environment variables
    2. User config file (~/.hive_bot/config.yaml)
    3. Default config (config/default_config.yaml)
    """

    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize ConfigManager.
        
        Args:
            config_file: Optional path to custom config file.
                        If not provided, uses default locations.
        """
        self.logger = logging.getLogger(__name__)
        self.config: Dict[str, Any] = {}
        self.config_file = config_file
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from all sources in priority order."""
        # Step 0: Load .env file into os.environ so that _load_env_vars() can read them.
        # override=False means real environment variables always win over .env values.
        dotenv_path = Path.cwd() / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path=dotenv_path, override=False)
            self.logger.debug(f"Loaded .env from {dotenv_path}")
        else:
            self.logger.debug(".env not found in CWD — relying on real env vars")

        # Start with default config
        default_config_path = CONFIG_DIR / "default_config.yaml"
        if default_config_path.exists():
            self.config = self._load_yaml(default_config_path)
            self.logger.debug(f"Loaded default config from {default_config_path}")
        else:
            self.logger.warning(f"Default config not found at {default_config_path}")

        # Override with user config if it exists
        user_config_path = HIVE_BOT_HOME / "config.yaml"
        if user_config_path.exists():
            user_config = self._load_yaml(user_config_path)
            self.config = self._deep_merge(self.config, user_config)
            self.logger.debug(f"Merged user config from {user_config_path}")

        # Override with custom config file if provided
        if self.config_file:
            custom_config_path = Path(self.config_file)
            if custom_config_path.exists():
                custom_config = self._load_yaml(custom_config_path)
                self.config = self._deep_merge(self.config, custom_config)
                self.logger.debug(f"Merged custom config from {custom_config_path}")
            else:
                raise ConfigError(f"Custom config file not found: {self.config_file}")

        # Override with environment variables (highest priority)
        self._load_env_vars()

        # Validate configuration
        self._validate_config()

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load YAML configuration file."""
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in {path}: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load config from {path}: {e}")

    def _load_env_vars(self) -> None:
        """Load and override configuration with environment variables."""
        # Authentication
        if hive_login_url := os.getenv("HIVE_LOGIN_URL"):
            if "auth" not in self.config:
                self.config["auth"] = {}
            self.config["auth"]["login_url"] = hive_login_url
            self.logger.debug("Loaded HIVE_LOGIN_URL from environment")

        if hive_username := os.getenv("HIVE_USERNAME"):
            if "auth" not in self.config:
                self.config["auth"] = {}
            self.config["auth"]["username"] = hive_username
            self.logger.debug("Loaded HIVE_USERNAME from environment")

        if hive_password := os.getenv("HIVE_PASSWORD"):
            if "auth" not in self.config:
                self.config["auth"] = {}
            self.config["auth"]["password"] = hive_password
            self.logger.debug("Loaded HIVE_PASSWORD from environment")

        # Browser settings
        if headless := os.getenv("BROWSER_HEADLESS"):
            if "browser" not in self.config:
                self.config["browser"] = {}
            self.config["browser"]["headless"] = headless.lower() in ("true", "1", "yes")
            self.logger.debug("Loaded BROWSER_HEADLESS from environment")

        if profile_path := os.getenv("BROWSER_PROFILE_PATH"):
            if "browser" not in self.config:
                self.config["browser"] = {}
            self.config["browser"]["browser_profile_path"] = profile_path
            self.logger.debug("Loaded BROWSER_PROFILE_PATH from environment")

        # AI Provider settings
        if openai_key := os.getenv("OPENAI_API_KEY"):
            if "ai_providers" not in self.config:
                self.config["ai_providers"] = {}
            if "openai" not in self.config["ai_providers"]:
                self.config["ai_providers"]["openai"] = {}
            self.config["ai_providers"]["openai"]["api_key"] = openai_key
            self.logger.debug("Loaded OPENAI_API_KEY from environment")

        if gemini_key := os.getenv("GEMINI_API_KEY"):
            if "ai_providers" not in self.config:
                self.config["ai_providers"] = {}
            if "gemini" not in self.config["ai_providers"]:
                self.config["ai_providers"]["gemini"] = {}
            self.config["ai_providers"]["gemini"]["api_key"] = gemini_key
            self.logger.debug("Loaded GEMINI_API_KEY from environment")

        if groq_key := os.getenv("GROQ_API_KEY"):
            if "ai_providers" not in self.config:
                self.config["ai_providers"] = {}
            if "groq" not in self.config["ai_providers"]:
                self.config["ai_providers"]["groq"] = {}
            self.config["ai_providers"]["groq"]["api_key"] = groq_key
            self.logger.debug("Loaded GROQ_API_KEY from environment")

    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        # At least one AI provider must be configured
        ai_providers = self.config.get("ai_providers", {})
        has_provider = False

        for provider_name in ["openai", "gemini", "groq", "ollama"]:
            if provider_name in ai_providers:
                provider_config = ai_providers[provider_name]
                if isinstance(provider_config, dict) and provider_config.get("api_key"):
                    has_provider = True
                    break

        if not has_provider:
            self.logger.warning(
                "No AI provider configured. Set one of: "
                "OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY"
            )

        # Browser profile path should be set
        if not self.get("browser.browser_profile_path"):
            self.logger.warning("Browser profile path not configured")

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge override config into base config."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key: Configuration key (e.g., "auth.username", "browser.headless")
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value if value is not None else default

    def get_required(self, key: str) -> Any:
        """
        Get required configuration value.
        
        Args:
            key: Configuration key
            
        Returns:
            Configuration value
            
        Raises:
            ConfigError: If key not found
        """
        value = self.get(key)
        if value is None:
            raise ConfigError(f"Required config value not found: {key}")
        return value

    def get_all(self) -> Dict[str, Any]:
        """Get entire configuration dictionary."""
        return self.config.copy()

    def reload(self) -> None:
        """Reload configuration from all sources."""
        self.config = {}
        self._load_config()
