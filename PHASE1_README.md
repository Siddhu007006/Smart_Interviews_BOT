# Phase 1: Hive Automation Bot Foundation

## Overview

Phase 1 establishes the core infrastructure for the Hive Automation Bot. It implements:

1. **Configuration System** - Load from files and environment variables
2. **Logging System** - Structured logging with file and console output
3. **Browser Management** - Playwright-based browser control with persistent profiles
4. **Authentication** - Hive platform login workflow
5. **Extension Verification** - Ensures Hive Extension Detector is installed
6. **Session Management** - State persistence and recovery
7. **Problem List Detection** - Detect problem list page
8. **Testing Infrastructure** - Unit tests and test fixtures

## Project Structure

```
hive-bot/
├── src/
│   ├── utils/                  # Core utilities
│   │   ├── config.py          # Configuration loading
│   │   ├── errors.py          # Custom exceptions
│   │   ├── constants.py       # Global constants and enums
│   │   └── logging_config.py  # Logging setup
│   ├── browser/               # Playwright browser management
│   │   ├── manager.py         # BrowserManager class
│   │   └── extension.py       # Extension verification
│   ├── auth/                  # Authentication
│   │   ├── credentials.py     # Credential management
│   │   └── login.py           # Login workflow
│   ├── hive/                  # Hive platform interaction
│   │   ├── dom_queries.py     # Safe DOM inspection
│   │   ├── ui_constants.py    # Discovered selectors (empty for Phase 1)
│   │   └── problem_list.py    # Problem list detection
│   ├── state/                 # State persistence
│   │   ├── models.py          # Data models
│   │   └── manager.py         # State management
│   ├── editor/                # (Phase 2+) Code editor integration
│   ├── solver/                # (Phase 2+) AI solving
│   ├── bot.py                 # Main orchestrator
│   └── main.py                # CLI entry point
├── tests/                     # Test suite
│   ├── conftest.py            # Pytest fixtures
│   ├── test_config.py         # Config tests
│   └── test_browser_manager.py # Browser tests
├── config/
│   └── default_config.yaml    # Default configuration
├── logs/                      # Log files (git-ignored)
├── state/                     # State persistence (git-ignored)
└── requirements.txt           # Python dependencies
```

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

```bash
python -m playwright install
```

### 3. Install Hive Extension Detector

1. Go to Chrome Web Store: https://chrome.google.com/webstore/
2. Search for "Hive Extension Detector"
3. Click "Add to Chrome"
4. Verify it appears in chrome://extensions/

## Configuration

### Environment Variables (Required)

Set these before running the bot:

```bash
export HIVE_LOGIN_URL="https://hive.example.com/login"
export HIVE_USERNAME="your_username@example.com"
export HIVE_PASSWORD="your_password"

# At least one AI provider
export OPENAI_API_KEY="sk-..."  # or
export GEMINI_API_KEY="AIza..."  # or
export GROQ_API_KEY="gsk_..."
```

### Configuration Files

1. **Default Config**: `config/default_config.yaml`
   - Built-in defaults for all settings
   
2. **User Config** (optional): `~/.hive_bot/config.yaml`
   - User-level overrides
   - Takes precedence over default config
   
3. **Environment Variables** (highest priority)
   - Override everything

### Configuration Priority (highest to lowest)

1. Environment variables
2. `~/.hive_bot/config.yaml` (user config)
3. `config/default_config.yaml` (bundled defaults)

## Usage

### Run Phase 1 Workflow

```bash
python -m src.main
```

This performs:
1. Launch browser with persistent profile
2. Verify Hive Extension Detector
3. Perform login
4. Verify authenticated session
5. Detect problem list page
6. Save state for crash recovery

### CLI Options

```bash
python -m src.main --help
```

Options:
- `--config FILE` - Custom config file
- `--headless` - Run in headless mode
- `--dry-run` - Test run (coming in Phase 2)
- `--log-level LEVEL` - DEBUG, INFO, WARNING, ERROR

## Phase 1 Components

### Configuration System (src/utils/config.py)

**ConfigManager** class handles:
- Loading default bundled config
- Merging user config overrides
- Environment variable precedence
- Configuration validation
- Nested key access via dot notation

```python
from src.utils import ConfigManager

config = ConfigManager()
username = config.get("auth.username")
login_url = config.get_required("auth.login_url")
```

### Logging System (src/utils/logging_config.py)

**Features**:
- Console output (INFO level by default)
- File output with rotation (logs/hive_bot.log)
- Structured format with timestamps
- Operation context tracking
- Module-level loggers

```python
from src.utils import setup_logging, get_logger, LogContext

setup_logging()
logger = get_logger(__name__)

with LogContext("Important operation"):
    logger.info("Doing something...")
```

### Browser Management (src/browser/manager.py)

**BrowserManager** class provides:
- Browser launch with persistent Chrome profile
- Context and page management
- Graceful shutdown
- Connection checking
- Crash recovery support

