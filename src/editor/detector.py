"""
Runtime editor type detector.

Inspects the page to determine which editor implementation is active
and instantiates the appropriate EditorAdapter.
"""

from playwright.async_api import Page
from src.editor.adapter import (
    EditorAdapter,
    MonacoEditorAdapter,
    CodeMirrorEditorAdapter,
    AceEditorAdapter,
    TextareaAdapter,
)
from src.utils.errors import EditorError
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


from typing import Optional


class EditorDetector:
    """Detects active editor on page and returns appropriate adapter."""

    def __init__(self, page: Optional[Page] = None, container_selector: str = "#editor"):
        self.page = page
        self.container_selector = container_selector

    async def detect_and_bind(
        self,
        page: Optional[Page] = None,
        container_selector: Optional[str] = None,
    ) -> EditorAdapter:
        """Instance alias for detect(), allowing EditorDetector(page).detect_and_bind()."""
        target_page = page or self.page
        if not target_page:
            raise EditorError("No Playwright Page provided to EditorDetector")
        sel = container_selector or self.container_selector
        return await self.detect(target_page, container_selector=sel)

    @staticmethod
    async def detect(page: Page, container_selector: str = "#editor") -> EditorAdapter:
        """
        Detect active editor implementation on page.

        Returns:
            The appropriate EditorAdapter instance.

        Raises:
            EditorError: If no recognized editor is detected and ready.
        """
        # 1. Check Monaco
        monaco_adapter = MonacoEditorAdapter(page, container_selector=container_selector)
        if await monaco_adapter.is_ready():
            logger.info("Detected active Monaco editor")
            return monaco_adapter

        # 2. Check CodeMirror
        codemirror_adapter = CodeMirrorEditorAdapter(page)
        if await codemirror_adapter.is_ready():
            logger.info("Detected active CodeMirror editor")
            return codemirror_adapter

        # 3. Check Ace
        ace_adapter = AceEditorAdapter(page)
        if await ace_adapter.is_ready():
            logger.info("Detected active Ace editor")
            return ace_adapter

        # 4. Check Textarea fallback
        textarea_adapter = TextareaAdapter(page)
        if await textarea_adapter.is_ready():
            logger.info("Detected active Textarea editor")
            return textarea_adapter

        raise EditorError(f"No recognized code editor found inside or near '{container_selector}'")
