"""
Hive UI Constants and Discovered Selectors.

Empirically discovered from live inspection of the Hive platform:
- Contest dashboard (/contests/<name>)
- Problem list (/contests/<name>/problems)
- Problem viewer (/contests/<name>/problems/<id>)
"""

# Contest Navigation Selectors
CONTEST_CONTINUE_BUTTON = "button:has-text('Continue Contest'), a:has-text('Continue Contest'), button:has-text('Start Contest')"
CONTEST_EXTENSION_BLOCKER = "app-extension-blocker"
CONTEST_EXTENSION_INSTALL_BUTTON = "button:has-text('Install Hive Extension Detector')"

# Problem List Selectors
PROBLEM_ROW_CONTAINER = ".problem, .problem-card, mat-card, [class*='problem-card']"
# "Try Again" = solved, "Solve" / "Continue" = unsolved.
# IMPORTANT: Use text-is() (exact match) for short words like "Continue" and "Solve"
# to avoid matching "Continue Contest" or other buttons containing these words as substrings.
# has-text() is a substring/partial match in Playwright; text-is() requires exact equality.
PROBLEM_ACTION_BUTTON = "button:text-is('Try Again'), button:text-is('Solve'), button:text-is('Continue')"
PROBLEM_ACCEPTED_CHECKMARK = "mat-icon, svg, [class*='check'], [class*='success'], [mattooltip*='Accepted']"
PROBLEM_TITLE_LINK = "h2, h3, h4, .title, a[href*='problem']"

# Pagination
PAGINATOR_CONTAINER = "mat-paginator, .pagination, [class*='paginator']"
NEXT_PAGE_BUTTON = "button[aria-label='Next page'], .mat-paginator-navigation-next, button:has-text('Next')"

# Problem Detail Selectors (Empirically discovered)
PROBLEM_DETAIL_TITLE = "app-question .question-wrapper p, p[style*='font-size: 28px'], .problem-title"
PROBLEM_DETAIL_DESCRIPTION = "div.description"
PROBLEM_DETAIL_CONTAINER = "app-question"

# Language Selector
LANGUAGE_SELECT_CONTAINER = ".language-dropdown mat-select, mat-select[formcontrolname='language']"
LANGUAGE_OPTION = "mat-option, [role='option']"

# Editor & Action Buttons
EDITOR_CONTAINER = "#editor, ngx-monaco-editor#editor"
RUN_CODE_BUTTON = "button:has-text('Run')"
SUBMIT_CODE_BUTTON = "button:has-text('Submit')"
CONSOLE_TOGGLE_BUTTON = "button:has-text('Console')"
CONSOLE_DRAWER = ".console, app-console"
NEXT_UNSOLVED_BUTTON = "button:has-text('Next Unsolved Problem')"
SUBMISSIONS_TAB = "div[role='tab']:has-text('Submissions')"
PROBLEM_TAB = "div[role='tab']:has-text('Problem')"