```python
from src.browser import BrowserManager

async with BrowserManager(profile_path, headless=False) as browser:
    page = await browser.get_page()
    await page.goto("https://example.com")
```

### Authentication (src/auth/)

**AuthManager** handles:
- Navigation to login page
- Credential entry (observable page state)
- Login submission
- Authentication verification
- Session validation

```python
from src.auth import AuthManager, Credentials

credentials = Credentials.from_config(config)
auth = AuthManager(page, credentials)
await auth.login()
```

**Key Design**:
- NO hard-coded selectors
- Uses observable page states
- Handles dynamic form layouts
- Robust error reporting

### Extension Verification (src/browser/extension.py)

**ExtensionChecker** ensures:
- Hive Extension Detector is installed
- Extension is enabled
- Other extensions are disabled
- Comprehensive error messages

```python
checker = ExtensionChecker(page)
await checker.verify_extension()
```

### State Management (src/state/)

**StateManager** provides:
- Persistent state storage (JSON files)
- Problem progress tracking
- Atomic writes with file locking
- Crash recovery via checkpoints
- Context manager support

```python
state_manager = StateManager()
state_manager.add_problem("123", "Problem Title")
state_manager.mark_problem_solved("123")
state_manager.save_state()
```

### Problem List Detection (src/hive/problem_list.py)

**ProblemListDetector** includes:
- Problem list page detection
- Observable URL/title patterns
- Placeholder for Phase 2 extraction
- Phase 2+ method signatures

```python
detector = ProblemListDetector(page)
if await detector.is_on_problem_list_page():
    print("On problem list!")
```

### Main Orchestrator (src/bot.py)

**HiveBot** class coordinates:
1. Browser launch
2. Extension verification
3. Login
4. Session verification
5. Problem list detection
6. State persistence

```python
config = ConfigManager()
async with HiveBot(config) as bot:
    success = await bot.run()
```

## Testing

### Run Tests

```bash
pytest tests/ -v
```

### Test Coverage

**test_config.py**:
- Default config loading
- User config merging
- Environment variable override
- Nested key access
- Required value validation

**test_browser_manager.py**:
- Browser initialization
- Browser launch/close
- Context creation
- Page management
- Error handling

## Important Design Principles

### 1. Observable Page State
- NO hard-coded selectors
- Uses page URL, title, and element presence
- Detects authenticated state via UI indicators
- Handles dynamic page layouts

### 2. No Spoofing
- Hive Extension Detector verification is REAL
- Does NOT bypass or fake security checks
- Requires actual browser automation

### 3. Extensibility
- Editor types detected at runtime (Phase 2)
- AI providers via fallback chain
- Problem selectors discovered via DOM inspection
- All configurations from environment/files

### 4. Robustness
- Comprehensive error handling
- Graceful degradation
- State persistence for crash recovery
- Detailed logging for debugging

### 5. Security
- Credentials from environment variables
- No credentials logged
- State file permissions
- HTTPS-only operations

## Important Notes for Phase 1

1. **UI Selectors Empty**: `src/hive/ui_constants.py` is intentionally empty
   - Selectors will be discovered during live testing on Hive platform
   - Prevents hard-coded assumptions about page structure

2. **Extension Verification**: Must be done manually
   - User installs Hive Extension Detector from Chrome Store
   - Bot logs instructions if extension not detected
   - No automation of extension installation (by design)

3. **DOM Inspection**: All DOM queries are observable
   - Query selectors are discovered at runtime
   - No assumptions about element IDs/classes
   - Graceful fallback if selectors change

4. **Phase 2 Placeholders**:
   - `problem_list.py` has method signatures for Phase 2
   - `editor/__init__.py` has planned exports
   - `solver/__init__.py` has planned structure

## Troubleshooting

### Bot Won't Start

1. Check environment variables:
   ```bash
   echo $HIVE_LOGIN_URL
   echo $HIVE_USERNAME
   ```

2. Check configuration file:
   ```bash
   cat config/default_config.yaml
   ```

3. Check logs:
   ```bash
   tail -f logs/hive_bot.log
   ```

### Login Fails

1. Verify credentials are correct
2. Check if Hive Extension Detector is installed
3. Verify page is accessible from your network
4. Check if form layout matches expected patterns

### Extension Verification Fails

1. Install Hive Extension Detector from Chrome Web Store
2. Verify it's enabled in chrome://extensions/
3. Disable other extensions that might conflict

## Next Steps (Phase 2)

Phase 2 will implement:
- Problem extraction from list
- Editor type detection
- Code editor integration
- AI solver pipeline
- Submission handling
- Verdict parsing
- Retry logic

## Contributing

When extending Phase 1:

1. Keep selectors in `ui_constants.py` (discovered, not assumed)
2. Use observable page states (not brittle DOM queries)
3. Log extensively at each step
4. Add tests for new functionality
5. Update documentation

## License

Proprietary - Hive Automation Bot

---

**Phase 1 Status**: ✓ Complete
**Ready for Phase 2**: When configured and tested against actual Hive platform
