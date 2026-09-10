"""
DOM inspection and safe queries for Hive platform.

Provides utilities for:
- Safe element finding with robust error handling
- Logging DOM snapshots on failure
- Observable page state detection
"""

from typing import List, Optional, Any
from playwright.async_api import Page, ElementHandle

from src.utils import get_logger, DOMError, LogContext

logger = get_logger(__name__)


class DOMInspector:
    """
    Provides safe DOM inspection and query utilities.
    
    Features:
    - Robust error handling
    - DOM snapshot logging on failure
    - Observable page state detection
    """

    def __init__(self, page: Page):
        """
        Initialize DOMInspector.
        
        Args:
            page: Playwright Page object
        """
        self.page = page
        logger.debug("DOMInspector initialized")

    async def find_element(
        self,
        selector: str,
        timeout_ms: Optional[int] = None,
    ) -> Optional[ElementHandle]:
        """
        Safely find a single element.
        
        Args:
            selector: CSS or XPath selector
            timeout_ms: Wait timeout in milliseconds
            
        Returns:
            ElementHandle if found, None if not found
        """
        try:
            element = await self.page.query_selector(selector)
            if element:
                logger.debug(f"Found element: {selector}")
            return element

        except Exception as e:
            logger.error(f"Error finding element '{selector}': {e}")
            return None

    async def find_elements(
        self,
        selector: str,
        timeout_ms: Optional[int] = None,
    ) -> List[ElementHandle]:
        """
        Safely find multiple elements.
        
        Args:
            selector: CSS or XPath selector
            timeout_ms: Wait timeout in milliseconds
            
        Returns:
            List of ElementHandle objects (empty if none found)
        """
        try:
            elements = await self.page.query_selector_all(selector)
            logger.debug(f"Found {len(elements)} elements matching: {selector}")
            return elements

        except Exception as e:
            logger.error(f"Error finding elements '{selector}': {e}")
            return []

    async def get_text_content(self, element: ElementHandle) -> Optional[str]:
        """
        Safely get text content from element.
        
        Args:
            element: ElementHandle
            
        Returns:
            Text content or None if error
        """
        try:
            text = await element.text_content()
            return text.strip() if text else None

        except Exception as e:
            logger.error(f"Error getting text content: {e}")
            return None

    async def get_attribute(
        self,
        element: ElementHandle,
        attribute: str,
    ) -> Optional[str]:
        """
        Safely get element attribute.
        
        Args:
            element: ElementHandle
            attribute: Attribute name
            
        Returns:
            Attribute value or None if not found
        """
        try:
            value = await element.get_attribute(attribute)
            return value

        except Exception as e:
            logger.error(f"Error getting attribute '{attribute}': {e}")
            return None

    async def is_visible(self, element: ElementHandle) -> bool:
        """
        Check if element is visible.
        
        Args:
            element: ElementHandle
            
        Returns:
            True if visible, False otherwise
        """
        try:
            return await element.is_visible()

        except Exception as e:
            logger.error(f"Error checking visibility: {e}")
            return False

    async def is_enabled(self, element: ElementHandle) -> bool:
        """
        Check if element is enabled.
        
        Args:
            element: ElementHandle
            
        Returns:
            True if enabled, False otherwise
        """
        try:
            return await element.is_enabled()

        except Exception as e:
            logger.error(f"Error checking enabled status: {e}")
            return False

    async def take_screenshot(self, path: str) -> None:
        """
        Take screenshot for debugging.
        
        Args:
            path: File path for screenshot
        """
        try:
            await self.page.screenshot(path=path)
            logger.info(f"Screenshot saved: {path}")

        except Exception as e:
            logger.warning(f"Failed to take screenshot: {e}")

    async def get_page_html(self) -> Optional[str]:
        """
        Get entire page HTML for logging.
        
        Returns:
            Page HTML or None if error
        """
        try:
            return await self.page.content()

        except Exception as e:
            logger.error(f"Error getting page HTML: {e}")
            return None

    async def log_dom_snapshot(self, context: str = "Error") -> None:
        """
        Log DOM snapshot for debugging on error.
        
        Args:
            context: Context description
        """
        with LogContext(f"DOM snapshot - {context}"):
            try:
                url = self.page.url
                title = await self.page.title()

                logger.info(f"Page URL: {url}")
                logger.info(f"Page Title: {title}")

                # Get visible text content (first 500 chars)
                text = await self.page.evaluate("() => document.body.innerText")
                if text and len(text) > 0:
                    preview = text[:500] + "..." if len(text) > 500 else text
                    logger.debug(f"Page text preview: {preview}")

                logger.debug("DOM snapshot complete")

            except Exception as e:
                logger.error(f"Error logging DOM snapshot: {e}")

    async def wait_for_element(
        self,
        selector: str,
        timeout_ms: int = 30000,
    ) -> Optional[ElementHandle]:
        """
        Wait for element to appear on page.
        
        Args:
            selector: CSS or XPath selector
            timeout_ms: Wait timeout in milliseconds
            
        Returns:
            ElementHandle if found, None if timeout
        """
        with LogContext(f"Waiting for element: {selector}"):
            try:
                element = await self.page.wait_for_selector(selector, timeout=timeout_ms)
                logger.info(f"Element found: {selector}")
                return element

            except Exception as e:
                logger.warning(f"Timeout waiting for element '{selector}': {e}")
                await self.log_dom_snapshot(f"Timeout waiting for: {selector}")
                return None

    async def wait_for_url_change(
        self,
        timeout_ms: int = 30000,
    ) -> bool:
        """
        Wait for page URL to change.
        
        Args:
            timeout_ms: Wait timeout in milliseconds
            
        Returns:
            True if URL changed, False if timeout
        """
        try:
            initial_url = self.page.url
            await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)

            if self.page.url != initial_url:
                logger.debug(f"URL changed: {initial_url} → {self.page.url}")
                return True

            return False

        except Exception as e:
            logger.warning(f"Timeout waiting for URL change: {e}")
            return False

    async def evaluate(self, expression: str) -> Any:
        """
        Safely evaluate JavaScript expression.
        
        Args:
            expression: JavaScript code to evaluate
            
        Returns:
            Result of evaluation or None if error
        """
        try:
            return await self.page.evaluate(expression)

        except Exception as e:
            logger.error(f"Error evaluating expression: {e}")
            return None
