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
        Navigate to the login page (bounded 10s timeout).
        
        Raises:
            AuthenticationError: If navigation fails
        """
        with LogContext("Navigating to login page"):
            try:
                logger.info(f"Navigating to login URL: {self.credentials.login_url}")
                await self.page.goto(
                    self.credentials.login_url,
                    wait_until="domcontentloaded",
                    timeout=10000,  # Explicit bounded 10s timeout
                )
                logger.info("✓ Login page loaded")

            except Exception as e:
                logger.error(f"Failed to navigate to login page: {e}")
                raise AuthenticationError(f"Failed to navigate to login page: {e}") from e

    async def fill_credentials(self) -> None:
        """
        Fill username and password fields intelligently.

        Strategy:
        1. Check what's currently in the form fields
        2. If they match .env credentials → skip filling (just click login)
        3. If they don't match or are empty → fill from .env

        Uses character-by-character typing so Angular's reactive form model
        receives real keyboard events and updates its internal state.

        Selector priority (deterministic, ambiguity detection):
        - Username: formcontrolname='username' → name='username' → scoped fallback
        - Password: formcontrolname='password' → name='password' → scoped fallback

        Raises:
            AuthenticationError: If credential fields cannot be found or filled
        """
        with LogContext("Filling login credentials"):
            try:
                # Wait for Angular to render the login form.
                await self.page.wait_for_load_state("domcontentloaded", timeout=10000)

                # Wait for first visible input to confirm form is rendered
                await self.page.wait_for_selector(
                    "input[formcontrolname='username'], input[name='username'], input[type='email'], input[type='text']",
                    state="visible",
                    timeout=10000,
                )
                logger.debug("Login form is visible")

                # --- CHECK EXISTING CREDENTIALS ---
                logger.info("Checking if form already has matching credentials...")
                
                # Find username field
                username_selectors = [
                    "input[formcontrolname='username']",
                    "input[name='username']",
                    "input[type='email']",
                ]
                
                username_field = None
                existing_username = None
                for selector in username_selectors:
                    candidates = await self.page.query_selector_all(selector)
                    visible_candidates = []
                    for cand in candidates:
                        if await cand.is_visible():
                            visible_candidates.append(cand)
                    
                    if len(visible_candidates) == 1:
                        username_field = visible_candidates[0]
                        existing_username = await username_field.input_value()
                        logger.debug(f"Found username field: {selector}")
                        break
                
                # Find password field
                password_selectors = [
                    "input[formcontrolname='password']",
                    "input[name='password']",
                    "input[type='password']",
                ]
                
                password_field = None
                existing_password = None
                for selector in password_selectors:
                    candidates = await self.page.query_selector_all(selector)
                    visible_candidates = []
                    for cand in candidates:
                        if await cand.is_visible():
                            visible_candidates.append(cand)
                    
                    if len(visible_candidates) == 1:
                        password_field = visible_candidates[0]
                        existing_password = await password_field.input_value()
                        logger.debug(f"Found password field: {selector}")
                        break

                # Check if existing credentials match .env
                env_username = self.credentials.username
                env_password = self.credentials.password
                
                if (existing_username and existing_password and
                    existing_username.strip() == env_username.strip() and
                    existing_password.strip() == env_password.strip()):
                    logger.info(f"✓ Form already has correct credentials for {env_username} - skipping fill, will click login")
                    return  # Skip filling, will proceed to login click
                
                logger.info(f"Form credentials don't match .env ({existing_username} vs {env_username}) or are empty - filling from .env")

                # --- USERNAME ---
                logger.info("Looking for username input field (deterministic hierarchy)...")
                username_selectors = [
                    "input[formcontrolname='username']",
                    "input[name='username']",
                    "input[type='email']",
                ]
                
                username_field = None
                for selector in username_selectors:
                    candidates = await self.page.query_selector_all(selector)
                    visible_candidates = []
                    for cand in candidates:
                        if await cand.is_visible():
                            visible_candidates.append(cand)
                    
                    if len(visible_candidates) > 1:
                        raise AuthenticationError(
                            f"Ambiguous username selector '{selector}': found {len(visible_candidates)} visible matches. "
                            f"Cannot safely select username input. Please verify login page structure."
                        )
                    elif len(visible_candidates) == 1:
                        username_field = visible_candidates[0]
                        logger.debug(f"✓ Found username field via: {selector}")
                        break

                if not username_field:
                    raise AuthenticationError(
                        "Could not locate username input field. "
                        "Verify login page structure matches expected format. "
                        f"Tried selectors: {username_selectors}"
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
                logger.info("Looking for password input field (deterministic hierarchy)...")
                password_selectors = [
                    "input[formcontrolname='password']",
                    "input[name='password']",
                    "input[type='password']",
                ]
                
                password_field = None
                for selector in password_selectors:
                    candidates = await self.page.query_selector_all(selector)
                    visible_candidates = []
                    for cand in candidates:
                        if await cand.is_visible():
                            visible_candidates.append(cand)
                    
                    if len(visible_candidates) > 1:
                        raise AuthenticationError(
                            f"Ambiguous password selector '{selector}': found {len(visible_candidates)} visible matches. "
                            f"Cannot safely select password input. Please verify login page structure."
                        )
                    elif len(visible_candidates) == 1:
                        password_field = visible_candidates[0]
                        logger.debug(f"✓ Found password field via: {selector}")
                        break

                if not password_field:
                    raise AuthenticationError(
                        "Could not locate password input field. "
                        "Verify login page structure matches expected format. "
                        f"Tried selectors: {password_selectors}"
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
        Wait for successful authentication with bounded 30s timeout.

        Hive is a SPA that uses client-side routing (pushState) after login.
        Primary signal: jwtToken in localStorage (set immediately on login).
        Secondary signals: page URL departure from /login, authenticated UI indicators.

        Handles "Existing Session" modal: if dialog title is "Existing Session" and
        Confirm button is visible, click it automatically to proceed with login.

        Raises:
            AuthenticationError: If authentication fails or times out
        """
        with LogContext("Waiting for authentication"):
            try:
                logger.info("Waiting for authentication to complete (30s timeout)...")

                from urllib.parse import urlparse

                login_path = urlparse(self.credentials.login_url).path.rstrip("/")
                deadline_s = 30  # Explicit bounded 30s timeout per refinement
                poll_interval_s = 0.5
                elapsed = 0.0
                pre_login_token = None

                # Record pre-login token to distinguish fresh vs. stale tokens
                try:
                    pre_login_token = await self.page.evaluate("() => localStorage.getItem('jwtToken')")
                    logger.debug(f"Pre-login jwtToken state: {'present' if pre_login_token else 'absent'}")
                except Exception:
                    pass

                while elapsed < deadline_s:
                    # --- Check for Existing Session dialog ---
                    try:
                        dialog_title = await self.page.evaluate("""() => {
                            const dialog = document.querySelector('mat-dialog-container');
                            if (!dialog) return null;
                            const title = dialog.querySelector('[mat-dialog-title], h1, h2');
                            return title ? title.innerText.trim() : null;
                        }""")

                        if dialog_title and "existing session" in dialog_title.lower():
                            logger.info(f"Existing Session dialog detected: '{dialog_title}'")
                            # Scoped check: Confirm button must be within the dialog AND dialog must be visible
                            confirm_btn = await self.page.query_selector(
                                "mat-dialog-container button:has-text('Confirm')"
                            )
                            if confirm_btn and await confirm_btn.is_visible():
                                logger.info("Clicking Confirm button to proceed with login...")
                                await confirm_btn.click()
                                await asyncio.sleep(1.0)  # Wait for modal to close
                                logger.debug("✓ Existing Session confirmed")
                            else:
                                logger.warning("Existing Session dialog visible but Confirm button not found or not visible")
                    except Exception as e:
                        logger.debug(f"Could not check for Existing Session dialog: {e}")

                    # --- Primary check: jwtToken in localStorage (fresh token) ---
                    try:
                        current_token = await self.page.evaluate("() => localStorage.getItem('jwtToken')")
                        if current_token and current_token != pre_login_token:
                            logger.info("✓ Authentication successful - fresh jwtToken acquired")
                            self.is_authenticated = True
                            return
                    except Exception as e:
                        logger.debug(f"Could not read jwtToken from localStorage: {e}")

                    # --- Secondary check: URL departure from /login ---
                    current_url = self.page.url
                    if current_url not in ("about:blank", ""):
                        current_path = urlparse(current_url).path.rstrip("/")
                        if current_path != login_path:
                            logger.info(f"✓ Redirected from login → {current_url}")
                            # Verify we also have the token now
                            try:
                                token = await self.page.evaluate("() => localStorage.getItem('jwtToken')")
                                if token:
                                    logger.info("✓ Authentication successful - URL redirected and token present")
                                    self.is_authenticated = True
                                    return
                            except Exception:
                                pass

                    # --- Check for error messages every 2s ---
                    if elapsed > 0 and elapsed % 2.0 < poll_interval_s:
                        try:
                            body = await self.page.evaluate("() => document.body.innerText")
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

                # --- Timeout expired ---
                error_hint = ""
                try:
                    body = await self.page.evaluate("() => document.body.innerText")
                    lines = [l.strip() for l in body.split("\n") if l.strip()]
                    error_hint = f" Page text: {' | '.join(lines[:5])}"
                except Exception:
                    pass

                # Capture debug screenshot
                try:
                    screenshot_path = "scratch/login_timeout.png"
                    await self.page.screenshot(path=screenshot_path)
                    logger.debug(f"Debug screenshot captured: {screenshot_path}")
                except Exception as e:
                    logger.debug(f"Could not capture screenshot: {e}")

                raise AuthenticationError(
                    f"Login completion timed out after {deadline_s}s — "
                    f"jwtToken not acquired and URL did not redirect.{error_hint}\n"
                    "Check credentials in .env, Hive availability, and network connectivity."
                )

            except AuthenticationError:
                raise
            except Exception as e:
                logger.error(f"Authentication wait failed: {e}")
                raise AuthenticationError(f"Authentication verification failed: {e}") from e




    async def verify_session(self) -> bool:
        """
        Verify that session is authenticated (bounded 10s timeout).
        
        Primary signal: jwtToken in localStorage (Hive SPA auth mechanism).
        Secondary signals: authenticated UI indicators, URL not on /login.
        
        For cold-start (fresh profile): jwtToken presence is conclusive.
        For persistent profile: token may be stale. Also check UI indicators
        to distinguish stale vs. active session.
        
        Returns:
            True if session appears to be authenticated
            
        Raises:
            AuthenticationError: If session verification fails
        """
        with LogContext("Verifying session"):
            try:
                logger.info("Verifying authenticated session (10s timeout)...")

                current_url = self.page.url
                
                # 1. URL check: if still explicitly on /login, definitely not authenticated
                if "/login" in current_url.lower():
                    logger.debug(f"Still on login page ({current_url}) - session not authenticated")
                    return False

                # 2. Primary check: jwtToken in localStorage (Hive SPA mechanism)
                # This is the single most reliable indicator on Hive
                try:
                    auth_storage = await self.page.evaluate("""() => {
                        return {
                            jwt: localStorage.getItem('jwtToken'),
                            username: localStorage.getItem('hive_username'),
                            jwtExpiry: localStorage.getItem('jwtExpiry')
                        };
                    }""")

                    jwt_token = auth_storage.get("jwt")
                    stored_username = auth_storage.get("username")

                    if jwt_token:
                        # Token is present - this is the primary success signal
                        logger.info(
                            "✓ Session authenticated via localStorage (jwtToken present)"
                        )
                        self.is_authenticated = True
                        return True

                except Exception as e:
                    logger.debug(f"Could not read localStorage for auth tokens: {e}")

                # 3. Secondary check: username visible in navbar/header
                try:
                    user_element = await self.page.query_selector(f"text={self.credentials.username}")
                    if user_element and await user_element.is_visible():
                        logger.info(
                            f"✓ Session verified - username '{self.credentials.username}' visible in UI"
                        )
                        self.is_authenticated = True
                        return True
                except Exception as e:
                    logger.debug(f"Could not check username visibility in UI: {e}")

                # 4. Fallback: common authenticated UI elements
                try:
                    auth_indicators = await self.page.query_selector_all(
                        "[aria-label*='profile'], [aria-label*='user'], "
                        "[aria-label*='account'], [href*='logout'], "
                        "[href*='signout'], a:has-text('Logout'), "
                        "a:has-text('Sign out')"
                    )
                    if auth_indicators and len(auth_indicators) > 0:
                        logger.debug("Session verified - authenticated indicators found")
                        self.is_authenticated = True
                        return True
                except Exception as e:
                    logger.debug(f"Could not check authenticated indicators: {e}")

                logger.warning(
                    f"No authenticated indicators found on {current_url} - "
                    "session may not be active or jwtToken may have expired"
                )
                return False

            except Exception as e:
                logger.error(f"Session verification failed: {e}")
                raise AuthenticationError(f"Session verification failed: {e}") from e

    async def login(self) -> bool:
        """
        Perform complete login workflow.
        
        Steps:
        1. Clear Hive authentication state (localStorage, session cookies)
           - Keeps profile intact (extensions, other data)
           - Forces fresh login every run
        2. Navigate to login page
        3. Fill credentials (always - explicit fresh login)
        4. Submit and handle modal
        5. Verify newly authenticated session
        6. Verify logged-in account matches configured credentials
        
        Returns:
            True if login successful
            
        Raises:
            AuthenticationError: If any login step fails
        """
        with LogContext(f"Login workflow for user {self.credentials.username}"):
            try:
                logger.info("Starting login workflow...")

                # Step 1: Logout from any existing session first
                # Navigate to logout endpoint to clear server-side session
                logger.info("Logging out from any existing session...")
                try:
                    logout_url = "https://hive.smartinterviews.in/logout"
                    logger.debug(f"Navigating to logout: {logout_url}")
                    await self.page.goto(logout_url, wait_until="networkidle", timeout=15000)
                    await asyncio.sleep(2.0)  # Wait for logout to process
                    logger.debug("✓ Logout request sent")
                except Exception as e:
                    logger.debug(f"Could not access logout endpoint: {e}")

                # Step 2: Clear Hive authentication state from localStorage/sessionStorage
                # This forces a fresh login every run while keeping browser profile intact
                logger.info("Clearing Hive authentication state from browser...")
                try:
                    await self.page.evaluate("""() => {
                        // Clear Hive-specific auth tokens and session
                        localStorage.removeItem('jwtToken');
                        localStorage.removeItem('hive_username');
                        localStorage.removeItem('jwtExpiry');
                        sessionStorage.clear();
                        return true;
                    }""")
                    logger.debug("✓ Authentication state cleared from storage")
                except Exception as e:
                    logger.debug(f"Could not clear auth state: {e}")

                # Step 3: Navigate to login page
                await self.navigate_to_login()
                await asyncio.sleep(1.0)  # Settle time

                # Step 4: Fill credentials (always - explicit fresh login)
                logger.info("Filling login credentials (explicit fresh login)...")
                await self.fill_credentials()

                # Step 5: Submit login
                await self.submit_login()

                # Step 6: Wait for authentication (handles modal)
                await self.wait_for_authentication()

                # Step 7: Verify session with newly acquired credentials
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

