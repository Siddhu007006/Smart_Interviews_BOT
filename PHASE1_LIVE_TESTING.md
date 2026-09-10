# Phase 1 Live Testing and DOM Inspection Guide

## Overview

Phase 1 establishes the foundation by verifying the bot can connect to Hive, authenticate, and detect the problem list page. This guide walks through the live testing process and DOM inspection required to identify the correct selectors for the Hive platform.

---

## 1. Prerequisites Checklist

Before starting Phase 1 live testing, ensure you have:

- [ ] **Python 3.10+** installed and available in PATH
  - Verify: `python --version`
- [ ] **Chrome browser** (not Chromium or Brave)
  - Verify: Chrome is installed at default location
  - Note: Playwright requires the actual Chrome executable
- [ ] **Hive Extension Detector** installed from Chrome Web Store
  - Visit: https://chrome.google.com/webstore/
  - Search for "Hive Extension Detector"
  - Click "Add to Chrome"
- [ ] **Actual Hive account** with valid credentials
  - Username/email
  - Password
  - Access to at least one contest with problems
- [ ] **At least one AI provider key** (for Phase 2 integration)
  - OpenAI API key, OR
  - Groq API key, OR
  - Google Gemini API key
  - Note: Phase 1 doesn't use this, but required for Phase 2

---

## 2. Setup Steps

### Step 1: Create Environment File

```bash
# Copy the example environment file
cp .env.example .env
```

### Step 2: Fill in Required Credentials

Edit `.env` and fill in these required fields:

```env
# Hive Login Configuration
HIVE_LOGIN_URL=https://hive.com/contests           # The main Hive contests page
HIVE_USERNAME=your_hive_username                   # Your Hive account username
HIVE_PASSWORD=your_hive_password                   # Your Hive account password

# AI Provider Keys (pick at least ONE for Phase 2)
OPENAI_API_KEY=sk-...                              # OpenAI API key
GROQ_API_KEY=gsk_...                               # Groq API key
GEMINI_API_KEY=AIza...                             # Google Gemini API key

# Logging Configuration (optional, but helpful)
LOG_LEVEL=DEBUG                                    # Use DEBUG for verbose output
```

**Important:** Keep `.env` in your `.gitignore` and never commit credentials.

### Step 3: Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Playwright and Chrome drivers
python -m playwright install

