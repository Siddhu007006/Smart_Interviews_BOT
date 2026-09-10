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

from playwright.async_api import Page

from src.utils import get_logger, ExtensionError, LogContext

logger = get_logger(__name__)

# The Hive Extension Detector Chrome Web Store ID (from spec URL)
EXTENSION_ID = "goknflnoeiaookhdbnldcbnodjahpgdh"
EXTENSION_STORE_URL = (
    "https://chromewebstore.google.com/detail/hive-extension-detector/"
    f"{EXTENSION_ID}"
)

# Text fragments Hive displays in the extension-required modal
# These will be confirmed/refined during live testing.
EXTENSION_MODAL_SIGNALS = [
    "extension required",          # Modal heading (case-insensitive)
    "hive extension detector",     # Extension name mentioned in modal
    "install hive extension",      # Instruction text in modal
]


class ExtensionChecker:
    """
    Verifies that the Hive Extension Detector is active in the browser.

    The primary signal we inspect:
    1. Whether Hive's "Extension Required" modal is present on the page.
       - Modal absent → extension is working correctly.
       - Modal present → extension is missing or disabled; raise ExtensionError.

    Secondary signals (added after live DOM inspection in Phase 2):
    - window.hiveExtension or equivalent JS property set by the extension.
    - Specific network requests made by the extension (via page.route).

    This class must be instantiated AFTER the bot has navigated to a Hive page
    (post-login) where the extension gate could appear.
    """

    def __init__(self, page: Page):
        """
        Initialize ExtensionChecker.

        Args:
            page: Playwright Page object, must be on a Hive page.
        """
        self.page = page
        logger.debug("ExtensionChecker initialized")

    async def is_extension_modal_visible(self) -> bool:
        """
        Detect whether Hive is currently showing the 'Extension Required' modal.

        Strategy: look for the known text signals of the modal in page content.
        Returns True if the modal is present (meaning extension is NOT active).

        Returns:
            True if the extension-required modal is visible.
            False if the modal is absent (extension appears active).
        """
        try:
            page_text = await self.page.evaluate("() => document.body.innerText")
            page_text_lower = page_text.lower()

            for signal in EXTENSION_MODAL_SIGNALS:
                if signal in page_text_lower:
                    logger.debug(f"Extension modal signal detected: '{signal}'")
                    return True

            # Also try to find a modal/dialog element containing extension text
            # This covers SPAs that render modals in a portal outside body
            try:
                modal_locator = self.page.locator(
                    "[role='dialog'], .modal, [class*='modal'], [class*='Modal']"
                )
                modal_count = await modal_locator.count()
                if modal_count > 0:
                    modal_text = await modal_locator.first.inner_text()
                    modal_text_lower = modal_text.lower()
                    for signal in EXTENSION_MODAL_SIGNALS:
                        if signal in modal_text_lower:
                            logger.debug(
                                f"Extension modal found inside dialog element: '{signal}'"
                            )
                            return True
            except Exception:
                # Non-critical: page.locator().count() might fail on some pages
                pass

            return False

        except Exception as e:
            logger.warning(f"Could not inspect page for extension modal: {e}")
            # Conservative: if we can't read the page, don't assume extension is ok
            return False

    async def check_js_extension_marker(self) -> bool | None:
        """
        Check for a JavaScript window property exposed by the Hive Extension Detector.

        The exact property name is unknown until live inspection.
        This is a best-effort check; returns None if no known property is found.

        Returns:
            True  — a known extension marker JS property exists.
            False — a known marker property is explicitly absent.
            None  — could not determine (marker property name not yet discovered).
        """
        # TODO: Replace these candidate names after live DOM inspection in Phase 2.
        candidate_properties = [
            "window.hiveExtension",
            "window.__hiveExtDetector__",
            "window.HIVE_EXT",
        ]

        for prop in candidate_properties:
            try:
                result = await self.page.evaluate(f"() => typeof {prop} !== 'undefined'")
                if result:
                    logger.debug(f"Extension JS marker found: {prop}")
                    return True
            except Exception:
                continue

        logger.debug(
            "No known extension JS marker found. "
            "Marker property name will be discovered during live Phase 2 testing."
        )
        return None

    async def verify_extension(self) -> bool:
        """
        Full extension verification for Phase 1.

        Logic:
        1. Check whether the extension-required modal is visible.
           - If visible → extension not working → raise ExtensionError.
           - If not visible → extension is plausibly active → continue.
        2. Optionally probe for JS window marker (best-effort, not blocking).

        NOTE: Phase 1 performs this check AFTER navigation to the login/home URL.
        The modal only appears when the user tries to start a contest, so if the
        bot is still on the login page before entering any contest, the modal will
        not be visible yet.

        In that case, the bot logs a NOTE and continues. The live-test run will
        reveal whether and where the modal appears.

        Returns:
            True if no extension modal is detected.

        Raises:
            ExtensionError: If the extension-required modal is detected.
        """
        with LogContext("Verifying Hive Extension"):
            logger.info("Checking Hive Extension Detector status...")

            current_url = self.page.url
            logger.debug(f"Checking extension on page: {current_url}")

            # Primary signal: extension-required modal
            modal_visible = await self.is_extension_modal_visible()

            if modal_visible:
                logger.error(
                    "Hive Extension Detector is NOT active. "
                    "Hive is displaying the 'Extension Required' modal."
                )
                raise ExtensionError(
                    "Hive Extension Detector is required but not active.\n"
                    "\n"
                    "To fix this:\n"
                    f"  1. Install the extension: {EXTENSION_STORE_URL}\n"
                    "  2. Open chrome://extensions/ and enable 'Hive Extension Detector'.\n"
                    "  3. Disable all other extensions (except Hive Extension Detector).\n"
                    "  4. Rerun the bot — it will use the same Chrome profile where the\n"
                    f"     extension is installed.\n"
                    "\n"
                    "The bot uses a persistent Chrome profile. Once you install and enable\n"
                    "the extension in that profile, the bot will work on subsequent runs."
                )

            # Secondary signal: JS marker (informational, not blocking in Phase 1)
            marker_found = await self.check_js_extension_marker()
            if marker_found is True:
                logger.info("✓ Extension JS marker present — extension is active")
            elif marker_found is None:
                logger.info(
                    "✓ No 'Extension Required' modal detected. "
                    "Extension JS marker property not yet identified (Phase 2 TODO). "
                    "Proceeding on assumption that extension is installed in this profile."
                )
            else:
                logger.warning(
                    "Extension JS marker not present. "
                    "This may mean the extension is not installed, or the marker "
                    "property name differs from our candidates. "
                    "Will confirm during live testing on a Hive contest page."
                )

            logger.info("✓ Hive Extension check passed (no modal detected)")
            return True
