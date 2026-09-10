"""
Hive platform authentication and login workflow.

Handles:
- Navigation to login page
- Credential entry and submission
- Authentication verification
- Session persistence
"""

import asyncio
from typing import Optional

from playwright.async_api import Page

from src.utils import get_logger, AuthenticationError, TimeoutError, LogContext
from .credentials import Credentials

logger = get_logger(__name__)


class AuthManager:
    """
    Manages Hive platform authentication.
    
    Performs login workflow and verifies authenticated session state.
    """

    def __init__(self, page: Page, credentials: Credentials, timeout_s: int = 60):
        """
        Initialize AuthManager.
        
        Args:
            page: Playwright Page object
            credentials: Credentials instance
            timeout_s: Timeout for login operations in seconds
        """
        self.page = page
        self.credentials = credentials
        self.timeout_s = timeout_s
        self.is_authenticated = False

        logger.debug(f"AuthManager initialized for user: {credentials.username}")

    async def navigate_to_login(self) -> None:
        """
        Navigate to the login page.
        
        Raises:
            AuthenticationError: If navigation fails
        """
        with LogContext("Navigating to login page"):
            try:
                logger.info(f"Navigating to login URL: {self.credentials.login_url}")
                await self.page.goto(
                    self.credentials.login_url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_s * 1000,
                )
                logger.info("✓ Login page loaded")

            except Exception as e:
                logger.error(f"Failed to navigate to login page: {e}")
                raise AuthenticationError(f"Failed to navigate to login page: {e}") from e

    async def fill_credentials(self) -> None:
        """
        Fill username and password fields.
        
        Uses observable page state and wait conditions to identify input fields.
        Does NOT use hard-coded selectors.
        
        Raises:
            AuthenticationError: If credential fields cannot be found or filled
        """
        with LogContext("Filling login credentials"):
            try:
                # Wait for page to be interactive
                await self.page.wait_for_load_state("networkidle", timeout=self.timeout_s * 1000)
                logger.debug("Page is interactive")

                # Find username field - look for common input types
                logger.info("Looking for username input field...")
                username_fields = await self.page.query_selector_all(
                    "input[type='email'], input[type='text'], input[name*='user'], input[name*='email']"
                )

                if not username_fields:
                    raise AuthenticationError(
                        "Could not locate username input field. "
                        "Verify login page structure matches expected format."
                    )

                # Use first email/text input as username
                username_field = username_fields[0]
                await username_field.fill(self.credentials.username)
                logger.debug("✓ Username entered")

                # Find password field
                logger.info("Looking for password input field...")
                password_field = await self.page.query_selector("input[type='password']")

                if not password_field:
                    raise AuthenticationError(
                        "Could not locate password input field. "
                        "Verify login page structure matches expected format."
                    )

                await password_field.fill(self.credentials.password)
                logger.debug("✓ Password entered")

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Failed to fill credentials: {e}")
                raise AuthenticationError(f"Failed to fill login credentials: {e}") from e

    async def submit_login(self) -> None:
        """
        Submit login form.
        
        Finds and clicks the login button using observable page state.
        Does NOT use hard-coded selectors.
        
        Raises:
            AuthenticationError: If login button cannot be found or clicked
        """
        with LogContext("Submitting login form"):
            try:
                logger.info("Looking for login submit button...")

                # Find submit button - look for common button patterns
                submit_button = await self.page.query_selector(
                    "button:has-text('Log'), button:has-text('Sign'), "
                    "button:has-text('Login'), button:has-text('Submit')"
                )

                if not submit_button:
                    # Fallback: look for any button in form
                    submit_button = await self.page.query_selector("button[type='submit']")

                if not submit_button:
                    raise AuthenticationError(
                        "Could not locate login submit button. "
                        "Verify login page structure matches expected format."
                    )

                logger.info("Clicking login submit button...")
                await submit_button.click()
                logger.debug("✓ Login submitted")

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Failed to submit login: {e}")
                raise AuthenticationError(f"Failed to submit login form: {e}") from e

    async def wait_for_authentication(self) -> None:
        """
        Wait for successful authentication.
        
        Waits for observable indicators of successful login:
        - Page URL change (redirect to dashboard/problem list)
        - Presence of authenticated UI elements
        - Absence of error messages
        
        Raises:
            AuthenticationError: If authentication fails or times out
        """
        with LogContext("Waiting for authentication"):
            try:
                logger.info("Waiting for authentication to complete...")

                # Wait for URL change (indicates redirect from login page)
                await self.page.wait_for_url(
                    lambda url: self.credentials.login_url not in str(url),
                    timeout=self.timeout_s * 1000,
                )
                logger.info("✓ Redirected from login page")

                # Wait for page to stabilize
                await self.page.wait_for_load_state("networkidle", timeout=self.timeout_s * 1000)
                logger.debug("Page loaded")

                # Check for error messages
                error_elements = await self.page.query_selector_all(
                    "[class*='error'], [class*='danger'], [role='alert']"
                )

                for error_elem in error_elements:
                    error_text = await error_elem.text_content()
                    if error_text and error_text.strip():
                        raise AuthenticationError(f"Login error: {error_text.strip()}")

                self.is_authenticated = True
                logger.info("✓ Authentication successful")

            except TimeoutError as e:
                logger.error(f"Authentication timeout: {e}")
                raise AuthenticationError(f"Login timeout after {self.timeout_s}s") from e
            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Authentication failed: {e}")
                raise AuthenticationError(f"Authentication verification failed: {e}") from e

    async def verify_session(self) -> bool:
        """
        Verify that session is authenticated.
        
        Checks for authenticated state indicators on the current page.
        
        Returns:
            True if session appears to be authenticated
            
        Raises:
            AuthenticationError: If session verification fails
        """
        with LogContext("Verifying session"):
            try:
                logger.info("Verifying authenticated session...")

                # Check that we're not on login page
                current_url = self.page.url
                if self.credentials.login_url in current_url:
                    logger.warning("Still on login page - session not authenticated")
                    return False

                # Check for common authenticated UI elements
                # (e.g., user menu, logout link, profile info)
                auth_indicators = await self.page.query_selector_all(
                    "[aria-label*='profile'], [aria-label*='user'], "
                    "[aria-label*='account'], [href*='logout'], "
                    "[href*='signout'], a:has-text('Logout'), "
                    "a:has-text('Sign out')"
                )

                if auth_indicators:
                    logger.info("✓ Session verified - authenticated indicators found")
                    self.is_authenticated = True
                    return True

                logger.warning("No authenticated indicators found - may not be logged in")
                return False

            except Exception as e:
                logger.error(f"Session verification failed: {e}")
                raise AuthenticationError(f"Session verification failed: {e}") from e

    async def login(self) -> bool:
        """
        Perform complete login workflow.
        
        Steps:
        1. Navigate to login page
        2. Fill credentials
        3. Submit login
        4. Wait for authentication
        5. Verify session
        
        Returns:
            True if login successful
            
        Raises:
            AuthenticationError: If any login step fails
        """
        with LogContext(f"Login workflow for user {self.credentials.username}"):
            try:
                logger.info("Starting login workflow...")

                await self.navigate_to_login()
                await self.fill_credentials()
                await self.submit_login()
                await self.wait_for_authentication()

                if await self.verify_session():
                    logger.info("✓ Login successful")
                    self.is_authenticated = True
                    return True
                else:
                    raise AuthenticationError("Session verification failed after login")

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Login workflow failed: {e}")
                raise AuthenticationError(f"Login failed: {e}") from e