# On Linux, you may also need system dependencies
python -m playwright install-deps
```

Verify installation:
```bash
python -c "from playwright.async_api import async_playwright; print('Playwright OK')"
```

---

## 3. Running Phase 1

### Command Variations

**Standard run:**
```bash
python -m src.main
```
Runs with INFO-level logging, browser visible, full debug output.

**Verbose debugging:**
```bash
python -m src.main --log-level DEBUG
```
Maximum verbosity - shows all internal steps, network calls, and DOM queries.

**Headless mode:**
```bash
python -m src.main --headless
```
Browser runs in background without GUI - useful for testing on servers or CI/CD.

### What Happens During Phase 1

The bot executes these steps in sequence:

1. **Browser Initialization**
   - Launches Chrome with persistent user profile
   - Loads stored cookies and login sessions (if available)
   - Displays browser window (unless `--headless` used)

2. **Extension Verification**
   - Detects if Hive Extension Detector is installed
   - Verifies it's properly registered in Chrome
   - Logs status: "✓ Extension detected" or "✗ Extension NOT found"

3. **Navigation to Hive**
   - Opens URL from `HIVE_LOGIN_URL` env var
   - Waits for page to load (with timeout)

4. **Login Handling**
   - If not already logged in, fills login form
   - Submits credentials from `HIVE_USERNAME` and `HIVE_PASSWORD`
   - Waits for redirect to authenticated state

5. **Session Verification**
   - Confirms user is authenticated
   - Checks for session tokens in cookies/storage
   - Logs successful auth or auth failure

6. **Problem List Detection**
   - Searches for problem list container on page
   - Counts visible problems
   - Logs: "✓ Found 25 problems" or "✗ Problem list not found"

7. **Phase 1 Complete**
   - Bot pauses and keeps browser open
   - Does NOT continue to Phase 2 (problem extraction)
   - Ready for DOM inspection and manual testing

### Expected Output

```
[INFO] Starting Hive Automation Bot - Phase 1
[INFO] Browser launching...
[INFO] ✓ Chrome browser initialized
[INFO] ✓ Extension Detector verified
[INFO] Navigating to https://hive.com/contests
[INFO] Page loaded in 2.5s
[INFO] ✓ Login verified (user: john_doe)
[INFO] ✓ Found problem list container
[INFO] Problem count: 25
[INFO] Phase 1 complete - ready for Phase 2
[INFO] Browser remains open for inspection
```

---

## 4. DOM Inspection Process

Once Phase 1 completes and the browser shows the problem list, follow these steps to inspect and document the DOM structure:

### Step 1: Open DevTools

In the browser window, press `F12` (or `Ctrl+Shift+I` on Windows/Linux, `Cmd+Option+I` on macOS).

### Step 2: Navigate to Elements/Inspector

The DevTools panel opens at the bottom or side. Click the **Elements** tab (Chrome) or **Inspector** tab (Firefox).

### Step 3: Use the Element Picker

In the top-left of DevTools, click the **element picker icon** (looks like a cursor/box).
- Alternatively: Press `Ctrl+Shift+C` (Windows/Linux) or `Cmd+Shift+C` (macOS)
- Cursor changes to indicate picker is active

### Step 4: Inspect Problem Elements

**Inspect the problem list container:**
- Click anywhere on the problem list area
- DevTools highlights the container element in the HTML tree
- Note the element's class, id, data attributes
- Example: `<div class="problem-list" id="problems">`

**Inspect a single problem card:**
- Click on one problem entry
- DevTools highlights the card element
- Note the element's class, id, and data attributes
- Example: `<div class="problem-item" data-problem-id="456">`

**Inspect nested elements within a card:**
- Double-click to drill into nested elements
- Look for: problem title, difficulty, status button
- Note their classes and positions
- Example: `<span class="problem-title">Array Basics</span>`

### Step 5: Document Findings

For each element you inspect, record:
- **Element Type** (div, span, button, etc.)
- **Class Name(s)**
- **ID** (if present)
- **Data Attributes** (e.g., `data-problem-id`)
- **Text Content** (for status buttons)
- **Parent/Child Context** (what's it nested in?)

Example documentation:
```
Element: Problem Card Container
  Type: div
  Class: problem-item
  Data Attr: data-problem-id="123"
  Parent: div.problems-list
  Status: FOUND ✓
```

### Step 6: Test Selectors in Console

DevTools also has a **Console** tab. Test CSS selectors directly:

```javascript
// Test CSS selector
document.querySelectorAll('.problem-item')
// Returns: NodeList [div.problem-item, div.problem-item, ...]

// Count results
document.querySelectorAll('.problem-item').length
// Returns: 25

// Get first result's text
document.querySelector('.problem-item .problem-title').textContent
// Returns: "Array Basics"

