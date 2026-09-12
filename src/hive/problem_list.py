"""
Problem list detection and parsing for Hive platform.

Implements Phase 2:
- Contest dashboard navigation
- Continue Contest button clicking
- Problem list detection
- Empirical DOM extraction for problem cards (title, url, score, solved status)
- Solved / unsolved classification
- Pagination readiness
"""

import asyncio
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from playwright.async_api import Page

from src.utils import get_logger, DOMError, LogContext
from .dom_queries import DOMInspector
from .ui_constants import (
    CONTEST_CONTINUE_BUTTON,
    CONTEST_EXTENSION_BLOCKER,
    PROBLEM_ROW_CONTAINER,
    PROBLEM_ACTION_BUTTON,
    PROBLEM_ACCEPTED_CHECKMARK,
    PROBLEM_TITLE_LINK,
    PAGINATOR_CONTAINER,
    NEXT_PAGE_BUTTON,
)

logger = get_logger(__name__)


@dataclass
class Problem:
    """
    Represents a Hive problem metadata with exact classification by action button text.
    
    Attributes:
        problem_id: Unique problem identifier / slug
        title: Problem title
        url: Full or relative problem URL
        score: Score integer (e.g. 20)
        action_button_text: Exact action button text ("Try Again", "Continue", "Solve")
        status_icon: Status icon type ("green_tick", "yellow_exclamation", "yellow_partial_tick", "open", "bookmark", "mail", None)
        classification: Problem classification ("SOLVED", "UNSOLVED_CONTINUE", "UNSOLVED_SOLVE", "UNKNOWN")
        solved: Whether problem is solved (True if classification == "SOLVED")
        status: String status ("Accepted" or "Unsolved") — deprecated, use classification instead
        difficulty: Optional difficulty level (Easy, Medium, Hard)
        category: Optional problem category/topic
    """
    problem_id: str
    title: str
    url: str
    action_button_text: str  # Exact button text from DOM
    score: int = 0
    status_icon: Optional[str] = None  # Icon type if present
    classification: str = "UNKNOWN"  # SOLVED, UNSOLVED_CONTINUE, UNSOLVED_SOLVE, UNKNOWN
    solved: bool = False  # True if classification == "SOLVED"
    status: str = "Unsolved"  # For backward compatibility
    difficulty: Optional[str] = None
    category: Optional[str] = None

    def __repr__(self) -> str:
        status_icon = "✓" if self.solved else "○"
        return f"{status_icon} Problem(id={self.problem_id}, title='{self.title}', action={self.action_button_text}, classification={self.classification})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for state storage or logging."""
        return {
            "problem_id": self.problem_id,
            "title": self.title,
            "url": self.url,
            "action_button_text": self.action_button_text,
            "score": self.score,
            "status_icon": self.status_icon,
            "classification": self.classification,
            "solved": self.solved,
            "status": self.status,
            "difficulty": self.difficulty,
            "category": self.category,
        }


