"""
Tests for browser management.

Tests:
- Browser initialization
- Browser launch/close with persistent context
- Context creation and timeouts
- Page management
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from src.browser import BrowserManager
from src.utils import BrowserError


class TestBrowserManager:
    """Test BrowserManager class"""

    @pytest.mark.asyncio
    async def test_browser_manager_init(self, temp_dir):
        """Test BrowserManager initialization"""
        manager = BrowserManager(
            profile_path=str(temp_dir / "profile"),
            headless=False,
            timeout_ms=30000,
        )

        assert manager.profile_path == (temp_dir / "profile").resolve()
        assert manager.headless is False
        assert manager.timeout_ms == 30000
        assert manager.context is None

    @pytest.mark.asyncio
    async def test_browser_launch(self, temp_dir, mock_playwright):
        """Test browser launch with persistent context"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_playwright)
            mock_context = AsyncMock()
            mock_context.set_default_timeout = MagicMock()
            mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

            await manager.launch_browser()

            assert manager.context is mock_context
            assert manager.playwright is mock_playwright
            mock_context.set_default_timeout.assert_called_once_with(30000)

    @pytest.mark.asyncio
    async def test_browser_launch_failure(self, temp_dir):
        """Test browser launch failure"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.side_effect = Exception("Launch failed")

            with pytest.raises(BrowserError):
                await manager.launch_browser()

    @pytest.mark.asyncio
    async def test_new_page(self, temp_dir):
        """Test creating new page"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.set_default_timeout = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        manager.context = mock_context

        page = await manager.new_page()

        assert page is mock_page
        mock_page.set_default_timeout.assert_called_once_with(manager.timeout_ms)

    @pytest.mark.asyncio
    async def test_get_page(self, temp_dir):
        """Test getting page"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.pages = []
        mock_context.new_page = AsyncMock(return_value=mock_page)
        manager.context = mock_context

        # First call creates page
        page1 = await manager.get_page()
        assert page1 is mock_page

        # Second call returns same page
        page2 = await manager.get_page()
        assert page2 is page1

    @pytest.mark.asyncio
    async def test_browser_close(self, temp_dir):
        """Test browser cleanup"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_playwright = AsyncMock()

        manager.page = mock_page
        manager.context = mock_context
        manager.playwright = mock_playwright

        await manager.close()

        mock_context.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

        assert manager.page is None
        assert manager.context is None
        assert manager.playwright is None

    @pytest.mark.asyncio
    async def test_is_connected_true(self, temp_dir):
        """Test connection check when connected"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))
        mock_context = AsyncMock()
        mock_context.pages = [AsyncMock()]
        manager.context = mock_context

        connected = await manager.is_connected()
        assert connected is True

    @pytest.mark.asyncio
    async def test_is_connected_false_no_browser(self, temp_dir):
        """Test connection check when no browser"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        connected = await manager.is_connected()
        assert connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir, mock_playwright):
        """Test async context manager"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_playwright)
            mock_context = AsyncMock()
            mock_context.set_default_timeout = MagicMock()
            mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

            async with manager as mgr:
                assert mgr is manager
                assert manager.context is mock_context

            mock_context.close.assert_called_once()
            mock_playwright.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_launch_channel_none_uses_chromium(self, temp_dir, mock_playwright):
        """Test that channel=None does not pass channel to launch_persistent_context (Chromium default)"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"), channel=None)

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_playwright)
            mock_context = AsyncMock()
            mock_context.set_default_timeout = MagicMock()
            mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

            await manager.launch_browser()

            call_kwargs = mock_playwright.chromium.launch_persistent_context.call_args.kwargs
            assert "channel" not in call_kwargs

    @pytest.mark.asyncio
    async def test_browser_launch_channel_chrome_passes_channel(self, temp_dir, mock_playwright):
        """Test that channel='chrome' explicitly passes channel='chrome' to launch_persistent_context"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"), channel="chrome")

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_playwright)
            mock_context = AsyncMock()
            mock_context.set_default_timeout = MagicMock()
            mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

            await manager.launch_browser()

            call_kwargs = mock_playwright.chromium.launch_persistent_context.call_args.kwargs
            assert call_kwargs.get("channel") == "chrome"

    @pytest.mark.asyncio
    async def test_get_runtime_info(self, temp_dir, mock_playwright):
        """Test get_runtime_info method returns runtime dictionary"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"), channel=None)
        mock_playwright.chromium.executable_path = "C:/fake/path/chrome.exe"
        manager.playwright = mock_playwright

        info = await manager.get_runtime_info()
        assert info["requested_channel"] is None
        assert info["executable_path"] == "C:/fake/path/chrome.exe"
        assert "user_agent" in info
        assert "profile_path" in info

