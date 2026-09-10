"""
Main HiveBot orchestrator.

Coordinates all components:
- Browser management
- Extension auto-installation (first run) / verification (subsequent runs)
- Authentication
- Session verification
- Problem list detection
- State persistence
"""

import asyncio
from pathlib import Path
from typing import Optional

from src.utils import (
    get_logger,
    LogContext,
    ConfigManager,
    HiveBotError,
    WorkflowState,
)
from src.browser import BrowserManager, ExtensionChecker, ExtensionInstaller
from src.auth import AuthManager, Credentials
from src.hive import ProblemListDetector
from src.state import StateManager, Credentials as StateCredentials

logger = get_logger(__name__)


class HiveBot:
    """
    Main bot orchestrator.

    Coordinates:
    - Browser lifecycle
    - Extension auto-install (first run only) or silent verification
    - Authentication workflow
    - Session management
    - Problem list detection
    - State persistence
    """

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.browser_manager: Optional[BrowserManager] = None
        self.auth_manager: Optional[AuthManager] = None
        self.state_manager = StateManager()
        self._installer: Optional[ExtensionInstaller] = None

        logger.info("HiveBot initialized")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, dry_run: bool = False) -> bool:
        """
        Run the complete Phase 1 workflow.

        Workflow
        --------
        1. Ensure extension is available (download + auto-install if first run,
           or silently verify on subsequent runs).
        2. Launch browser (with --load-extension on first run only).
        3. Perform login.
        4. Verify session.
        5. Detect problem list page.

        Args:
            dry_run: If True, skip actual operations (for testing).

        Returns:
            True if Phase 1 completed successfully.

        Raises:
            HiveBotError: If any critical step fails.
        """
        with LogContext("Phase 1 Workflow"):
            try:
                logger.info("Starting Phase 1 workflow...")

                # Step 1: Ensure extension is ready
                await self._ensure_extension()

                # Step 2: Perform login (browser already running after step 1)
                await self._perform_login()

                # Step 3: Verify session
                await self._verify_session()

                # Step 4: Detect problem list
                await self._detect_problem_list()

                logger.info("✓ Phase 1 workflow completed successfully")
                return True

            except HiveBotError as e:
                logger.error(f"Phase 1 workflow failed: {e}")
                await self.shutdown()
                raise

            except Exception as e:
                logger.error(f"Unexpected error in Phase 1: {e}")
                await self.shutdown()
                raise HiveBotError(f"Phase 1 failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 1 — Extension (combined download + install + verify)
    # ------------------------------------------------------------------

    async def _ensure_extension(self) -> None:
        """
        Step 1: Ensure the Hive Extension Detector is installed in the profile.

        Calls ExtensionInstaller.ensure_installed() which:
          - On first run: downloads the CRX, unpacks it, copies files into the
            profile Extensions directory, and registers it in Preferences.
            Fully automatic. Zero user interaction.
          - On subsequent runs: detects existing installation and returns
            immediately (fast path, no network call).

        After this method returns, the browser is launched normally with no
        extra CLI flags — Chrome loads the extension automatically from the
        profile.
        """
        with LogContext("Step 1: Ensure Extension"):
            try:
                profile_path = Path(
                    self.config.get_required("browser.browser_profile_path")
                ).expanduser().resolve()
                data_dir = Path(
                    self.config.get("bot.data_dir", "~/.hive_bot")
                ).expanduser().resolve()

                self._installer = ExtensionInstaller(
                    profile_path=profile_path,
                    data_dir=data_dir,
                )

                # Install (or skip if already present) — runs before Chrome opens
                self._installer.ensure_installed()

                # Launch browser — extension already in profile, no extra args
                await self._launch_browser(extra_args=None)

                # Verify extension is active on the Hive login page
                await self._verify_extension_active()

                logger.info("✓ Hive Extension is active")

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Extension ensure step failed: {e}")
                raise HiveBotError(f"Extension setup failed: {e}") from e



    async def _launch_browser(self, extra_args) -> None:
        """
        Launch (or re-launch) Chrome with the persistent profile.

        Args:
            extra_args: List of additional Chrome CLI args, or None.
                        Passed as-is to BrowserManager.
        """
        headless = self.config.get("browser.headless", False)
        timeout_ms = self.config.get("browser.timeout_default_ms", 30000)
        profile_path = self.config.get_required("browser.browser_profile_path")

        self.browser_manager = BrowserManager(
            profile_path=profile_path,
            headless=headless,
            timeout_ms=timeout_ms,
            extra_args=extra_args,
        )
        await self.browser_manager.launch_browser()
        self.state_manager.state.session.workflow_state = WorkflowState.LOGGING_IN
        logger.info("✓ Browser launched")

    async def _verify_extension_active(self) -> None:
        """
        Navigate to the Hive login page and verify no 'Extension Required'
        modal is shown.  Called after the browser is running with the extension
        permanently installed.
        """
        assert self.browser_manager is not None
        page = await self.browser_manager.get_page()
        login_url = self.config.get(
            "auth.login_url", "https://hive.smartinterviews.in/login"
        )
        logger.info(f"Navigating to login page for extension check: {login_url}")
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2.0)  # Let extension inject its signals

        checker = ExtensionChecker(page)
        if not await checker.verify_extension():
            raise HiveBotError("Hive Extension verification failed")

    # ------------------------------------------------------------------
    # Step 2 — Login
    # ------------------------------------------------------------------

    async def _perform_login(self) -> None:
        """Step 2: Perform login."""
        with LogContext("Step 2: Perform Login"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                credentials = Credentials.from_config(self.config)
                page = await self.browser_manager.get_page()
                login_timeout = self.config.get("auth.login_timeout_s", 60)
                self.auth_manager = AuthManager(page, credentials, login_timeout)

                success = await self.auth_manager.login()
                if not success:
                    # Login failed — check if the extension modal appeared
                    checker = ExtensionChecker(page)
                    modal_visible = await checker.is_extension_modal_visible()
                    if modal_visible:
                        from src.browser.extension_installer import EXTENSION_STORE_URL
                        raise HiveBotError(
                            "Login blocked by Hive: the Extension Required modal is visible.\n"
                            "The Hive Extension Detector is not enabled in the bot profile.\n"
                            f"Install it from: {EXTENSION_STORE_URL}\n"
                            "Then re-run the bot."
                        )
                    raise HiveBotError(
                        "Login failed — URL never left the login page. "
                        "Credentials may be wrong, or an invisible form validation is failing."
                    )

                logger.info("✓ Login successful")

                state_creds = StateCredentials(
                    username=credentials.username,
                    login_url=credentials.login_url,
                )
                self.state_manager.update_session(
                    authenticated=True,
                    credentials=state_creds,
                )

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Login failed: {e}")
                raise HiveBotError(f"Login failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 3 — Session verify
    # ------------------------------------------------------------------

    async def _verify_session(self) -> None:
        """Step 3: Verify authenticated session."""
        with LogContext("Step 3: Verify Session"):
            try:
                if not self.auth_manager:
                    raise HiveBotError("Auth manager not initialized")

                if not await self.auth_manager.verify_session():
                    raise HiveBotError("Session verification failed")

                logger.info("✓ Session verified")

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Session verification failed: {e}")
                raise HiveBotError(f"Session verification failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 4 — Problem list
    # ------------------------------------------------------------------

    async def _detect_problem_list(self) -> None:
        """Step 4: Detect problem list page."""
        with LogContext("Step 4: Detect Problem List"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                page = await self.browser_manager.get_page()
                detector = ProblemListDetector(page)

                if await detector.is_on_problem_list_page():
                    logger.info("✓ Problem list page detected")
                    self.state_manager.mark_on_problem_list(True)
                    self.state_manager.state.session.workflow_state = (
                        WorkflowState.ON_PROBLEM_LIST
                    )
                else:
                    logger.warning("Problem list page not detected")
                    logger.info("Attempting to navigate to problem list...")
                    # Phase 2: navigation logic goes here

            except Exception as e:
                logger.error(f"Problem list detection failed: {e}")
                raise HiveBotError(f"Problem list detection failed: {e}") from e

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Graceful shutdown of all components."""
        with LogContext("Shutdown"):
            try:
                logger.info("Shutting down bot...")

                if self.browser_manager:
                    await self.browser_manager.close()

                self.state_manager.save_state()
                logger.info("✓ Bot shutdown complete")

            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
        return False

