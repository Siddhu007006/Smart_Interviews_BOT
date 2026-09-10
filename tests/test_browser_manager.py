"""
Tests for browser management.

Tests:
- Browser initialization
- Browser launch/close
- Context creation
- Page management
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

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

        assert manager.profile_path == temp_dir / "profile"
        assert manager.headless == False
        assert manager.timeout_ms == 30000
        assert manager.browser is None
        assert manager.context is None

    @pytest.mark.asyncio
    async def test_browser_launch(self, temp_dir, mock_playwright):
        """Test browser launch"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.__aenter__ = AsyncMock(
                return_value=mock_playwright
            )
            mock_ap.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_browser = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)

            await manager.launch_browser()

            assert manager.browser is mock_browser
            assert manager.playwright is mock_playwright

    @pytest.mark.asyncio
    async def test_browser_launch_failure(self, temp_dir):
        """Test browser launch failure"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.side_effect = Exception("Launch failed")

            with pytest.raises(BrowserError):
                await manager.launch_browser()

    @pytest.mark.asyncio
    async def test_create_context(self, temp_dir, mock_browser):
        """Test context creation"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))
        manager.browser = mock_browser

        mock_context = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        await manager.create_context()

        assert manager.context is mock_context
        mock_context.set_default_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_context_without_browser(self, temp_dir):
        """Test error when creating context without browser"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with pytest.raises(BrowserError):
            await manager.create_context()

    @pytest.mark.asyncio
    async def test_new_page(self, temp_dir):
        """Test creating new page"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        manager.context = mock_context

        page = await manager.new_page()

        assert page is mock_page
        mock_page.set_default_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_page(self, temp_dir):
        """Test getting page"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        mock_context = AsyncMock()
        mock_page = AsyncMock()
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
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()

        manager.page = mock_page
        manager.context = mock_context
        manager.browser = mock_browser
        manager.playwright = mock_playwright

        await manager.close()

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

        assert manager.page is None
        assert manager.context is None
        assert manager.browser is None
        assert manager.playwright is None

    @pytest.mark.asyncio
    async def test_is_connected_true(self, temp_dir, mock_browser):
        """Test connection check when connected"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))
        manager.browser = mock_browser
        mock_browser.version = "120.0"

        connected = await manager.is_connected()
        assert connected == True

    @pytest.mark.asyncio
    async def test_is_connected_false_no_browser(self, temp_dir):
        """Test connection check when no browser"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        connected = await manager.is_connected()
        assert connected == False

    @pytest.mark.asyncio
    async def test_context_manager(self, temp_dir, mock_playwright):
        """Test async context manager"""
        manager = BrowserManager(profile_path=str(temp_dir / "profile"))

        with patch('src.browser.manager.async_playwright') as mock_ap:
            mock_ap.return_value.__aenter__ = AsyncMock(
                return_value=mock_playwright
            )
            mock_ap.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_browser = AsyncMock()
            mock_context = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_browser.new_context = AsyncMock(return_value=mock_context)

            async with manager as mgr:
                assert mgr is manager
                assert manager.browser is mock_browser
                assert manager.context is mock_context

            # Verify cleanup was called
            mock_context.close.assert_called_once()
            mock_browser.close.assert_called_once()
