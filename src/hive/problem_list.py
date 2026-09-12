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
    Represents a Hive problem metadata.
    
    Attributes:
        problem_id: Unique problem identifier / slug
        title: Problem title
        url: Full or relative problem URL
        score: Score integer (e.g. 20)
        solved: Whether problem is already solved
        status: String status ("Accepted" or "Unsolved")
        difficulty: Optional difficulty level (Easy, Medium, Hard)
        category: Optional problem category/topic
    """
    problem_id: str
    title: str
    url: str
    score: int = 0
    solved: bool = False
    status: str = "Unsolved"
    difficulty: Optional[str] = None
    category: Optional[str] = None

    def __repr__(self) -> str:
        status_icon = "✓" if self.solved else "○"
        return f"{status_icon} Problem(id={self.problem_id}, title='{self.title}', score={self.score}, solved={self.solved})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for state storage or logging."""
        return {
            "problem_id": self.problem_id,
            "title": self.title,
            "url": self.url,
            "score": self.score,
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
        - Extracts title, URL link, score
        - Detects solved status from checkmark icon / 'Try Again' button text
        
        Returns:
            List of Problem objects
        """
        with LogContext("Fetching problem list"):
            try:
                # Evaluate in page context to extract structured problem data
                raw_problems = await self.page.evaluate(r'''() => {
                    const results = [];
                    // Find action buttons:
                    //   "Try Again" = solved (Accepted), "Solve" = unsolved (never started),
                    //   "Continue" = unsolved (started but not submitted).
                    // Uses ^ and $ anchors for exact text matching — prevents matching
                    // "Continue Contest" or other buttons containing these words as substrings.
                    const buttons = Array.from(document.querySelectorAll("button, a")).filter(el => {
                        const t = (el.innerText || "").trim();
                        return /^Try Again$/i.test(t) || /^Solve$/i.test(t) || /^Continue$/i.test(t);
                    });

                    for (const btn of buttons) {
                        const btnText = (btn.innerText || "").trim();
                        const isSolvedByBtn = /^Try Again$/i.test(btnText);

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
                        if (!title || /^try again$/i.test(title) || /^solve$/i.test(title)) {
                            const pTitle = container.querySelector(".problem-title");
                            if (pTitle) title = pTitle.innerText.trim();
                        }
                        if (!title) continue;

                        // Problem Link / Href
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

                        // Checkmark element (Accepted indicator)
                        const checkmark = container.querySelector("mat-icon, svg, [class*='check'], [class*='success'], [mattooltip*='Accepted']");
                        const isSolved = isSolvedByBtn || (checkmark !== null);

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
                            solved: isSolved,
                            status: isSolved ? "Accepted" : "Unsolved"
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

                    problems.append(
                        Problem(
                            problem_id=pid,
                            title=raw["title"],
                            url=raw["url"],
                            score=raw.get("score", 0),
                            solved=raw.get("solved", False),
                            status=raw.get("status", "Unsolved"),
                        )
                    )

                logger.info(f"✓ Extracted {len(problems)} problems from DOM.")
                solved_count = sum(1 for p in problems if p.solved)
                unsolved_count = len(problems) - solved_count
                logger.info(f"Problem summary: Total={len(problems)}, Solved={solved_count}, Unsolved={unsolved_count}")

                return problems

            except Exception as e:
                logger.error(f"Error fetching problems from DOM: {e}")
                return []

    async def get_unsolved_count(self) -> int:
        """Get count of unsolved problems on current page."""
        problems = await self.fetch_problems()
        return sum(1 for p in problems if not p.solved)

    async def get_solved_count(self) -> int:
        """Get count of solved problems on current page."""
        problems = await self.fetch_problems()
        return sum(1 for p in problems if p.solved)

    async def get_unsolved_problems(self) -> List[Problem]:
        """Get all unsolved Problem objects on current page."""
        problems = await self.fetch_problems()
        return [p for p in problems if not p.solved]

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

