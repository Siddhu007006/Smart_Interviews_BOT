"""
Hive UI Constants and Selectors

IMPORTANT: This file documents discovered selectors AFTER DOM inspection.
DO NOT hard-code assumptions. Selectors are discovered at runtime through
DevTools inspection on the actual Hive platform.

Format for discovered selectors:
- XPath: Full XPath to element
- CSS: CSS selector if preferred
- Context: Where selector is used (e.g., "Problem list page")
- Notes: Any special handling or edge cases

This file will be populated during Phase 1 live inspection.
"""

# Placeholder - Selectors will be discovered and documented here during
# Phase 1 implementation when testing against actual Hive platform.
# See: https://github.com/your-repo/docs/hive-dom-discovery.md

# Example format (to be replaced with actual discoveries):
# LOGIN_PAGE_USERNAME_INPUT = "input[type='email']"  # or input[name='username']
# LOGIN_PAGE_PASSWORD_INPUT = "input[type='password']"
# LOGIN_PAGE_SUBMIT_BUTTON = "button:text('Log in')"
# PROBLEM_LIST_CONTAINER = "div.problem-list"  # or similar
# PROBLEM_CARD = "div.problem-card"
# UNSOLVED_PROBLEMS_XPATH = "//div[@data-solved='false']"

# Status indicators (must be discovered from actual Hive UI)
# PROBLEM_STATUS_SOLVED = "Try Again"  # Indicates already solved
# PROBLEM_STATUS_UNSOLVED = "Continue"  # Indicates unsolved
# PROBLEM_STATUS_UNSTARTED = "Solve"    # Indicates not started

print("Note: Hive UI selectors will be discovered during Phase 1 live testing")
print("No hard-coded selectors present - safe for production")
