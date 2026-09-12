"""
Hive Extension verification.

The Hive Extension Detector is a genuine Chrome extension that Hive's platform
requires to be installed and enabled before a contest can be started.

This module checks whether the extension is active by inspecting observable
browser signals, and detects the Hive-displayed modal that appears when the
extension requirement is not met.

Design principle:
- We do NOT spoof, bypass, or fake extension presence.
- We do NOT inject fake window properties or modify HTTP headers.
- The correct approach is: open Chrome with a persistent profile that has the
  extension genuinely installed, then verify it is working.

Phase 1 implementation:
- Navigate to login URL.
- After login lands on a Hive page, check whether the extension-required modal
  is visible.
- If the modal is NOT visible → extension is active.
- If the modal IS visible → log diagnostic guidance and raise ExtensionError
  so the user knows exactly what to fix before re-running the bot.
- Actual window/DOM signals exposed by the extension will be discovered during
  live testing and documented for Phase 2 hardening.
"""

import asyncio
import json
from pathlib import Path
from typing import List, Optional
from playwright.async_api import Page

from src.utils import get_logger, ExtensionError, LogContext

logger = get_logger(__name__)

# The Hive Extension Detector Chrome Web Store ID
EXTENSION_ID = "goknflnoeiaookhdbnldcbnodjahpgdh"
EXTENSION_STORE_URL = (
    "https://chromewebstore.google.com/detail/hive-extension-detector/"
    f"{EXTENSION_ID}"
)

# Text fragments Hive displays in the extension-required modal
EXTENSION_MODAL_SIGNALS = [
    "extension required",          # Modal heading (case-insensitive)
    "hive extension detector",     # Extension name mentioned in modal
    "install hive extension",      # Instruction text in modal
]


