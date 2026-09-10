"""
Main HiveBot orchestrator.

Coordinates all components:
- Browser management
- Authentication
- Session verification
- Problem list detection
- State persistence
"""

import asyncio
from typing import Optional

from src.utils import (
    get_logger,
    LogContext,
    ConfigManager,
    HiveBotError,
    WorkflowState,
)
from src.browser import BrowserManager, ExtensionChecker
from src.auth import AuthManager, Credentials
from src.hive import ProblemListDetector
from src.state import StateManager, Credentials as StateCredentials

logger = get_logger(__name__)


class HiveBot:
    """
    Main bot orchestrator.
    
    Coordinates:
    - Browser lifecycle
    - Authentication workflow
    - Session management
    - Problem list detection
    - State persistence
    """

    def __init__(self, config_manager: ConfigManager):
        """
        Initialize HiveBot.
        
        Args:
            config_manager: ConfigManager instance
        """
        self.config = config_manager
        self.browser_manager: Optional[BrowserManager] = None
        self.auth_manager: Optional[AuthManager] = None
        self.state_manager = StateManager()

        logger.info("HiveBot initialized")

    async def run(self, dry_run: bool = False) -> bool:
        """
        Run complete Phase 1 workflow.
        
        Workflow:
        1. Launch browser with persistent profile
        2. Verify Hive Extension
        3. Perform login
        4. Verify session
        5. Detect problem list page
        
        Args:
            dry_run: If True, skip actual operations (for testing)
            
        Returns:
            True if Phase 1 completed successfully
            
        Raises:
            HiveBotError: If any critical step fails
        """
        with LogContext("Phase 1 Workflow"):
            try:
                logger.info("Starting Phase 1 workflow...")

                # Step 1: Launch browser
                await self._launch_browser()

                # Step 2: Verify extension
                await self._verify_extension()

                # Step 3: Perform login
                await self._perform_login()

                # Step 4: Verify session
                await self._verify_session()

                # Step 5: Detect problem list
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

    async def _launch_browser(self) -> None:
        """Step 1: Launch browser with persistent profile"""
        with LogContext("Step 1: Launch Browser"):
            try:
                profile_path = self.config.get_required("browser.browser_profile_path")
                headless = self.config.get("browser.headless", False)
                timeout_ms = self.config.get("browser.timeout_default_ms", 30000)

                self.browser_manager = BrowserManager(
                    profile_path=profile_path,
                    headless=headless,
                    timeout_ms=timeout_ms,
                )

                await self.browser_manager.launch_browser()

                logger.info("✓ Browser launched with persistent profile")
                self.state_manager.state.session.workflow_state = WorkflowState.LOGGING_IN

            except Exception as e:
                logger.error(f"Browser launch failed: {e}")
                raise HiveBotError(f"Failed to launch browser: {e}") from e

    async def _verify_extension(self) -> None:
        """Step 2: Verify Hive Extension Detector"""
        with LogContext("Step 2: Verify Hive Extension"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                page = await self.browser_manager.get_page()
                checker = ExtensionChecker(page)

                if not await checker.verify_extension():
                    raise HiveBotError("Hive Extension verification failed")

                logger.info("✓ Hive Extension verified")

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Extension verification failed: {e}")
                raise HiveBotError(f"Extension verification failed: {e}") from e

    async def _perform_login(self) -> None:
        """Step 3: Perform login"""
        with LogContext("Step 3: Perform Login"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                # Load credentials
                credentials = Credentials.from_config(self.config)

                # Create auth manager
                page = await self.browser_manager.get_page()
                login_timeout = self.config.get("auth.login_timeout_s", 60)
                self.auth_manager = AuthManager(page, credentials, login_timeout)

                # Perform login
                if not await self.auth_manager.login():
                    raise HiveBotError("Login failed")

                logger.info("✓ Login successful")

                # Update state
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

    async def _verify_session(self) -> None:
        """Step 4: Verify authenticated session"""
        with LogContext("Step 4: Verify Session"):
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

    async def _detect_problem_list(self) -> None:
        """Step 5: Detect problem list page"""
        with LogContext("Step 5: Detect Problem List"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                page = await self.browser_manager.get_page()
                detector = ProblemListDetector(page)

                if await detector.is_on_problem_list_page():
                    logger.info("✓ Problem list page detected")
                    self.state_manager.mark_on_problem_list(True)
                    self.state_manager.state.session.workflow_state = WorkflowState.ON_PROBLEM_LIST
                else:
                    logger.warning("Problem list page not detected")
                    logger.info("Attempting to navigate to problem list...")
                    # Phase 2: Will add navigation logic

            except Exception as e:
                logger.error(f"Problem list detection failed: {e}")
                raise HiveBotError(f"Problem list detection failed: {e}") from e

    async def shutdown(self) -> None:
        """Graceful shutdown of all components"""
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
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.shutdown()
        return False
