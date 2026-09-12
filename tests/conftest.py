"""
Pytest configuration and shared fixtures for tests.

Provides:
- Temporary directories
- Mock configuration
- Mock page objects (for unit tests)
- Test data
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock
import yaml

from src.utils import ConfigManager, HIVE_BOT_HOME


@pytest.fixture
def temp_dir():
    """Provide temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config():
    """Provide mock configuration"""
    config_data = {
        "browser": {
            "headless": False,
            "browser_profile_path": "/tmp/test_profile",
            "timeout_default_ms": 30000,
        },
        "auth": {
            "login_timeout_s": 60,
            "username": "test_user",
            "password": "test_password",
            "login_url": "https://test.example.com/login",
        },
        "state": {
            "persistence_file": "/tmp/state.json",
            "auto_checkpoint": True,
        },
        "logging": {
            "level": "DEBUG",
            "log_file": "/tmp/hive_bot.log",
        },
    }

    return config_data


@pytest.fixture
def config_manager(temp_dir, mock_config):
    """Provide ConfigManager with test configuration"""
    # Create config file
    config_file = temp_dir / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(mock_config, f)

    return ConfigManager(config_file=str(config_file), load_env_file=False)


@pytest.fixture
def mock_page():
    """Provide mock Playwright Page object"""
    page = AsyncMock()
    page.url = "https://test.example.com"
    page.title = AsyncMock(return_value="Test Page")
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock()
    page.close = AsyncMock()
    page.content = AsyncMock(return_value="<html></html>")
    page.screenshot = AsyncMock()

    return page


@pytest.fixture
def mock_browser():
    """Provide mock Playwright Browser object"""
    browser = AsyncMock()
    browser.version = "120.0"
    browser.new_context = AsyncMock()
    browser.close = AsyncMock()

    return browser


@pytest.fixture
def mock_playwright():
    """Provide mock Playwright object"""
    playwright = AsyncMock()
    playwright.chromium.launch = AsyncMock()
    playwright.start = AsyncMock()
    playwright.stop = AsyncMock()

    return playwright


@pytest.fixture
def mock_element():
    """Provide mock ElementHandle"""
    element = AsyncMock()
    element.text_content = AsyncMock(return_value="Test Content")
    element.get_attribute = AsyncMock(return_value="test-value")
    element.is_visible = AsyncMock(return_value=True)
    element.is_enabled = AsyncMock(return_value=True)
    element.click = AsyncMock()
    element.fill = AsyncMock()

    return element


@pytest.fixture
def test_credentials():
    """Provide test credentials"""
    return {
        "username": "test_user",
        "password": "test_password",
        "login_url": "https://test.example.com/login",
    }


@pytest.fixture(autouse=True)
def cleanup(monkeypatch):
    """Cleanup and isolate environment before and after each test"""
    test_env_vars = [
        "HIVE_USERNAME", "HIVE_PASSWORD", "HIVE_LOGIN_URL", "HIVE_CONTEST_URL",
        "BROWSER_HEADLESS", "BROWSER_PROFILE_PATH", "DEFAULT_LANGUAGE", "MAX_ATTEMPTS",
        "GROQ_MODEL", "GEMINI_MODEL",
        "GROQ_API_KEY", "GEMINI_API_KEY"
    ]
    for var in test_env_vars:
        monkeypatch.delenv(var, raising=False)
    yield


# Mark tests as async
pytest.mark.asyncio = pytest.mark.asyncio