class ExtensionChecker:
    """
    Verifies that the Hive Extension Detector is active in the browser using
    a strict multi-tier verification hierarchy:

    Tier 1: Browser / Profile verification
            -> Verify Hive Extension Detector ID exists in the persistent Chrome profile
    Tier 2: Extension runtime verification
            -> Verify actual extension service worker / background is active in browser context
    Tier 3: Hive platform verification
            -> Verify <app-extension-blocker> is absent or dismissed on the contest page
    Tier 4: Only then proceed to Continue Contest.
    """

    def __init__(self, page: Page, profile_path: Optional[Path] = None):
        """
        Initialize ExtensionChecker.

        Args:
            page: Playwright Page object.
            profile_path: Optional path to Chrome profile root directory.
        """
        self.page = page
        self.profile_path = (
            Path(profile_path).expanduser().resolve() if profile_path else None
        )
        logger.debug("ExtensionChecker initialized")

    def verify_profile_installation(self, profile_path: Optional[Path] = None) -> bool:
        """
        Tier 1: Profile verification.
        Verify that the Hive Extension Detector files exist in the Chrome profile.

        Args:
            profile_path: Path to Chrome profile (defaults to self.profile_path).

        Returns:
            True if extension files or preferences record exists in profile.
        """
        target_profile = (
            Path(profile_path).expanduser().resolve()
            if profile_path
            else self.profile_path
        )
        if not target_profile:
            logger.warning("No profile_path provided for Tier 1 profile verification")
            return False

        ext_dir = target_profile / "Default" / "Extensions" / EXTENSION_ID
        if ext_dir.exists() and any(ext_dir.iterdir()):
            logger.info(f"✓ Tier 1 Passed: Extension ID '{EXTENSION_ID}' found in profile extensions at {ext_dir}")
            return True

        # Also inspect Preferences JSON as a secondary check
        prefs_path = target_profile / "Default" / "Preferences"
        if prefs_path.exists():
            try:
                with open(prefs_path, "r", encoding="utf-8") as f:
                    prefs = json.load(f)
                settings = prefs.get("extensions", {}).get("settings", {})
                if EXTENSION_ID in settings:
                    logger.info(f"✓ Tier 1 Passed: Extension ID '{EXTENSION_ID}' registered in Chrome Preferences")
                    return True
            except Exception as e:
                logger.debug(f"Could not read profile preferences: {e}")

        logger.warning(f"Tier 1 Failed: Extension ID '{EXTENSION_ID}' not found in profile: {target_profile}")
        return False

    async def verify_runtime_active(self, retries: int = 3, retry_delay_s: float = 1.0) -> bool:
        """
        Tier 2: Extension runtime verification.
        Verify that the extension's service worker or background page is running
        in the current Playwright BrowserContext.

        Args:
            retries: Number of attempts to observe the running extension process.
            retry_delay_s: Delay between attempts.

        Returns:
            True if extension runtime is actively running.
        """
        context = self.page.context
        for attempt in range(1, retries + 1):
            # Check active service workers (Manifest V3)
            workers = context.service_workers
            for sw in workers:
                if EXTENSION_ID in sw.url:
                    logger.info(f"✓ Tier 2 Passed: Extension service worker active: {sw.url}")
                    return True

            # Check active background pages (Manifest V2 / fallbacks)
            bg_pages = context.background_pages
            for bp in bg_pages:
                if EXTENSION_ID in bp.url:
                    logger.info(f"✓ Tier 2 Passed: Extension background page active: {bp.url}")
                    return True

            if attempt < retries:
                logger.debug(f"Tier 2 check attempt {attempt}/{retries} pending; waiting {retry_delay_s}s...")
                await asyncio.sleep(retry_delay_s)

        logger.warning(f"Tier 2 Failed: No active service worker or background page found for extension '{EXTENSION_ID}'.")
        return False

    async def is_extension_modal_visible(self) -> bool:
        """
        Detect whether Hive is currently showing the 'Extension Required' modal or blocker.
        """
        try:
            # Check for <app-extension-blocker> custom element
            blocker = self.page.locator("app-extension-blocker")
            if await blocker.count() > 0:
                is_vis = await blocker.first.is_visible()
                if is_vis:
                    raw_text = None
                    text = ""
                    try:
                        raw_text = await blocker.first.inner_text()
                        text = str(raw_text).strip() if raw_text else ""
                    except Exception:
                        pass

                    # On real Hive, the Angular component stays in DOM but clears its inner
                    # content (inner_text == "") once the genuine extension is verified.
                    if raw_text is not None and text == "":
                        logger.debug("app-extension-blocker is present but empty (dismissed)")
                    else:
                        logger.debug(f"app-extension-blocker is present and visible with content: {repr(text[:50])}")
                        return True

            # Also check for overlay or modal text signals
            page_text = await self.page.evaluate("() => document.body ? document.body.innerText : ''")
            page_text_lower = page_text.lower()
            for signal in EXTENSION_MODAL_SIGNALS:
                if signal in page_text_lower:
                    logger.debug(f"Extension modal signal detected: '{signal}'")
                    return True

            return False
        except Exception as e:
            logger.warning(f"Could not inspect page for extension modal: {e}")
            return False

    async def verify_hive_blocker_dismissed(self, timeout_s: float = 10.0) -> bool:
        """
        Tier 3: Hive platform verification.
        Verify that <app-extension-blocker> is absent or dismissed on the contest page.

        Args:
            timeout_s: Maximum seconds to wait for Hive Angular app to dismiss blocker.

        Returns:
            True if blocker is absent or dismissed; False if blocker persists.
        """
        poll_interval = 0.5
        elapsed = 0.0
        while elapsed < timeout_s:
            modal_visible = await self.is_extension_modal_visible()
            if not modal_visible:
                logger.info("✓ Tier 3 Passed: Hive extension blocker is absent or dismissed.")
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        logger.error(f"Tier 3 Failed: Hive extension blocker remained visible after {timeout_s}s.")
        return False

    async def verify_extension_ready(
        self,
        profile_path: Optional[Path] = None,
        timeout_s: float = 10.0
    ) -> bool:
        """
        Execute full 3-tier verification hierarchy in accordance with project requirements:
        1. Browser/profile verification (ID exists in profile)
        2. Extension runtime verification (actual extension running in context)
        3. Hive verification (<app-extension-blocker> absent/dismissed)

        Returns:
            True if all 3 tiers pass.

        Raises:
            ExtensionError: If any tier fails, detailing exact diagnosis.
        """
        with LogContext("Verifying Extension Ready (Multi-Tier Hierarchy)"):
            # Tier 1: Browser / profile verification
            profile = profile_path or self.profile_path
            if profile and not self.verify_profile_installation(profile):
                raise ExtensionError(
                    f"Tier 1 Failure: Hive Extension Detector ('{EXTENSION_ID}') is not installed in "
                    f"the persistent Chrome profile at '{profile}'."
                )

            # Tier 2: Extension runtime verification
            runtime_ok = await self.verify_runtime_active()
            if not runtime_ok:
                raise ExtensionError(
                    f"Tier 2 Failure: Hive Extension Detector ('{EXTENSION_ID}') is present in profile, "
                    f"but its service worker/process is not active in the browser runtime."
                )

            # Tier 3: Hive platform verification
            blocker_dismissed = await self.verify_hive_blocker_dismissed(timeout_s=timeout_s)
            if not blocker_dismissed:
                raise ExtensionError(
                    "Tier 3 Failure: Hive platform has not unblocked the contest. "
                    "<app-extension-blocker> is actively preventing navigation."
                )

            logger.info("✓ All 3 extension verification tiers passed successfully.")
            return True

    async def verify_extension(self) -> bool:
        """
        Backwards-compatible wrapper for Phase 1 calls.
        """
        modal_visible = await self.is_extension_modal_visible()
        if modal_visible:
            raise ExtensionError(
                "Hive Extension Detector is required but not active.\n"
                f"Store URL: {EXTENSION_STORE_URL}"
            )
        return True