class ProblemListDetector:
    """
    Detects and interacts with Hive contest pages and problem list.
    
    Provides:
    - Navigation to contest dashboard
    - Continue Contest click handling
    - Robust problem list detection
    - Real DOM problem extraction and classification
    - Pagination support
    """

    def __init__(self, page: Page):
        """
        Initialize ProblemListDetector.
        
        Args:
            page: Playwright Page object
        """
        self.page = page
        self.inspector = DOMInspector(page)
        logger.debug("ProblemListDetector initialized")

    async def navigate_to_contest(self, contest_url: str, timeout_ms: int = 30000) -> bool:
        """
        Navigate to contest dashboard page and wait for Angular render.
        
        Args:
            contest_url: URL to the contest dashboard.
            timeout_ms: Timeout in milliseconds.

        Returns:
            True if navigation succeeded.
        """
        with LogContext(f"Navigating to contest: {contest_url}"):
            try:
                logger.info(f"Navigating to contest dashboard: {contest_url}")
                await self.page.goto(contest_url, wait_until="domcontentloaded", timeout=timeout_ms)
                # Allow Angular SPA and extension checks to settle
                await asyncio.sleep(3.0)
                logger.info(f"Contest dashboard loaded: {self.page.url}")
                return True
            except Exception as e:
                logger.error(f"Failed to navigate to contest: {e}")
                return False

    async def click_continue_contest(self, timeout_ms: int = 15000) -> bool:
        """
        Locate and click the 'Continue Contest' or 'Start Contest' button.
        Waits for navigation to the problems page.
        
        Args:
            timeout_ms: Timeout in milliseconds to wait for button.

        Returns:
            True if button was clicked and problem list page reached.
        """
        with LogContext("Clicking Continue Contest"):
            try:
                # First check if already on the problems page
                if await self.is_on_problem_list_page():
                    logger.info("Already on problem list page — skipping Continue Contest click.")
                    return True

                # Locate Continue Contest button
                btn = self.page.locator(CONTEST_CONTINUE_BUTTON)
                if await btn.count() == 0:
                    # Try text regex locator as fallback
                    btn = self.page.locator("text=/Continue Contest|Start Contest/i")

                if await btn.count() == 0:
                    logger.warning("Continue Contest button not found in DOM.")
                    return False

                # Ensure button is visible
                first_btn = btn.first
                if not await first_btn.is_visible():
                    logger.warning("Continue Contest button is not visible.")
                    return False

                logger.info("Clicking Continue Contest button...")
                await first_btn.click(timeout=timeout_ms)

                # Wait for Angular router transition to /problems
                try:
                    await self.page.wait_for_url("**/problems*", timeout=timeout_ms)
                except Exception:
                    logger.debug("wait_for_url timed out or URL pattern did not match immediately; checking state...")

                await asyncio.sleep(2.0)
                logger.info(f"Page URL after Continue Contest click: {self.page.url}")
                return await self.is_on_problem_list_page()

            except Exception as e:
                logger.error(f"Error clicking Continue Contest button: {e}")
                return False

    async def is_on_problem_list_page(self) -> bool:
        """
        Detect if currently on problem list page.
        
        Uses observable page indicators:
        - URL pattern (/contests/.../problems or /problems)
        - Page title or headings
        - Presence of problem rows or Try Again/Solve action buttons
        
        Returns:
            True if on problem list page, False otherwise
        """
        with LogContext("Detecting problem list page"):
            try:
                url = self.page.url
                logger.debug(f"Current URL: {url}")

                # Check URL patterns
                if "/problems" in url:
                    logger.info("✓ Detected problem list page from URL (/problems)")
                    return True

                # Check for problem action buttons in DOM
                action_btn_count = await self.page.locator(PROBLEM_ACTION_BUTTON).count()
                if action_btn_count > 0:
                    logger.info(f"✓ Detected problem list page from DOM ({action_btn_count} problem buttons found)")
                    return True

                return False

            except Exception as e:
                logger.error(f"Error detecting problem list page: {e}")
                return False

    async def fetch_problems(self) -> List[Problem]:
        """
        Fetch and parse list of problems from the current problem list page.
        
        Uses empirical DOM extraction:
        - Finds problem rows / cards
        - Extracts title, URL link, score, action button text, status icon
        - Classifies each problem by action button text (Try Again, Continue, Solve)
        
        Returns:
            List of Problem objects with exact classification
        """
        with LogContext("Fetching problem list"):
            try:
                # Evaluate in page context to extract structured problem data
                raw_problems = await self.page.evaluate(r'''() => {
                    const results = [];
                    
                    // Find action buttons: exact text matching only (not substring)
                    // "Try Again" = green tick (solved)
                    // "Continue" = previously attempted (unsolved)
                    // "Solve" = never attempted (unsolved)
                    const buttons = Array.from(document.querySelectorAll("button, a")).filter(el => {
                        const t = (el.innerText || "").trim();
                        return /^Try Again$/i.test(t) || /^Solve$/i.test(t) || /^Continue$/i.test(t);
                    });

                    for (const btn of buttons) {
                        const btnText = (btn.innerText || "").trim();

                        // Find enclosing container (card / row)
                        let container = btn.parentElement;
                        for (let i = 0; i < 6; i++) {
                            if (!container) break;
                            if (container.querySelector("h2, h3, h4, .title, a[href*='problem']")) {
                                break;
                            }
                            container = container.parentElement;
                        }

                        if (!container) continue;

                        // Title element - prioritize .problem-title before falling back to generic headings or links
                        const titleEl = container.querySelector(".problem-title, h2, h3, h4, .title") || container.querySelector("a[href*='problem']");
                        let title = titleEl ? titleEl.innerText.trim() : "";
                        if (!title || /^try again$/i.test(title) || /^solve$/i.test(title) || /^continue$/i.test(title)) {
                            const pTitle = container.querySelector(".problem-title");
                            if (pTitle) title = pTitle.innerText.trim();
                        }
                        if (!title) continue;

                        // Problem Link / Href - use actual DOM href (authoritative)
                        let href = "";
                        if (titleEl && titleEl.tagName === "A" && titleEl.href) {
                            href = titleEl.href;
                        } else {
                            const anyLink = container.querySelector("a[href*='problem']");
                            if (anyLink && anyLink.href) {
                                href = anyLink.href;
                            } else if (btn.tagName === "A" && btn.href) {
                                href = btn.href;
                            }
                        }

                        // Status icon detection
                        let statusIcon = null;
                        const checkmark = container.querySelector("mat-icon, svg, [class*='check'], [class*='success'], [mattooltip*='Accepted']");
                        
                        // Detect icon type from class names, colors, or content
                        if (checkmark) {
                            const classList = checkmark.className || "";
                            const style = window.getComputedStyle(checkmark);
                            const color = style.color || style.fill || "";
                            const innerHTML = checkmark.innerHTML || "";
                            
                            // Green tick
                            if (color.includes("rgb(76, 175, 80)") || color.includes("green") || classList.includes("success") || classList.includes("accepted")) {
                                statusIcon = "green_tick";
                            }
                            // Yellow exclamation
                            else if (color.includes("rgb(255, 193, 7)") || color.includes("yellow") || innerHTML.includes("error") || innerHTML.includes("warning")) {
                                statusIcon = "yellow_exclamation";
                            }
                            // Yellow partial tick
                            else if (innerHTML.includes("schedule") || innerHTML.includes("partial")) {
                                statusIcon = "yellow_partial_tick";
                            }
                            // Other icons (open, bookmark, mail)
                            else if (innerHTML.includes("open_in_new") || classList.includes("open")) {
                                statusIcon = "open";
                            } else if (innerHTML.includes("bookmark") || classList.includes("bookmark")) {
                                statusIcon = "bookmark";
                            } else if (innerHTML.includes("mail") || classList.includes("mail")) {
                                statusIcon = "mail";
                            }
                        }

                        // Score extraction (e.g. "Score: 20")
                        let score = 0;
                        const fullText = container.innerText || "";
                        const scoreMatch = fullText.match(/Score:\s*(\d+)/i);
                        if (scoreMatch) {
                            score = parseInt(scoreMatch[1], 10);
                        }

                        // Generate slug from title if href has no specific problem id
                        let problemId = "";
                        if (href) {
                            const parts = href.split("/problems/");
                            if (parts.length > 1) {
                                problemId = parts[1].split("?")[0].split("/")[0];
                            }
                        }
                        if (!problemId) {
                            problemId = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
                        }

                        results.push({
                            problem_id: problemId,
                            title: title,
                            url: href || window.location.href,
                            score: score,
                            action_button_text: btnText,
                            status_icon: statusIcon,
                        });
                    }

                    return results;
                }''')

                problems: List[Problem] = []
                seen_ids = set()

                for raw in raw_problems:
                    pid = raw["problem_id"]
                    if pid in seen_ids:
                        continue
                    seen_ids.add(pid)

                    # Classify problem by action button text (exact rules)
                    action_text = raw["action_button_text"]
                    status_icon = raw["status_icon"]
                    classification = "UNKNOWN"
                    solved = False

                    if action_text:
                        action_lower = action_text.lower().strip()
                        
                        # Rule 1: Green tick + "Try Again" = SOLVED
                        if "try again" in action_lower and status_icon == "green_tick":
                            classification = "SOLVED"
                            solved = True
                        
                        # Rule 2: Any icon + "Continue" = UNSOLVED_CONTINUE (icon doesn't matter)
                        elif "continue" in action_lower:
                            classification = "UNSOLVED_CONTINUE"
                            solved = False
                        
                        # Rule 3: "Solve" button = UNSOLVED_SOLVE (never attempted)
                        elif "solve" in action_lower:
                            classification = "UNSOLVED_SOLVE"
                            solved = False
                        
                        # Edge case: "Try Again" without green tick should be treated as SOLVED
                        # (Hive rules: "Try Again" is only shown after acceptance)
                        elif "try again" in action_lower:
                            classification = "SOLVED"
                            solved = True

                    problem = Problem(
                        problem_id=pid,
                        title=raw["title"],
                        url=raw["url"],
                        score=raw.get("score", 0),
                        action_button_text=action_text,
                        status_icon=status_icon,
                        classification=classification,
                        solved=solved,
                        status="Accepted" if solved else "Unsolved",
                    )
                    problems.append(problem)

                logger.info(f"✓ Extracted {len(problems)} problems from DOM.")
                
                # Log classification breakdown
                solved_count = sum(1 for p in problems if p.classification == "SOLVED")
                continue_count = sum(1 for p in problems if p.classification == "UNSOLVED_CONTINUE")
                solve_count = sum(1 for p in problems if p.classification == "UNSOLVED_SOLVE")
                unknown_count = sum(1 for p in problems if p.classification == "UNKNOWN")
                
                logger.info(
                    f"Classification breakdown: "
                    f"Solved={solved_count}, "
                    f"Continue={continue_count}, "
                    f"Solve={solve_count}, "
                    f"Unknown={unknown_count}"
                )

                return problems

            except Exception as e:
                logger.error(f"Error fetching problems from DOM: {e}")
                return []

    async def get_unsolved_count(self) -> int:
        """Get count of unsolved problems on current page."""
        problems = await self.fetch_problems()
        return sum(1 for p in problems if p.classification in ("UNSOLVED_CONTINUE", "UNSOLVED_SOLVE"))

    async def get_solved_count(self) -> int:
        """Get count of solved problems on current page."""
        problems = await self.fetch_problems()
        return sum(1 for p in problems if p.classification == "SOLVED")

    async def get_unsolved_problems(self) -> List[Problem]:
        """Get all unsolved Problem objects on current page (UNSOLVED_CONTINUE or UNSOLVED_SOLVE)."""
        problems = await self.fetch_problems()
        return [p for p in problems if p.classification in ("UNSOLVED_CONTINUE", "UNSOLVED_SOLVE")]

    async def get_continue_problems(self) -> List[Problem]:
        """Get all UNSOLVED_CONTINUE problems on current page (previously attempted, highest priority)."""
        problems = await self.fetch_problems()
        return [p for p in problems if p.classification == "UNSOLVED_CONTINUE"]

    async def get_solve_problems(self) -> List[Problem]:
        """Get all UNSOLVED_SOLVE problems on current page (never attempted, lower priority)."""
        problems = await self.fetch_problems()
        return [p for p in problems if p.classification == "UNSOLVED_SOLVE"]

    def classify_problem(self, problem: Problem) -> str:
        """
        Classify a single problem by its action button text and icon.
        
        Classification rules (authoritative):
        - Green tick + "Try Again"              → SOLVED
        - Any icon + "Continue"                 → UNSOLVED_CONTINUE
        - "Solve"                               → UNSOLVED_SOLVE
        - Unknown                               → UNKNOWN
        
        Args:
            problem: Problem object with action_button_text and status_icon
            
        Returns:
            Classification string: "SOLVED", "UNSOLVED_CONTINUE", "UNSOLVED_SOLVE", "UNKNOWN"
        """
        if not problem.action_button_text:
            return "UNKNOWN"
        
        action_lower = problem.action_button_text.lower().strip()
        
        # Rule 1: Green tick + "Try Again" = SOLVED (only solution to consider solved)
        if "try again" in action_lower and problem.status_icon == "green_tick":
            return "SOLVED"
        
        # Rule 2: Any icon + "Continue" = UNSOLVED_CONTINUE (ignore icon, Continue means unsolved)
        elif "continue" in action_lower:
            return "UNSOLVED_CONTINUE"
        
        # Rule 3: "Solve" = UNSOLVED_SOLVE (never attempted)
        elif "solve" in action_lower:
            return "UNSOLVED_SOLVE"
        
        # Edge case: "Try Again" without icon should be SOLVED (Hive always shows green tick with Try Again)
        elif "try again" in action_lower:
            return "SOLVED"
        
        else:
            return "UNKNOWN"

    async def navigate_to_problem(self, problem: Problem | str) -> bool:
        """
        Navigate to specific problem page.
        
        Args:
            problem: Problem object or problem_id / url
            
        Returns:
            True if navigation successful
        """
        target_url = problem.url if isinstance(problem, Problem) else problem
        with LogContext(f"Navigating to problem {target_url}"):
            try:
                logger.info(f"Navigating to problem URL: {target_url}")
                await self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2.0)
                return True
            except Exception as e:
                logger.error(f"Failed to navigate to problem: {e}")
                return False

    async def go_to_first_page(self, contest_url: Optional[str] = None) -> bool:
        """
        Navigate to page 1 of the problem list unconditionally.

        Strategy (two-step fallback):
          1. If contest_url is provided, navigate directly to the /problems URL.
             A fresh page.goto() to the problems URL always gives page 1 —
             the Angular paginator is reset on hard navigation.
          2. If no URL is available, try clicking the 'First page' button on the
             Angular Material paginator.  If that button is absent (we are already
             on page 1) this is a no-op and returns True.

        This MUST be called immediately before the solve loop to guarantee that
        the bot starts from page 1 regardless of where the browser was left.

        Returns:
            True if browser is on page 1, False on failure.
        """
        try:
            if contest_url:
                # Build the /problems URL from the contest URL
                problems_url = contest_url.rstrip("/")
                if not problems_url.endswith("/problems"):
                    problems_url = problems_url + "/problems"

                logger.info(f"[go_to_first_page] Hard-navigating to {problems_url} (resets paginator to page 1)")
                await self.page.goto(problems_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3.0)
                logger.info(f"[go_to_first_page] ✓ Now on: {self.page.url}")
                return True

            # Fallback: try the Material paginator 'First page' button
            first_btn = self.page.locator(
                "button[aria-label='First page'], .mat-paginator-navigation-first"
            )
            if await first_btn.count() > 0 and await first_btn.first.is_enabled():
                logger.info("[go_to_first_page] Clicking 'First page' paginator button")
                await first_btn.first.click()
                await asyncio.sleep(2.0)
                return True

            # Already on page 1 (no first-page button = paginator is at the start)
            logger.info("[go_to_first_page] No 'First page' button — already on page 1")
            return True

        except Exception as e:
            logger.error(f"[go_to_first_page] Failed: {e}")
            return False

    async def has_next_page(self) -> bool:

        """Check if paginator has a next page available."""
        try:
            next_btn = self.page.locator(NEXT_PAGE_BUTTON)
            if await next_btn.count() > 0:
                is_disabled = await next_btn.first.get_attribute("disabled")
                return is_disabled is None
            return False
        except Exception:
            return False

    async def go_to_next_page(self) -> bool:
        """
        Navigate to the next page in the problem list.

        Advancement verification: records the current URL and problem IDs
        *before* clicking Next, then checks both changed afterwards.
        If the page did not actually advance (same URL and same IDs),
        logs a warning and returns False to terminate the pagination loop.

        Returns:
            True if pagination successfully advanced to a new page.
            False if no next page is available or advancement failed.
        """
        try:
            if not await self.has_next_page():
                logger.info("Pagination: no Next page button available — loop terminates.")
                return False

            # Snapshot state before click
            prev_url = self.page.url
            prev_problems = await self.fetch_problems()
            prev_ids = frozenset(p.problem_id for p in prev_problems)

            next_btn = self.page.locator(NEXT_PAGE_BUTTON).first
            await next_btn.click()
            await asyncio.sleep(2.0)

            new_url = self.page.url
            new_problems = await self.fetch_problems()
            new_ids = frozenset(p.problem_id for p in new_problems)

            # Verify page actually advanced
            if new_url == prev_url and new_ids == prev_ids:
                logger.warning(
                    "go_to_next_page(): page did NOT advance after Next click "
                    f"(URL still {new_url}, same {len(new_ids)} problem IDs). "
                    "Terminating pagination to prevent infinite loop."
                )
                return False

            logger.info(f"✓ Pagination advanced: {prev_url} → {new_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to navigate to next page: {e}")
            return False

