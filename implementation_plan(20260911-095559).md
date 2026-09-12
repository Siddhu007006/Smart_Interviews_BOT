# Repair Production-Blocking Hive Platform Authentication Defect

## Overview
When running `python run.py`, the bot logged:
```
Navigating to login URL: https://hive.smartinterviews.in/login
✓ Login page loaded
Verifying authenticated session...
WARNING - No authenticated indicators found on https://hive.smartinterviews.in/ - may not be logged in
```
and remained stuck indefinitely.

Our empirical investigation on the live Hive platform revealed two root causes:
1. **Unbounded Form / Navigation Wait**: The existing authentication code did not strictly bound every wait phase and lacked handling for Hive's Angular routing transitions between the homepage (`https://hive.smartinterviews.in/`) and the login page (`https://hive.smartinterviews.in/login`).
2. **Hive "Existing Session" Material Dialog**: When submitting credentials for an account that has an active session from another device/browser, Hive's API returns `{"status":true,"message":"Session already exists","data":{"isSessionExist":true}}` and displays an Angular Material dialog (`<mat-dialog-container>`) titled **"Existing Session"** asking *"You already have an existing session. Do you want to logout from the existing session and login here?"* with buttons **Cancel** and **Confirm**. The bot previously waited indefinitely for the URL to change away from `/login`, but the dialog halted navigation until **Confirm** was clicked.
3. **SPA `localStorage` as Primary Source of Truth**: Hive is an Angular SPA. Successful login immediately sets `jwtToken` and `hive_username` in `window.localStorage`. The bot's session verification must prioritize `localStorage.getItem('jwtToken')` while also checking navbar indicators, and must strictly enforce bounded timeouts.

---

## User Review Required

> [!IMPORTANT]
> **Material Dialog Auto-Confirmation**:
> When logging in with rotated or shared credentials, Hive displays the `Existing Session` dialog. We will automatically detect and click `button:has-text('Confirm')` within the post-submit wait loop so that the session is acquired seamlessly without user intervention.

> [!IMPORTANT]
> **Strict Bounded Timeouts (Zero Hanging)**:
> All waits will be explicitly bounded:
> - Initial session check: **10 seconds**
> - Login form element appearance: **10 seconds**
> - Post-submission auth token acquisition / modal confirmation: **30 seconds**
> If any phase times out, a typed `AuthenticationError` is raised immediately, a debug screenshot is captured, and the browser closes cleanly without touching problem solving.

---

## Open Questions

None — the live DOM structure, API response payloads, and modal dialog behavior have been empirically validated in both persistent and clean Playwright browser contexts.

---

## Proposed Changes

### Authentication Layer (`src/auth`)

#### [MODIFY] [login.py](file:///c:/Users/Siddharth%20Reddy/projects/bot/src/auth/login.py)
1. **Selector Hardening**:
   - Username input: `input[formcontrolname='username'], input[name='username'], input#autofocus, input[type='text']`
   - Password input: `input[formcontrolname='password'], input[type='password'], input#password`
   - Submit button: `button.mat-mdc-unelevated-button:has-text('Login'), button:has-text('Login')`
2. **`navigate_to_login()` Enhancements**:
   - If currently on `https://hive.smartinterviews.in/` (homepage) and not authenticated, check for visible `a[href*='login'], button:has-text('Login')` or navigate directly to `https://hive.smartinterviews.in/login`.
   - Ensure the login form inputs are verified present before proceeding to fill.
3. **`fill_credentials()`**:
   - Bounded wait (10s max) for username and password fields to be visible.
   - Maintain character-by-character typing with delay to update Angular's `ReactiveFormsModule`.
   - Fail fast with `AuthenticationError` if inputs cannot be located within the 10s deadline.
4. **`submit_login()`**:
   - Locate the Login button, ensure it is enabled, and click.
5. **`wait_for_authentication()`**:
   - Bounded 30s wait loop (polling every 0.5s).
   - In each tick:
     1. Check if `mat-dialog-container button:has-text('Confirm')` is visible. If so, log and click **Confirm**.
     2. Check `localStorage.getItem('jwtToken')`. If truthy, authentication succeeded $\rightarrow$ break.
     3. Check if page URL left `/login` and is on an authenticated page $\rightarrow$ break.
     4. Check for error banners / failure messages (`invalid credentials`, `incorrect password`, `user not found`, etc.) and fail fast with `AuthenticationError`.
   - If 30s expires without `jwtToken`: capture screenshot to `scratch/login_timeout.png` and raise `AuthenticationError("Login completion timed out after 30s...")`.
