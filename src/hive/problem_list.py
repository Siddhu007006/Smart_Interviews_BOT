"""
Problem list detection and parsing for Hive platform.

Detects problem list page and provides interfaces for future
problem extraction and navigation (Phase 2+).
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from playwright.async_api import Page

from src.utils import get_logger, DOMError, LogContext
from .dom_queries import DOMInspector

logger = get_logger(__name__)


@dataclass
class Problem:
    """
    Represents a Hive problem metadata.
    
    Attributes:
        problem_id: Unique problem identifier
        title: Problem title
        difficulty: Difficulty level (Easy, Medium, Hard)
        category: Problem category/topic
        solved: Whether problem is already solved
    """
    problem_id: str
    title: str
    difficulty: Optional[str] = None
    category: Optional[str] = None
    solved: bool = False

    def __repr__(self) -> str:
        status = "✓" if self.solved else "○"
        return f"{status} Problem(id={self.problem_id}, title={self.title})"


class ProblemListDetector:
    """
    Detects and interacts with Hive problem list page.
    
    Phase 1: Detect problem list page
    Phase 2+: Extract problem metadata, navigate to problems
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

    async def is_on_problem_list_page(self) -> bool:
        """
        Detect if currently on problem list page.
        
        Uses observable page indicators:
        - URL pattern
        - Page title
        - Presence of problem list elements
        
        Returns:
            True if on problem list page, False otherwise
        """
        with LogContext("Detecting problem list page"):
            try:
                url = self.page.url
                logger.debug(f"Current URL: {url}")

                # Check URL patterns (common indicators)
                common_patterns = [
                    "/problems",
                    "/contests",
                    "/dashboard",
                    "/home",
                ]

                on_problem_page = any(pattern in url for pattern in common_patterns)

                if on_problem_page:
                    logger.info("✓ Detected problem list page from URL")
                    return True

                # Check page title
                title = await self.page.title()
                logger.debug(f"Page title: {title}")

                if any(word in title.lower() for word in ["problem", "challenge", "contest"]):
                    logger.info("✓ Detected problem list page from title")
                    return True

                # If no obvious indicators, log for inspection
                logger.warning("Could not definitively detect problem list page")
                await self.inspector.log_dom_snapshot("Problem list detection")

                return False

            except Exception as e:
                logger.error(f"Error detecting problem list page: {e}")
                return False

    async def get_unsolved_count(self) -> int:
        """
        Get count of unsolved problems.
        
        Phase 2+ implementation: Extract from DOM
        Phase 1: Placeholder
        
        Returns:
            Count of unsolved problems (0 for Phase 1)
        """
        with LogContext("Getting unsolved problem count"):
            logger.info("Phase 1: Unsolved count detection not implemented")
            logger.info("Phase 2 will extract problem count from DOM")
            return 0

    async def fetch_problems(self) -> List[Problem]:
        """
        Fetch list of problems from page.
        
        Phase 2+ implementation: Parse problem list
        Phase 1: Placeholder
        
        Returns:
            List of Problem objects (empty for Phase 1)
        """
        with LogContext("Fetching problem list"):
            logger.info("Phase 1: Problem extraction not implemented")
            logger.info("Phase 2 will query DOM and extract problems")
            logger.info("Expected workflow:")
            logger.info("  1. Find problem list container via discovered selectors")
            logger.info("  2. Extract individual problem cards")
            logger.info("  3. Parse metadata (title, difficulty, status)")
            return []

    async def navigate_to_problem(self, problem_id: str) -> bool:
        """
        Navigate to specific problem page.
        
        Phase 2+ implementation: Click problem link
        Phase 1: Placeholder
        
        Args:
            problem_id: Problem identifier
            
        Returns:
            True if navigation successful (Phase 2+)
        """
        with LogContext(f"Navigating to problem {problem_id}"):
            logger.info("Phase 1: Problem navigation not implemented")
            logger.info("Phase 2 will click problem link and wait for page load")
            return False

    async def extract_problem_metadata(self, element_handle) -> Optional[Problem]:
        """
        Extract metadata from problem card element.
        
        Phase 2+ implementation: Parse element
        Phase 1: Placeholder
        
        Args:
            element_handle: Playwright ElementHandle
            
        Returns:
            Problem object or None if parsing fails
        """
        with LogContext("Extracting problem metadata"):
            logger.info("Phase 1: Metadata extraction not implemented")
            logger.info("Phase 2 will parse element attributes and text")
            return None

    async def parse_problem_details(self) -> Optional[Dict[str, Any]]:
        """
        Parse detailed problem information from problem page.
        
        Phase 2+ implementation: Extract statement, constraints, examples
        Phase 1: Placeholder
        
        Returns:
            Dictionary with problem details or None
        """
        with LogContext("Parsing problem details"):
            logger.info("Phase 1: Problem detail parsing not implemented")
            logger.info("Phase 2 will extract:")
            logger.info("  - Problem statement")
            logger.info("  - Input/output constraints")
            logger.info("  - Example test cases")
            return None

    # ===== Method signatures for Phase 2+ (not implemented) =====

    async def detect_editor_type(self) -> Optional[str]:
        """Detect editor type on problem page (Phase 2+)"""
        logger.debug("Editor detection scheduled for Phase 2")
        return None

    async def get_problem_statement(self) -> Optional[str]:
        """Get problem statement text (Phase 2+)"""
        logger.debug("Problem statement parsing scheduled for Phase 2")
        return None

    async def get_test_examples(self) -> List[tuple]:
        """Get test input/output examples (Phase 2+)"""
        logger.debug("Test example extraction scheduled for Phase 2")
        return []
