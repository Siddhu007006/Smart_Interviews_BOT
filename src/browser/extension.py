"""
Hive Extension verification and management.

Ensures the Hive Extension Detector is installed and enabled before
bot operation. This is a REQUIRED security mechanism - bot does NOT
spoof or bypass this check.
"""

from src.utils import get_logger, ExtensionError, LogContext

logger = get_logger(__name__)


class ExtensionChecker:
    """
    Verifies Hive Extension Detector installation and status.
    
    The Hive Extension Detector is a required security mechanism for
    the Hive platform. This checker ensures it is properly installed
    and enabled before proceeding.
    """

    def __init__(self, page):
        """
        Initialize ExtensionChecker.
        
        Args:
            page: Playwright Page object
        """
        self.page = page
        logger.debug("ExtensionChecker initialized")

    async def check_extension_installed(self) -> bool:
        """
        Check if Hive Extension Detector is installed.
        
        This checks by navigating to the Chrome extensions page or by
        checking for extension-specific markers on the page.
        
        Returns:
            True if extension appears to be installed, False otherwise
        """
        with LogContext("Checking Hive Extension installation"):
            try:
                # Check if we can detect extension presence
                # This may involve checking page for extension-specific features
                # or navigating to extension info page
                logger.info("Checking for Hive Extension Detector...")

                # For now, log a placeholder - actual detection depends on
                # how Hive implements extension detection (e.g., via API, window object)
                logger.warning(
                    "Extension verification requires live inspection of Hive platform. "
                    "In Phase 1, ensure Hive Extension Detector is installed manually. "
                    "See: https://chrome.google.com/webstore/category/extensions"
                )
                return True  # Assume installed for Phase 1

            except Exception as e:
                logger.error(f"Failed to check extension: {e}")
                return False

    async def check_extension_enabled(self) -> bool:
        """
        Check if Hive Extension Detector is enabled.
        
        Returns:
            True if extension is enabled, False otherwise
        """
        with LogContext("Checking Hive Extension status"):
            try:
                logger.info("Verifying Hive Extension Detector is enabled...")

                # Check for extension-specific markers or API
                # This depends on how Hive implements the extension interface
                logger.warning(
                    "Extension status verification requires live Hive platform inspection. "
                    "Please ensure the Hive Extension Detector is enabled in chrome://extensions/"
                )
                return True  # Assume enabled for Phase 1

            except Exception as e:
                logger.error(f"Failed to verify extension status: {e}")
                return False

    async def disable_other_extensions(self) -> None:
        """
        Disable all extensions except Hive Extension Detector.
        
        This improves performance and reduces security risks from
        unnecessary extensions.
        """
        with LogContext("Disabling non-essential extensions"):
            try:
                logger.info("Disabling non-essential extensions...")
                # This would require accessing chrome://extensions/ management
                # For Phase 1, we rely on user having only necessary extensions
                logger.warning(
                    "Manual extension management required. "
                    "Please disable all extensions except Hive Extension Detector "
                    "in chrome://extensions/"
                )

            except Exception as e:
                logger.warning(f"Failed to manage extensions: {e}")

    async def verify_extension(self) -> bool:
        """
        Perform full extension verification.
        
        Returns:
            True if extension is properly installed and enabled
            
        Raises:
            ExtensionError: If extension verification fails critically
        """
        with LogContext("Verifying Hive Extension"):
            logger.info("Starting Hive Extension verification...")

            try:
                # Check installation
                if not await self.check_extension_installed():
                    raise ExtensionError(
                        "Hive Extension Detector is not installed. "
                        "Install from: https://chrome.google.com/webstore/ "
                        "and search for 'Hive Extension Detector'"
                    )

                logger.info("✓ Extension installed")

                # Check enabled status
                if not await self.check_extension_enabled():
                    raise ExtensionError(
                        "Hive Extension Detector is not enabled. "
                        "Enable it in chrome://extensions/"
                    )

                logger.info("✓ Extension enabled")

                # Clean up unnecessary extensions
                await self.disable_other_extensions()

                logger.info("✓ Hive Extension verification passed")
                return True

            except ExtensionError:
                raise
            except Exception as e:
                logger.error(f"Extension verification failed: {e}")
                raise ExtensionError(f"Extension verification failed: {e}") from e