// Test XPath
document.evaluate("//button[contains(text(), 'Continue')]", document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength
// Returns: 5
```

This confirms selectors work before adding them to code.

---

## 5. What To Discover

Use DOM inspection to locate and document these elements. This is critical for Phase 2 implementation.

### Problem List Selectors

- [ ] **Problem list container selector**
  - The main `<div>` that wraps all problem cards
  - Query: `document.querySelector('???')`
  - Store in: `PROBLEM_LIST_CONTAINER`

- [ ] **Individual problem card selector**
  - Wrapping `<div>` for each problem
  - Query: `document.querySelectorAll('???')`
  - Store in: `PROBLEM_CARD`

- [ ] **Problem title location**
  - Where the problem name is displayed
  - Example: "Array Basics", "Two Sum", etc.
  - Query: Within each card, `querySelector('???')`
  - Store in: `PROBLEM_TITLE`

- [ ] **Problem difficulty location**
  - Where difficulty badge is shown
  - Example: "Easy", "Medium", "Hard"
  - Query: `querySelector('???')`
  - Store in: `PROBLEM_DIFFICULTY`

- [ ] **Problem status button location**
  - The button showing current status
  - Examples: "Continue", "Solve", "Try Again"
  - Query: `querySelector('???')`
  - Store in: `PROBLEM_STATUS_BUTTON`

### Status Text Patterns

- [ ] **Text for "solved" problems**
  - What button text indicates problem is solved?
  - Example: "Try Again", "Solved", "Review"
  - Store in: `STATUS_SOLVED`

- [ ] **Text for "unsolved" - needs solving**
  - What button text for never-attempted?
  - Example: "Solve", "Start", "Begin"
  - Store in: `STATUS_UNSOLVED_SOLVE`

- [ ] **Text for "unsolved" - incomplete**
  - What button text for previously attempted?
  - Example: "Continue", "Resume", "Retry"
  - Store in: `STATUS_UNSOLVED_CONTINUE`

### Other Elements

- [ ] **Problem count display selector**
  - Where total problem count is shown
  - Example: "25 Problems" or displays number
  - Store in: `PROBLEM_COUNT_DISPLAY`

- [ ] **Pagination controls** (if applicable)
  - Are problems paginated or all on one page?
  - If paginated, selector for "Next" button
  - Store in: `PAGINATION_NEXT_BUTTON`

- [ ] **Contest name selector**
  - The title or name of current contest
  - Store in: `CONTEST_NAME`

- [ ] **Problem ID storage**
  - How is each problem's ID stored?
  - Is it in a data attribute? HTML attribute? Text?
  - Example: `data-problem-id="123"` or `data-id="123"`
  - Store in: `PROBLEM_ID_ATTRIBUTE`

---

## 6. DOM Inspection Example

Here's an example of what the Hive problem list HTML structure might look like. **Your actual Hive page will differ** - use this only as a reference structure:

```html
<!-- Main contest page -->
<div class="hive-main-container">
  
  <!-- Contest header -->
  <div class="contest-header">
    <h1 class="contest-title">LeetCode Easy Challenge</h1>
    <p class="contest-subtitle">25 problems • 7 days remaining</p>
  </div>

  <!-- Problems list container -->
  <div class="problems-list" id="problems-container">
    
    <!-- Individual problem card -->
    <div class="problem-card" data-problem-id="123">
      <div class="problem-header">
        <span class="problem-index">1</span>
        <span class="problem-title">Array Basics</span>
        <span class="problem-difficulty difficulty-easy">Easy</span>
      </div>
      <div class="problem-content">
        <p class="problem-description">Learn basic array operations...</p>
      </div>
      <div class="problem-footer">
        <div class="problem-stats">
          <span class="acceptance-rate">75% Acceptance</span>
        </div>
        <button class="action-button status-unsolved">Solve</button>
      </div>
    </div>

    <!-- Another problem card (solved) -->
    <div class="problem-card" data-problem-id="456">
      <div class="problem-header">
        <span class="problem-index">2</span>
        <span class="problem-title">Two Sum</span>
        <span class="problem-difficulty difficulty-medium">Medium</span>
      </div>
      <div class="problem-content">
        <p class="problem-description">Find two numbers that add to target...</p>
      </div>
      <div class="problem-footer">
        <div class="problem-stats">
          <span class="acceptance-rate">82% Acceptance</span>
        </div>
        <button class="action-button status-solved">Try Again</button>
      </div>
    </div>

    <!-- Card 3 and beyond... -->
  </div>

</div>
```

**Key observations from this example:**
- Problem cards are wrapped in `div.problem-card`
- Each has `data-problem-id` attribute with numeric ID
- Difficulty is a separate `<span>` with class like `difficulty-easy`
- Status button shows text: "Solve" (unsolved) or "Try Again" (solved)
- Description text is in `p.problem-description`

**Your Hive page will have different structure.** Document what YOU find.

---

## 7. Updating ui_constants.py

Once you've discovered all selectors through DOM inspection, update the constants file. Here's the template:

### File: `src/hive/ui_constants.py`

```python
"""
Hive UI Selectors and Constants

These selectors were discovered via live DOM inspection on the actual Hive platform.
They are NOT assumptions - each selector was empirically verified by inspecting
real page elements in a browser.

Discovery Date: YYYY-MM-DD
Tested With: Chrome Version XX, Hive Platform URL: https://hive.com/contests
Tested By: [Your Name]

IMPORTANT: If Hive updates their DOM structure, these selectors may break.
When that happens, repeat the live testing and inspection process to find new selectors.
"""

# ============================================================================
# PROBLEM LIST CONTAINER
# ============================================================================

PROBLEM_LIST_CONTAINER = "div.problems-list"
"""
The main container that wraps all problem cards.
Selector: CSS class 'problems-list'
Verification: document.querySelector('.problems-list') returns the container
"""

# ============================================================================
# PROBLEM CARD ELEMENTS
# ============================================================================

PROBLEM_CARD = "div.problem-card"
"""
Individual problem card wrapper.
Each problem on the list is wrapped in an element with this selector.
Query: document.querySelectorAll('.problem-card') returns all cards
"""

PROBLEM_ID_ATTRIBUTE = "data-problem-id"
"""
HTML attribute storing the problem's unique ID.
Extraction: card.getAttribute('data-problem-id') returns ID as string
Example: "123", "456", etc.
"""

PROBLEM_TITLE = "span.problem-title"
"""
The text element containing the problem name.
Relative to card: card.querySelector('.problem-title')
Example text: "Array Basics", "Two Sum", "Longest Substring"
"""

PROBLEM_DIFFICULTY = "span.problem-difficulty"
"""
The text element containing difficulty level.
Relative to card: card.querySelector('.problem-difficulty')
Possible values: "Easy", "Medium", "Hard"
"""

PROBLEM_STATUS_BUTTON = "button.action-button"
"""
The button showing current status or action.
Relative to card: card.querySelector('.action-button')
Text content varies: "Solve", "Continue", "Try Again", etc.
"""

# ============================================================================
# STATUS TEXT PATTERNS
# ============================================================================

STATUS_SOLVED = "Try Again"
"""
Button text indicating a problem has been solved.
Used to identify which problems in list are completed.
"""

STATUS_UNSOLVED_SOLVE = "Solve"
"""
Button text for completely unsolved problems (never attempted).
These are problems the user hasn't started yet.
"""

STATUS_UNSOLVED_CONTINUE = "Continue"
"""
Button text for partially solved problems (attempted but incomplete).
These are problems the user started but didn't complete.
"""

# ============================================================================
# XPATHS FOR COMPLEX QUERIES
# ============================================================================

UNSOLVED_PROBLEMS_XPATH = "//div[@class='problem-card']//button[contains(text(), 'Solve') or contains(text(), 'Continue')]"
"""
XPath to find all unsolved problem cards.
Matches cards with buttons containing "Solve" or "Continue" text.
Usage: driver.find_elements(By.XPATH, UNSOLVED_PROBLEMS_XPATH)
"""

SOLVED_PROBLEMS_XPATH = "//div[@class='problem-card']//button[contains(text(), 'Try Again')]"
"""
XPath to find all solved problem cards.
Matches cards with buttons containing "Try Again" text.
Usage: driver.find_elements(By.XPATH, SOLVED_PROBLEMS_XPATH)
"""

# ============================================================================
# OTHER UI ELEMENTS
# ============================================================================

CONTEST_NAME = "h1.contest-title"
"""
The heading element showing current contest name.
Query: document.querySelector('.contest-title').textContent
Example: "LeetCode Easy Challenge"
"""

PROBLEM_COUNT_DISPLAY = "p.contest-subtitle"
"""
Text element showing total problem count.
Query: document.querySelector('.contest-subtitle').textContent
Example: "25 problems • 7 days remaining"
"""

# ============================================================================
# PAGINATION (if applicable)
# ============================================================================

PAGINATION_NEXT_BUTTON = "button.pagination-next"
"""
Button to navigate to next page of problems (if paginated).
Set to None if all problems display on single page.
Query: document.querySelector('.pagination-next')
"""

PAGINATION_CONTAINER = "div.pagination"
"""
Container for pagination controls.
Query: document.querySelector('.pagination')
Set to None if not applicable.
"""

# ============================================================================
# TIMEOUTS (in seconds)
# ============================================================================

ELEMENT_LOAD_TIMEOUT = 10
"""Maximum time to wait for elements to appear on page"""

PAGE_LOAD_TIMEOUT = 15
"""Maximum time to wait for page navigation"""

LOGIN_TIMEOUT = 20
"""Maximum time to wait for login to complete"""
```

### Tips for Updating

1. **Match real selectors exactly** - Copy from DevTools element picker output
2. **Test in console first** - Verify with JavaScript before adding to code
3. **Include comments** - Document why each selector was chosen
4. **Note discoveries** - Record what you learned about the page structure
5. **Date your findings** - Mark when this was verified
6. **Keep original line numbers** - If updating existing file, preserve line structure

---

## 8. Common Issues & Fixes

### Issue: "Extension verification failed"

**Symptom:**
```
[ERROR] Extension Detector verification failed
[ERROR] Hive Extension Detector not found in Chrome
```

**Cause:** The Hive Extension Detector Chrome extension is not installed or disabled.

**Fix:**
1. Open Chrome
2. Visit: https://chrome.google.com/webstore/
3. Search: "Hive Extension Detector"
4. Click "Add to Chrome"
5. Confirm permission prompt
6. Verify extension appears in Chrome menu (top-right)
7. Re-run bot: `python -m src.main`

---

### Issue: "Login failed"

**Symptom:**
```
[ERROR] Login verification failed
[ERROR] Could not authenticate with provided credentials
```

**Cause:** Invalid credentials or wrong login URL.

**Fix:**
1. Verify `.env` has correct values:
   - `HIVE_USERNAME` - your actual Hive username
   - `HIVE_PASSWORD` - your actual Hive password
   - `HIVE_LOGIN_URL` - complete URL (e.g., `https://hive.com/login`)
2. Test manually:
   - Open Chrome
   - Go to `HIVE_LOGIN_URL`
   - Try login with same credentials
   - If manual login works, issue is in bot code
   - If manual login fails, credentials are wrong
3. If URL is wrong, check what URL shows after login succeeds
4. Update `.env` with correct URL
5. Re-run bot

---

### Issue: "Browser won't open / Chrome not found"

**Symptom:**
```
[ERROR] Failed to launch browser
[ERROR] Chrome executable not found
```

**Cause:** Playwright can't find Chrome executable, or Chrome isn't installed.

**Fix:**
1. Verify Chrome is installed:
   - Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`
   - macOS: `/Applications/Google Chrome.app`
   - Linux: Run `which google-chrome`
2. If Chrome is installed, reinstall Playwright:
   ```bash
   python -m playwright install
   python -m playwright install-deps  # On Linux
   ```
3. Try explicit headless mode (simpler):
   ```bash
   python -m src.main --headless
   ```

---

### Issue: "Problem list not detected"

**Symptom:**
```
[ERROR] Problem list container not found
[ERROR] Could not locate problem elements on page
```

**Cause:** Selectors in `ui_constants.py` don't match actual page structure.

**Fix:**
1. Open browser manually and check URL:
   - Are you on the correct page showing problems?
   - Example: `https://hive.com/contests/123/problems`
2. Open DevTools (F12)
3. In Console tab, test selectors:
   ```javascript
   document.querySelector('div.problems-list')  // Should NOT be null
   document.querySelectorAll('div.problem-card').length  // Should be > 0
   ```
4. If selectors return `null` or empty:
   - Hive may have changed their HTML structure
   - Use element picker to find new selectors
   - Update `ui_constants.py` with new selectors
5. Re-run bot: `python -m src.main`

---

### Issue: "Timeout waiting for element"

**Symptom:**
```
[ERROR] Timeout waiting for problem list to load (10s)
[ERROR] Element did not appear within timeout
```

**Cause:** Page is slow to load or element takes time to render.

**Fix:**
1. Increase timeout in `ui_constants.py`:
   ```python
   ELEMENT_LOAD_TIMEOUT = 20  # Increase from 10 to 20 seconds
   ```
2. Check your internet connection
3. Try with less network traffic
4. Check if Hive site is slow:
   - Open Chrome and manually navigate to Hive
   - Does page load slowly?
   - If yes, issue is Hive's speed, not bot
5. Try debug logging:
   ```bash
   python -m src.main --log-level DEBUG
   ```
   This shows exactly what's waiting for

---

### Issue: "Multiple possible issues, unsure where to start"

**General debugging steps:**

1. **Run with verbose logging:**
   ```bash
   python -m src.main --log-level DEBUG
   ```
   Read output line-by-line to identify failure point.

2. **Check browser manually:**
   - Open Chrome
   - Navigate to same URL bot uses
   - Can you see the problem list?
   - If no, issue is with Hive or login
   - If yes, issue is with bot's DOM selection

3. **Inspect with DevTools:**
   - Open DevTools (F12)
   - Console tab
   - Test selectors directly
   - Confirms if HTML structure matches expectations

4. **Check .env file:**
   - Verify all required fields are filled
   - Check for typos in URLs
   - Ensure no trailing spaces

5. **Try simpler commands:**
   ```bash
   # Start fresh
   python -m src.main --headless
   
   # Or with fresh profile
   rm -rf ~/.config/hive_bot  # Remove cached profile
   python -m src.main
   ```

---

## 9. Success Criteria

You've successfully completed Phase 1 when:

- [x] **Phase 1 workflow runs without errors**
  - Bot starts with: `python -m src.main`
  - No exception tracebacks
  - All major steps complete

- [x] **Browser shows problem list page**
  - Chrome window opens
  - Displays Hive problem list
  - Can see multiple problems listed

- [x] **You have documented all selectors**
  - Problem list container ✓
  - Problem cards ✓
  - Problem titles, difficulty, status ✓
  - Status button text variations ✓

- [x] **You understand DOM structure**
  - Can explain how problem data is stored in HTML
  - Can explain how status is determined
  - Know where problem IDs come from

- [x] **ui_constants.py is fully updated**
  - All selectors added from discovery
  - Includes comments and dates
  - Tests show selectors work

- [x] **You can explain each selector choice**
  - Why each CSS selector was chosen
  - What it matches on the page
  - How it's used in the extraction code

---

## 10. Next Steps

Once Phase 1 discoveries are complete:

### Step 1: Document Findings

Create a file `PHASE1_DISCOVERIES.md` recording:
- Date of testing
- Chrome version used
- Selectors found
- Any unexpected findings
- Screenshots (optional)

### Step 2: Update ui_constants.py

Using the template in Section 7:
- Add all discovered selectors
- Include comments explaining each
- Test each selector in console before finalizing

### Step 3: Commit Changes

```bash
git add src/hive/ui_constants.py PHASE1_DISCOVERIES.md
git commit -m "Phase 1: Document discovered DOM selectors"
git push origin phase-1-discovery
```

### Step 4: Proceed to Phase 2

Phase 2 implements problem extraction using discovered selectors:

```bash
python -m src.main --phase 2
```

This will:
- Use selectors from `ui_constants.py`
- Extract problem data from page
- Save problems to `data/problems/`
- Verify extraction accuracy

### Step 5: Implement Phase 2 Tasks

Based on selector discoveries:
1. Implement `problem_list.extract_problems()`
2. Use discovered selectors to parse DOM
3. Build Problem objects with title, difficulty, ID
4. Test extraction with sample problems

---

## 11. Appendix: Useful Browser DevTools Tips

### Keyboard Shortcuts

| Action | Shortcut (Windows/Linux) | Shortcut (macOS) |
|--------|--------------------------|------------------|
| Open DevTools | `F12` or `Ctrl+Shift+I` | `Cmd+Option+I` |
| Element Picker | `Ctrl+Shift+C` | `Cmd+Shift+C` |
| Find in page | `Ctrl+F` | `Cmd+F` |
| Console tab | `Ctrl+Shift+J` | `Cmd+Option+J` |
| Take screenshot | `Ctrl+Shift+P` | `Cmd+Shift+P` |
| Toggle DevTools | `F12` | `F12` |

### Right-Click Context Menu (on elements)

Right-click any element in DevTools to:

**Copy selector:**
- `Inspect` → Right-click element → `Copy` → `Copy selector`
- Returns CSS selector like: `.problems-list > .problem-card:nth-child(2)`

**Copy XPath:**
- Right-click element → `Copy` → `Copy full XPath`
- Returns XPath like: `//*[@class="problem-card"][1]`

**Edit as HTML:**
- Right-click element → `Edit as HTML`
- Temporarily modify HTML to test changes
- Useful for testing alternate selectors

### Console Commands

Useful JavaScript commands in Console tab:

```javascript
// Find element by selector
document.querySelector('.problems-list')
// Returns: <div class="problems-list">...</div>

// Find all matching elements
document.querySelectorAll('.problem-card')
// Returns: NodeList [div.problem-card, div.problem-card, ...]

// Count matching elements
document.querySelectorAll('.problem-card').length
// Returns: 25

// Get text content of element
document.querySelector('.problem-title').textContent
// Returns: "Array Basics"

// Get attribute value
document.querySelector('.problem-card').getAttribute('data-problem-id')
// Returns: "123"

// Find by XPath
document.evaluate("//button[contains(text(), 'Solve')]", document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength
// Returns: 10

// Get computed styles
window.getComputedStyle(document.querySelector('.problem-card')).display
// Returns: "flex"
```

### Advanced: Setting Breakpoints

1. Open DevTools → **Sources** tab
2. Click line number to add breakpoint
3. When code reaches that line, execution pauses
4. Inspect variables in **Scope** panel
5. Step through code with **Step over** / **Step into** buttons

This is advanced and optional for Phase 1, but useful for debugging Phase 2.

### Taking Screenshots

1. Open DevTools (F12)
2. Press `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (macOS)
3. Search: "screenshot"
4. Choose:
   - **Capture screenshot** - Current viewport
   - **Capture full page screenshot** - Entire scrollable page
5. Screenshot saves to Downloads folder

---

## 12. Troubleshooting Checklist

If Phase 1 isn't working, work through this checklist:

- [ ] Chrome browser is installed (not Chromium)
- [ ] Hive Extension Detector is installed in Chrome
- [ ] `.env` file exists and has correct credentials
- [ ] `HIVE_LOGIN_URL` is correct (check in browser)
- [ ] `HIVE_USERNAME` and `HIVE_PASSWORD` work manually
- [ ] Playwright is installed: `python -m playwright install`
- [ ] All dependencies installed: `pip install -r requirements.txt`
- [ ] Python 3.10+ is being used: `python --version`
- [ ] Bot runs with: `python -m src.main`
- [ ] Browser opens and loads page
- [ ] No extension errors in browser console
- [ ] Login succeeds (verify in browser)
- [ ] Problem list is visible (see actual problems)

If stuck on any point:
1. Run with debug logging: `python -m src.main --log-level DEBUG`
2. Read the output line-by-line
3. Find the first `[ERROR]` message
4. Search this guide for that error in Section 8
5. Follow the fix instructions

---

## 13. Final Checklist

Before considering Phase 1 complete:

- [ ] Bot runs successfully start-to-finish
- [ ] Browser displays the problem list page
- [ ] All selectors documented in `ui_constants.py`
- [ ] Selectors tested in browser console
- [ ] Understand what each selector does
- [ ] Know how to use DevTools element picker
- [ ] Can identify new selectors if page changes
- [ ] Ready to implement Phase 2 extraction

---

## Additional Resources

- [Playwright Documentation](https://playwright.dev/python/)
- [Chrome DevTools Guide](https://developer.chrome.com/docs/devtools/)
- [CSS Selectors Reference](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Selectors)
- [XPath Tutorial](https://www.w3schools.com/xml/xpath_intro.asp)

---

**Last Updated:** 2024
**Phase:** 1 - Foundation & Discovery
**Status:** Ready for Live Testing
