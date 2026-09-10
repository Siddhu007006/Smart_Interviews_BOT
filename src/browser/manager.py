"""
Browser management using Playwright.

Handles:
- Browser launch with Google Chrome (channel='chrome') and persistent profile
- Persistent BrowserContext creation via launch_persistent_context
- Page object management
- Graceful shutdown and resource cleanup

Design notes:
- Playwright's launch_persistent_context() is the correct API for retaining a
  user-data directory across runs. It creates a single persistent BrowserContext
  that keeps cookies, localStorage, extension state, and installed extensions.
- launch() + new_context() creates an ephemeral incognito-style context and
  CANNOT load Chrome extensions — that approach is intentionally not used here.
- channel='chrome' tells Playwright to use the system-installed Google Chrome
  binary rather than a Playwright-managed Chromium build. Google Chrome is
  required so that the Hive Extension Detector (a real Chrome extension) can
  be installed and remain active between bot runs.
"""

import asyncio
from pathlib import Path
from typing import List, Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Playwright,
)

from src.utils import get_logger, BrowserError, LogContext

logger = get_logger(__name__)


class BrowserManager:
    """
    Manages Playwright browser lifecycle using a persistent Chrome profile.

    Key invariant: uses launch_persistent_context(user_data_dir, channel='chrome')
    so that the Hive Extension Detector extension persists across bot restarts,
    exactly as if the user had opened their regular Chrome profile.
    """

    def __init__(
        self,
        profile_path: str,
        headless: bool = False,
        timeout_ms: int = 30000,
        extra_args: Optional[List[str]] = None,
    ):
        """
        Initialize BrowserManager.

        Args:
            profile_path: Path to Chrome user data directory (persistent profile).
                          Extensions installed here survive process restarts.
            headless: Whether to run the browser in headless mode.
                      NOTE: Chrome extensions are disabled in headless mode.
                      Set headless=False when the Hive Extension Detector is required.
            timeout_ms: Default timeout for browser operations in milliseconds.
            extra_args: Additional Chrome CLI arguments to pass at launch.
                        Used during first-run extension installation to pass
                        --load-extension and --disable-extensions-except flags.
                        Leave None for all normal bot runs (extension loads
                        automatically from the persistent profile).
        """
        self.profile_path = Path(profile_path).expanduser().resolve()
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.extra_args: List[str] = extra_args or []

        # With launch_persistent_context the 'context' is returned directly —
        # there is no separate Browser object in the Playwright API.
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        if self.headless:
            logger.warning(
                "headless=True: Chrome extensions are disabled in headless mode. "
                "The Hive Extension Detector will NOT be active. "
                "Phase 1 requires headless=False."
            )

        logger.debug(
            f"BrowserManager initialized — profile: {self.profile_path}, "
            f"headless: {self.headless}"
        )

    async def launch_browser(self) -> None:
        """
        Launch Google Chrome with a persistent user profile.

        Uses playwright.chromium.launch_persistent_context() with channel='chrome'
        so that:
          1. The Hive Extension Detector (installed in this profile) is loaded.
          2. Cookies/session data survive between bot runs.
          3. No incognito isolation that would strip extensions.

        Raises:
            BrowserError: If Chrome is not found or launch fails.
        """
        with LogContext("Launching browser"):
            try:
                # Ensure the profile directory exists before launch
                self.profile_path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Profile directory ready: {self.profile_path}")

                self.playwright = await async_playwright().start()
                logger.debug("Playwright started")

                # launch_persistent_context is the correct API for:
                #   - persistent cookies/session
                #   - Chrome extension support
                #   - user-data-dir retention
                #
                # IMPORTANT: Playwright adds --disable-extensions to Chrome by default.
                # We must remove it via ignore_default_args so that extensions
                # installed in the persistent profile (including the Hive Extension
                # Detector we injected) are actually loaded and their content
                # scripts execute on Hive pages.
                launch_kwargs = dict(
                    user_data_dir=str(self.profile_path),
                    channel="chrome",       # Use installed Google Chrome binary
                    headless=self.headless,
                    ignore_default_args=["--disable-extensions"],
                )
                if self.extra_args:
                    launch_kwargs["args"] = self.extra_args
                    logger.debug(f"Extra Chrome args: {self.extra_args}")
                self.context = await self.playwright.chromium.launch_persistent_context(
                    **launch_kwargs
                )
                self.context.set_default_timeout(self.timeout_ms)


                logger.info(
                    f"✓ Chrome launched with persistent profile: {self.profile_path}"
                )

            except Exception as e:
                logger.error(f"Failed to launch Chrome: {e}")
                # Provide actionable guidance for the most common failure
                if "Executable doesn't exist" in str(e) or "chrome" in str(e).lower():
                    logger.error(
                        "Google Chrome not found. Playwright uses channel='chrome' to locate "
                        "the system-installed Google Chrome binary. "
                        "Ensure Chrome is installed at one of: "
                        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe  OR  "
                        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
                    )
                raise BrowserError(f"Browser launch failed: {e}") from e

    async def get_page(self) -> Page:
        """
        Get or create the main working page.

        With launch_persistent_context, pages are accessed directly from
        self.context rather than from a Browser object.

        Returns:
            Page object ready for navigation.

        Raises:
            BrowserError: If the browser context is not available.
        """
        if not self.context:
            raise BrowserError(
                "Browser context is not available. Call launch_browser() first."
            )

        if self.page and not self.page.is_closed():
            return self.page

        try:
            # Reuse an existing open page if available (e.g. browser restored from profile)
            existing_pages = self.context.pages
            if existing_pages:
                self.page = existing_pages[0]
                logger.debug(f"Reusing existing page: {self.page.url}")
            else:
                self.page = await self.context.new_page()
                logger.debug("New page created")

            self.page.set_default_timeout(self.timeout_ms)
            return self.page

        except Exception as e:
            logger.error(f"Failed to get/create page: {e}")
            raise BrowserError(f"Page creation failed: {e}") from e

    async def new_page(self) -> Page:
        """
        Create an additional page in the persistent context.

        Useful for DOM inspection tasks that run in a separate tab.

        Returns:
            A fresh Page object.

        Raises:
            BrowserError: If context is not available.
        """
        if not self.context:
            raise BrowserError(
                "Browser context is not available. Call launch_browser() first."
            )

        try:
            page = await self.context.new_page()
            page.set_default_timeout(self.timeout_ms)
            logger.debug("Additional page created")
            return page
        except Exception as e:
            raise BrowserError(f"New page creation failed: {e}") from e

    async def close(self) -> None:
        """Close the browser context and Playwright gracefully."""
        with LogContext("Closing browser"):
            try:
                if self.context:
                    await self.context.close()
                    self.context = None
                    logger.debug("Browser context closed")

                if self.playwright:
                    await self.playwright.stop()
                    self.playwright = None
                    logger.debug("Playwright stopped")

                self.page = None
                logger.info("Browser closed successfully")

            except Exception as e:
                logger.warning(f"Error during browser cleanup: {e}")

    async def is_connected(self) -> bool:
        """
        Check if the browser context is still alive.

        Returns:
            True if the context is available and has at least one open page.
        """
        try:
            if not self.context:
                return False
            # Accessing .pages on a closed context raises an exception
            _ = self.context.pages
            return True
        except Exception:
            return False

    async def reconnect(self) -> None:
        """
        Close and relaunch the browser.

        Called by the bot's recovery logic when is_connected() returns False.

        Raises:
            BrowserError: If relaunch fails.
        """
        with LogContext("Reconnecting browser"):
            logger.warning("Browser connection lost — attempting reconnect...")
            await self.close()
            await asyncio.sleep(1)
            await self.launch_browser()
            self.page = await self.get_page()
            logger.info("Browser reconnected successfully")

    async def __aenter__(self) -> "BrowserManager":
        """Async context manager entry — launches browser."""
        await self.launch_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit — closes browser."""
        await self.close()
        return False
