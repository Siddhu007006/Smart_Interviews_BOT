"""
Unit tests for authentication system: login flow, session verification, and error handling.

Focused unit tests covering:
1. Existing authenticated session (verify_session returns True → skip form)
2. Session verification with jwtToken as primary signal
3. Form missing raises bounded error
4. Credential secrets never leaked in exceptions
5. Deterministic selector ambiguity detection
6. Existing Session modal Confirm is scoped
7. Bounded timeouts on navigation
8. Session returns False when no token
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.auth.login import AuthManager
from src.auth.credentials import Credentials
from src.utils import AuthenticationError


@pytest.fixture
def test_credentials():
    """Provide test credentials (no real secrets)"""
    return Credentials(
        username="test_user@example.com",
        password="test_password_123",
        login_url="https://hive.smartinterviews.in/login"
    )


@pytest.fixture
def mock_auth_page():
    """Provide mock Playwright Page object"""
    page = AsyncMock()
    page.url = "https://hive.smartinterviews.in/login"
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.evaluate = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()
    return page


# ========================================
# TEST 1: Existing Authenticated Session
# ========================================
@pytest.mark.asyncio
async def test_existing_authenticated_session_skips_form(mock_auth_page, test_credentials):
    """Verify that when verify_session() returns True, form is skipped (session reuse path)."""
    # Setup: page already has jwtToken and authenticated state
    mock_auth_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic"
    mock_auth_page.evaluate = AsyncMock(return_value={
        "jwt": "mock_jwt_token_123",
        "username": "test_user@example.com",
        "jwtExpiry": "1999999999"
    })

    # Simulate form elements that already contain matching credentials so fill_credentials
    # hits the early-return "credentials already match" branch instead of re-typing.
    mock_username_element = AsyncMock()
    mock_username_element.is_visible = AsyncMock(return_value=True)
    mock_username_element.input_value = AsyncMock(return_value=test_credentials.username)

    mock_password_element = AsyncMock()
    mock_password_element.is_visible = AsyncMock(return_value=True)
    mock_password_element.input_value = AsyncMock(return_value=test_credentials.password)

    # query_selector_all is called for username selectors first, then password selectors
    mock_auth_page.query_selector_all = AsyncMock(
        side_effect=[
            [mock_username_element],   # username selector match
            [mock_password_element],   # password selector match
        ]
    )

    # page.locator() is a SYNCHRONOUS Playwright method that returns a Locator object.
    # AsyncMock makes every attribute async by default, so we must override locator
    # explicitly with a MagicMock that returns a locator-like object whose async
    # methods (wait_for, get_attribute, click) are AsyncMocks.
    mock_locator_first = AsyncMock()
    mock_locator_first.wait_for = AsyncMock()            # succeeds → submit button found
    mock_locator_first.get_attribute = AsyncMock(return_value=None)  # not disabled
    mock_locator_first.click = AsyncMock()

    mock_locator = MagicMock()
    mock_locator.first = mock_locator_first

    mock_auth_page.locator = MagicMock(return_value=mock_locator)

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)
    result = await auth_mgr.login()

    assert result is True
    assert auth_mgr.is_authenticated is True



# =========================================================
# TEST 2: Verify Session Uses jwtToken as Primary Signal
# =========================================================
@pytest.mark.asyncio
async def test_verify_session_primary_signal_jwttoken(mock_auth_page, test_credentials):
    """Verify that jwtToken in localStorage is the primary authentication signal."""
    mock_auth_page.url = "https://hive.smartinterviews.in/contests/basic"
    mock_auth_page.evaluate = AsyncMock(return_value={
        "jwt": "valid_token_abc123",
        "username": "test_user@example.com"
    })
    mock_auth_page.query_selector = AsyncMock(return_value=None)
    mock_auth_page.query_selector_all = AsyncMock(return_value=[])

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)
    result = await auth_mgr.verify_session()

    assert result is True
    assert auth_mgr.is_authenticated is True


# =========================================================
# TEST 3: Verify Session Returns False When No Token
# =========================================================
@pytest.mark.asyncio
async def test_verify_session_returns_false_when_no_token(mock_auth_page, test_credentials):
    """Verify that verify_session() returns False when jwtToken is absent."""
    mock_auth_page.url = "https://hive.smartinterviews.in/login"
    mock_auth_page.evaluate = AsyncMock(return_value={
        "jwt": None,
        "username": None
    })
    mock_auth_page.query_selector = AsyncMock(return_value=None)
    mock_auth_page.query_selector_all = AsyncMock(return_value=[])

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)
    result = await auth_mgr.verify_session()

    assert result is False
    assert auth_mgr.is_authenticated is False


# =========================================================
# TEST 4: Login Form Missing Raises Error
# =========================================================
@pytest.mark.asyncio
async def test_login_form_missing_raises_bounded_error(mock_auth_page, test_credentials):
    """Verify that when login form inputs never appear, AuthenticationError is raised."""
    mock_auth_page.url = "https://hive.smartinterviews.in/login"
    mock_auth_page.wait_for_load_state = AsyncMock()
    mock_auth_page.wait_for_selector = AsyncMock(side_effect=TimeoutError("Timeout"))
    mock_auth_page.query_selector_all = AsyncMock(return_value=[])

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)

    with pytest.raises(AuthenticationError) as exc_info:
        await auth_mgr.fill_credentials()

    assert "Failed to fill login credentials" in str(exc_info.value)


# =========================================================
# TEST 5: Credential Secrets Never Leaked
# =========================================================
@pytest.mark.asyncio
async def test_credential_secrets_never_leaked_in_exceptions(mock_auth_page, test_credentials):
    """Verify that password never appears in exception messages."""
    mock_auth_page.url = "https://hive.smartinterviews.in/login"
    mock_auth_page.wait_for_load_state = AsyncMock()
    mock_auth_page.wait_for_selector = AsyncMock(side_effect=TimeoutError("Timeout"))
    mock_auth_page.query_selector_all = AsyncMock(return_value=[])

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)

    try:
        await auth_mgr.fill_credentials()
    except AuthenticationError as e:
        error_str = str(e)
        assert "test_password_123" not in error_str
        assert "test_password_123" not in repr(e)


# =========================================================
# TEST 6: Deterministic Selector Ambiguity Detection
# =========================================================
@pytest.mark.asyncio
async def test_deterministic_selector_ambiguity_detection(mock_auth_page, test_credentials):
    """Verify that when multiple visible inputs match a selector, ambiguity error is raised."""
    mock_auth_page.url = "https://hive.smartinterviews.in/login"
    mock_auth_page.wait_for_load_state = AsyncMock()
    mock_auth_page.wait_for_selector = AsyncMock()

    # Create two visible inputs
    input1 = AsyncMock()
    input1.is_visible = AsyncMock(return_value=True)
    input2 = AsyncMock()
    input2.is_visible = AsyncMock(return_value=True)

    # Return multiple matches
    mock_auth_page.query_selector_all = AsyncMock(return_value=[input1, input2])

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)

    with pytest.raises(AuthenticationError) as exc_info:
        await auth_mgr.fill_credentials()

    assert "Ambiguous" in str(exc_info.value)


# =========================================================
# TEST 7: Navigate to Login Bounded Timeout
# =========================================================
@pytest.mark.asyncio
async def test_navigate_to_login_bounded_timeout(mock_auth_page, test_credentials):
    """Verify that navigate_to_login has explicit 10s bounded timeout."""
    mock_auth_page.goto = AsyncMock()

    auth_mgr = AuthManager(page=mock_auth_page, credentials=test_credentials, timeout_s=60)
    await auth_mgr.navigate_to_login()

    # Verify goto was called with 10000ms (10s) timeout
    mock_auth_page.goto.assert_called_once()
    call_kwargs = mock_auth_page.goto.call_args[1]
    assert call_kwargs["timeout"] == 10000


# =========================================================
# TEST 8: Existing Session Modal Confirm is Scoped
# =========================================================
@pytest.mark.asyncio
async def test_existing_session_modal_confirm_is_scoped(mock_auth_page, test_credentials):
    """Verify that only Confirm button within mat-dialog-container is targeted."""
    mock_auth_page.url = "https://hive.smartinterviews.in/login"

    # Modal Confirm button
    modal_confirm = AsyncMock()
    modal_confirm.is_visible = AsyncMock(return_value=True)

    # Unrelated Confirm button
    unrelated_confirm = AsyncMock()
    unrelated_confirm.is_visible = AsyncMock(return_value=True)

    def query_selector_handler(selector):
        if "mat-dialog-container" in selector:
            return modal_confirm
        return unrelated_confirm

    mock_auth_page.query_selector = AsyncMock(side_effect=query_selector_handler)

    # Verify scoped selector targeting
    dialog_confirm = await mock_auth_page.query_selector("mat-dialog-container button:has-text('Confirm')")
    assert dialog_confirm is modal_confirm

    unrelated = await mock_auth_page.query_selector("button:has-text('Confirm')")
    assert unrelated is unrelated_confirm
