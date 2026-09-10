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

        Uses character-by-character typing so Angular's reactive form model
        receives real keyboard events and updates its internal state.
        Playwright's fill() sets the DOM value directly without triggering
        Angular's (input)/(change) event handlers, leaving the form model empty.

        Raises:
            AuthenticationError: If credential fields cannot be found or filled
        """
        with LogContext("Filling login credentials"):
            try:
                # Wait for Angular to render the login form.
                # domcontentloaded fires once the HTML shell is parsed; we then
                # wait for an actual input element to be visible on screen.
                await self.page.wait_for_load_state("domcontentloaded", timeout=self.timeout_s * 1000)

                # Wait for first visible text/email input (Angular form rendered)
                await self.page.wait_for_selector(
                    "input[type='email'], input[type='text'], input[type='username']",
                    state="visible",
                    timeout=self.timeout_s * 1000,
                )
                logger.debug("Login form is visible")

                # --- USERNAME ---
                logger.info("Looking for username input field...")
                username_field = await self.page.query_selector(
                    "input[type='email'], input[type='text'], input[name*='user'], input[name*='email']"
                )

                if not username_field:
                    raise AuthenticationError(
                        "Could not locate username input field. "
                        "Verify login page structure matches expected format."
                    )

                # Click to focus, then type char-by-char so Angular's synthetic
                # event system registers each keystroke and updates the form model.
                await username_field.click()
                await username_field.type(self.credentials.username, delay=40)
                # Tab to blur the field — Angular marks it as 'touched' and may
                # reveal the password field if it was conditionally hidden.
                await self.page.keyboard.press("Tab")
                await asyncio.sleep(0.3)
                logger.debug("✓ Username entered")

                # --- PASSWORD ---
                logger.info("Looking for password input field...")
                await self.page.wait_for_selector(
                    "input[type='password']", state="visible", timeout=10000
                )
                password_field = await self.page.query_selector("input[type='password']")

                if not password_field:
                    raise AuthenticationError(
                        "Could not locate password input field. "
                        "Verify login page structure matches expected format."
                    )

                await password_field.click()
                await password_field.type(self.credentials.password, delay=40)
                await asyncio.sleep(0.2)
                logger.debug("✓ Password entered")

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Failed to fill credentials: {e}")
                raise AuthenticationError(f"Failed to fill login credentials: {e}") from e


    async def submit_login(self) -> None:
        """
        Submit the Angular login form.

        The Hive Login button is a standard button without type='submit'.
        We use text-based selectors first to reliably find the visible button.

        Raises:
            AuthenticationError: If login button cannot be found or clicked
        """
        with LogContext("Submitting login form"):
            try:
                logger.info("Looking for login submit button...")

                # Hive login button has text "Login" — prioritise text-based
                # selectors to avoid matching hidden/disabled sibling elements.
                button_selectors = [
                    "button:has-text('Login')",
                    "button:has-text('Log In')",
                    "button:has-text('Sign In')",
                    "button:has-text('Sign in')",
                    "button:has-text('Submit')",
                    "button[type='submit']",
                    "input[type='submit']",
                ]

                submit_button = None
                for selector in button_selectors:
                    # Use page.locator() so we can filter to visible only
                    locator = self.page.locator(selector).first
                    try:
                        # Wait up to 3s for it to appear
                        await locator.wait_for(state="visible", timeout=3000)
                        submit_button = locator
                        logger.debug(f"Found visible submit button via: {selector}")
                        break
                    except Exception:
                        continue

                if not submit_button:
                    raise AuthenticationError(
                        "Could not locate login submit button. "
                        "Verify login page structure matches expected format."
                    )

                # Wait up to 5s for button to become enabled (Angular validation)
                for attempt in range(10):
                    is_disabled = await submit_button.get_attribute("disabled")
                    aria_disabled = await submit_button.get_attribute("aria-disabled")
                    if is_disabled is None and aria_disabled not in ("true", ""):
                        break
                    logger.debug(
                        f"Submit button disabled (attempt {attempt+1}/10) — "
                        "waiting for Angular form validation..."
                    )
                    await asyncio.sleep(0.5)

                logger.info("Clicking login submit button...")
                await submit_button.click()
                logger.debug("Login submitted")

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Failed to submit login: {e}")
                raise AuthenticationError(f"Failed to submit login form: {e}") from e




    async def wait_for_authentication(self) -> None:
        """
        Wait for successful authentication.

        Hive is a SPA that uses client-side routing (pushState) after login.
        We poll the page URL until it leaves the /login path. Also checks for
        visible error messages on the page during polling so we can fail fast
        instead of waiting the full timeout on wrong credentials.

        Raises:
            AuthenticationError: If authentication fails or times out
        """
        with LogContext("Waiting for authentication"):
            try:
                logger.info("Waiting for authentication to complete...")

                from urllib.parse import urlparse

                login_path = urlparse(self.credentials.login_url).path.rstrip("/")
                deadline_s = self.timeout_s
                poll_interval_s = 0.5
                elapsed = 0.0

                while elapsed < deadline_s:
                    current_url = self.page.url
                    if current_url not in ("about:blank", ""):
                        current_path = urlparse(current_url).path.rstrip("/")
                        if current_path != login_path:
                            logger.info(f"Redirected from login → {current_url}")
                            break

                    # Check for error messages on the page every 2s
                    if elapsed > 0 and elapsed % 2.0 < poll_interval_s:
                        try:
                            body = await self.page.evaluate(
                                "() => document.body.innerText"
                            )
                            body_lower = body.lower()
                            failure_phrases = [
                                "invalid credentials", "incorrect password",
                                "user not found", "login failed",
                                "authentication failed", "wrong password",
                                "invalid username", "invalid password",
                                "incorrect username", "account not found",
                                "no account", "user does not exist",
                            ]
                            for phrase in failure_phrases:
                                if phrase in body_lower:
                                    raise AuthenticationError(
                                        f"Login rejected: '{phrase}' visible on page. "
                                        "Please verify credentials in .env"
                                    )
                        except AuthenticationError:
                            raise
                        except Exception:
                            pass  # Page not readable yet — continue polling

                    await asyncio.sleep(poll_interval_s)
                    elapsed += poll_interval_s
                else:
                    # Timed out — try to capture any error message for context
                    error_hint = ""
                    try:
                        body = await self.page.evaluate("() => document.body.innerText")
                        lines = [l.strip() for l in body.split("\n") if l.strip()]
                        error_hint = f" Page text: {' | '.join(lines[:5])}"
                    except Exception:
                        pass
                    raise AuthenticationError(
                        f"Login timeout after {deadline_s}s — URL never left /login."
                        f"{error_hint}\n"
                        "Check credentials in .env and Hive availability."
                    )

                # Brief settle for JS-rendered post-login content
                await asyncio.sleep(1.5)

                self.is_authenticated = True
                logger.info("Authentication successful")

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
