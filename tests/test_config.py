"""
Tests for configuration system.

Tests:
- Loading default config
- Loading user config
- Environment variable override
- Configuration validation
"""

import os
import pytest
from pathlib import Path
import yaml

from src.utils import ConfigManager, ConfigError


class TestConfigManager:
    """Test ConfigManager class"""

    def test_load_default_config(self, temp_dir):
        """Test loading default configuration"""
        # Create default config
        config_dir = temp_dir / "config"
        config_dir.mkdir()

        default_config = {
            "browser": {"headless": False},
            "auth": {"login_timeout_s": 60},
        }

        default_path = config_dir / "default_config.yaml"
        with open(default_path, 'w') as f:
            yaml.dump(default_config, f)

        # Temporarily override CONFIG_DIR
        import src.utils.config
        original_config_dir = src.utils.config.CONFIG_DIR
        src.utils.config.CONFIG_DIR = config_dir

        try:
            manager = ConfigManager()
            assert manager.get("browser.headless") == False
            assert manager.get("auth.login_timeout_s") == 60
        finally:
            src.utils.config.CONFIG_DIR = original_config_dir

    def test_config_get_with_default(self, config_manager):
        """Test get() with default value"""
        value = config_manager.get("nonexistent.key", "default")
        assert value == "default"

    def test_config_get_required(self, config_manager):
        """Test get_required() raises error for missing key"""
        with pytest.raises(ConfigError):
            config_manager.get_required("nonexistent.key")

    def test_config_get_nested(self, config_manager):
        """Test get() with nested keys"""
        value = config_manager.get("browser.headless")
        assert isinstance(value, bool)

    def test_env_var_override(self, temp_dir, mock_config):
        """Test environment variable override"""
        # Create config file
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(mock_config, f)

        # Set environment variable
        os.environ["HIVE_USERNAME"] = "env_user"

        try:
            manager = ConfigManager(config_file=str(config_file))
            assert manager.get("auth.username") == "env_user"
        finally:
            del os.environ["HIVE_USERNAME"]

    def test_multiple_env_vars(self, temp_dir, mock_config):
        """Test multiple environment variable overrides"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(mock_config, f)

        os.environ["HIVE_USERNAME"] = "env_user"
        os.environ["HIVE_PASSWORD"] = "env_pass"
        os.environ["HIVE_LOGIN_URL"] = "https://env.example.com"

        try:
            manager = ConfigManager(config_file=str(config_file))
            assert manager.get("auth.username") == "env_user"
            assert manager.get("auth.password") == "env_pass"
            assert manager.get("auth.login_url") == "https://env.example.com"
        finally:
            del os.environ["HIVE_USERNAME"]
            del os.environ["HIVE_PASSWORD"]
            del os.environ["HIVE_LOGIN_URL"]

    def test_get_all_config(self, config_manager):
        """Test get_all() returns entire config"""
        config = config_manager.get_all()
        assert isinstance(config, dict)
        assert "browser" in config
        assert "auth" in config

    def test_reload_config(self, temp_dir, mock_config):
        """Test reload() refreshes configuration"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(mock_config, f)

        manager = ConfigManager(config_file=str(config_file))
        original_headless = manager.get("browser.headless")

        # Modify config file
        mock_config["browser"]["headless"] = not original_headless
        with open(config_file, 'w') as f:
            yaml.dump(mock_config, f)

        # Reload
        manager.reload()
        assert manager.get("browser.headless") == (not original_headless)


class TestCredentialsLoading:
    """Test credential loading from config"""

    def test_credentials_from_config(self, config_manager):
        """Test loading credentials from ConfigManager"""
        from src.auth import Credentials

        credentials = Credentials.from_config(config_manager)
        assert credentials.username == "test_user"
        assert credentials.password == "test_password"
        assert credentials.login_url == "https://test.example.com/login"

    def test_credentials_missing_username(self, temp_dir):
        """Test error when username missing"""
        from src.auth import Credentials

        config = {"auth": {"password": "pass", "login_url": "url"}}
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump(config, f)

        manager = ConfigManager(config_file=str(config_file))

        with pytest.raises(ConfigError):
            Credentials.from_config(manager)


class TestPhase3SolverConfig:
    """Test Phase 3 solver and provider model configuration."""

    def test_default_solver_settings(self, temp_dir):
        """Test default language and max attempts from default config"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump({}, f)

        manager = ConfigManager(config_file=str(config_file))
        assert manager.get("solver.default_language") == "C++"
        assert manager.get("solver.max_attempts") == 5

    def test_env_override_solver_settings(self, temp_dir):
        """Test overriding solver settings via environment variables"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump({}, f)

        os.environ["DEFAULT_LANGUAGE"] = "Python"
        os.environ["MAX_ATTEMPTS"] = "3"

        try:
            manager = ConfigManager(config_file=str(config_file))
            assert manager.get("solver.default_language") == "Python"
            assert manager.get("solver.max_attempts") == 3
        finally:
            del os.environ["DEFAULT_LANGUAGE"]
            del os.environ["MAX_ATTEMPTS"]

    def test_provider_models_loaded_from_env(self, temp_dir):
        """Test loading provider models dynamically from environment"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump({}, f)

        os.environ["GROQ_MODEL"] = "test-groq-model"
        os.environ["GEMINI_MODEL"] = "test-gemini-model"

        try:
            manager = ConfigManager(config_file=str(config_file))
            assert manager.get_provider_model("groq") == "test-groq-model"
            assert manager.get_provider_model("gemini") == "test-gemini-model"
        finally:
            del os.environ["GROQ_MODEL"]
            del os.environ["GEMINI_MODEL"]

    def test_get_provider_model_missing_fails_loudly(self, temp_dir):
        """Test that missing provider model raises ConfigError with zero fallback strings"""
        config_file = temp_dir / "config.yaml"
        with open(config_file, 'w') as f:
            yaml.dump({}, f)

        manager = ConfigManager(config_file=str(config_file))
        with pytest.raises(ConfigError) as exc_info:
            manager.get_provider_model("groq")

        assert "Missing required model ID for provider 'groq'" in str(exc_info.value)
        assert "GROQ_MODEL" in str(exc_info.value)