6. **`verify_session()`**:
   - Check `localStorage.getItem('jwtToken')` and `localStorage.getItem('hive_username')`.
   - Check UI navbar elements (`[aria-label*='profile']`, `[href*='logout']`, `button:has-text('Logout')`, text matching username).
   - Return `True` if verified, `False` if not.
   - Strict 10s timeout budget; never hang.

---

### Test Fixture State Isolation

#### [MODIFY] [test_retry_flow.py](file:///c:/Users/Siddharth%20Reddy/projects/bot/tests/test_retry_flow.py)
- Ensure the `mock_bot` fixture initializes an isolated `BotState` so unit tests do not accidentally read the live developer's `~/.hive_bot/state.json` file.

---

### Automated Unit Test Suite

#### [NEW] [test_auth.py](file:///c:/Users/Siddharth%20Reddy/projects/bot/tests/test_auth.py)
Add 7 required test cases:
1. **`test_existing_authenticated_session_skips_form`**: `verify_session()` returns `True` initially; form filling and submission are never called.
2. **`test_unauthenticated_session_successful_login`**: unauthenticated $\rightarrow$ fills username/password from credentials $\rightarrow$ clicks login $\rightarrow$ verifies `jwtToken` $\rightarrow$ succeeds.
3. **`test_unauthenticated_session_with_existing_session_modal`**: login form submitted $\rightarrow$ Existing Session dialog appears $\rightarrow$ bot clicks Confirm $\rightarrow$ `jwtToken` set $\rightarrow$ succeeds.
4. **`test_login_form_missing_raises_bounded_error`**: inputs never appear $\rightarrow$ raises `AuthenticationError` within bounded timeout.
5. **`test_login_submission_fails_timeout`**: credentials submitted but `jwtToken` never appears and page never redirects $\rightarrow$ raises `AuthenticationError` within bounded timeout.
6. **`test_stale_expired_session_recovers_via_login`**: initial check returns `False` $\rightarrow$ performs login $\rightarrow$ post-login verification returns `True`.
7. **`test_credential_secrets_never_leaked_in_exceptions_or_logs`**: verify neither password nor API key appears in exception strings, `__repr__`, or error logs.

---

### Live Smoke Test & Verification Tooling

#### [MODIFY] [scratch/credential_smoke_test.py](file:///c:/Users/Siddharth%20Reddy/projects/bot/scratch/credential_smoke_test.py)
- Extend script to test **BOTH**:
  1. **Cold-start session**: Uses an isolated temporary profile (`tempfile.TemporaryDirectory()`), navigates to login, fills live credentials, clicks Login, handles Confirm dialog, verifies `jwtToken`.
  2. **Existing persistent session**: Uses `~/.hive_bot_profile`, launches browser, verifies instant `verify_session() == True` without filling form.

---

## Verification Plan

### Automated Tests
1. Run complete pytest suite:
   ```powershell
   & "c:\Users\Siddharth Reddy\projects\bot\.venv\Scripts\python.exe" -m pytest "c:\Users\Siddharth Reddy\projects\bot\tests" -v
   ```
   Must pass 100% (all existing tests + new auth tests).

2. Run secret scanner:
   ```powershell
   & "c:\Users\Siddharth Reddy\projects\bot\.venv\Scripts\python.exe" "c:\Users\Siddharth Reddy\projects\bot\scratch\secret_scanner.py"
   ```
   Must report 0 live secrets in tracked files or tests.

### Manual / Live Verification
1. Run live credential smoke test:
   ```powershell
   & "c:\Users\Siddharth Reddy\projects\bot\.venv\Scripts\python.exe" "c:\Users\Siddharth Reddy\projects\bot\scratch\credential_smoke_test.py"
   ```
   - Validates cold-start login (Case B).
   - Validates existing session skip (Case A).
2. Run dry-run bot launcher:
   ```powershell
   & "c:\Users\Siddharth Reddy\projects\bot\.venv\Scripts\python.exe" run.py --dry-run
   ```
   - Verifies that `python run.py` completes login cleanly and reaches the problem discovery / contest phase without hanging.
