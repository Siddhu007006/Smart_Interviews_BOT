"""
Language Controller for Hive Code Editor.

Handles:
- Detecting current selected programming language
- Selecting target language via Angular Material dropdown
- Canonical language mapping (C, C++, Java, Python)
- Closed-loop verification of selected language
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Union
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.utils.errors import EditorError
from src.utils.logging_config import get_logger
from src.hive.ui_constants import (
    LANGUAGE_SELECT_CONTAINER,
    LANGUAGE_OPTION,
)

logger = get_logger(__name__)

SUPPORTED_LANGUAGES = ["C", "C++", "Java", "Python"]


class LanguageController:
    """
    Controls language selection on the Hive problem editor page.
    """

    def __init__(
        self,
        page_or_selector: Optional[Any] = None,
        select_selector: str = LANGUAGE_SELECT_CONTAINER,
    ):
        if page_or_selector is not None and not isinstance(page_or_selector, str):
            self.page = page_or_selector
            self.select_selector = select_selector
        elif isinstance(page_or_selector, str):
            self.page = None
            self.select_selector = page_or_selector
        else:
            self.page = None
            self.select_selector = select_selector

    @staticmethod
    def map_canonical_to_option(target_lang: str, available_options: List[str]) -> Optional[str]:
        """
        Map a canonical language name (e.g. 'Python', 'Java') to actual Hive dropdown option text.

        Examples in Hive:
        - 'C' -> 'C' (not 'C++' or 'C#')
        - 'C++' -> 'C++'
        - 'Java' -> 'Java 11' (or 'Java')
        - 'Python' -> 'Python 3.6' (prefers Python 3 over 2.7)
        """
        norm_target = target_lang.strip().lower()

        if norm_target == "c++":
            for opt in available_options:
                if "c++" in opt.lower():
                    return opt
            return None

        if norm_target == "c#":
            for opt in available_options:
                if "c#" in opt.lower():
                    return opt
            return None

        if norm_target == "c":
            # Must be standalone 'C', not 'C++' or 'C#'
            for opt in available_options:
                first_word = opt.split()[0].strip() if opt.strip() else ""
                if first_word.upper() == "C":
                    return opt
            return None

        if norm_target == "python":
            # Prefer Python 3.x over Python 2.x
            py3_candidates = [opt for opt in available_options if "python 3" in opt.lower()]
            if py3_candidates:
                return py3_candidates[0]
            # Fallback to any python
            py_candidates = [opt for opt in available_options if "python" in opt.lower()]
            if py_candidates:
                return py_candidates[0]
            return None

        if norm_target == "java":
            # Match Java or Java 11
            java_candidates = [
                opt for opt in available_options
                if opt.lower().startswith("java") and "javascript" not in opt.lower()
            ]
            if java_candidates:
                return java_candidates[0]
            return None

        # Generic substring match
        for opt in available_options:
            if norm_target in opt.lower():
                return opt

        return None

    @staticmethod
    def normalize_to_canonical(option_text: str) -> str:
        """Normalize an actual Hive dropdown string to our project's canonical language name."""
        if not option_text:
            return ""
        clean = option_text.strip()
        first_line = clean.splitlines()[0].strip()

        if first_line == "C++":
            return "C++"
        if first_line.startswith("C") and not first_line.startswith("C++") and not first_line.startswith("C#"):
            return "C"
        if first_line.startswith("Java") and not first_line.startswith("Javascript"):
            return "Java"
        if first_line.startswith("Python"):
            return "Python"
        return first_line

    async def get_current_language(self, page: Optional[Page] = None) -> str:
        """
        Get the currently active language from the dropdown.

        Returns:
            The raw active option text (e.g. 'C', 'C++', 'Java 11', 'Python 3.6').

        Raises:
            EditorError: If language dropdown cannot be found.
        """
        target_page = page or self.page
        if not target_page:
            raise EditorError("No Playwright Page provided to get_current_language")

        try:
            select_el = await target_page.wait_for_selector(self.select_selector, timeout=5000)
            if not select_el:
                raise EditorError(f"Language dropdown selector '{self.select_selector}' not found")

            # Extract displayed text
            text = await select_el.inner_text()
            if not text:
                text = await select_el.text_content() or ""

            # Hive shows 'Language\nC' or just 'C'
            lines = [l.strip() for l in text.splitlines() if l.strip() and l.strip().lower() != "language"]
            active_lang = lines[0] if lines else ""
            return active_lang

        except PlaywrightTimeoutError as e:
            raise EditorError(f"Timed out waiting for language dropdown: {e}") from e
        except Exception as e:
            if isinstance(e, EditorError):
                raise
            raise EditorError(f"Failed to get current language: {e}") from e

    async def select_language(self, page_or_target: Any, target_language: Optional[str] = None) -> str:
        """
        Select a programming language in the Hive editor.

        Supports both:
        - `select_language(page, "C++")`
        - `select_language("C++")` (when page was passed to __init__)
        """
        if target_language is None:
            canonical_query = page_or_target
            target_page = self.page
        else:
            canonical_query = target_language
            target_page = page_or_target

        if not target_page:
            raise EditorError("No Playwright Page provided to select_language")

        canonical_target = None
        for supported in SUPPORTED_LANGUAGES:
            if canonical_query.strip().lower() == supported.lower():
                canonical_target = supported
                break

        if not canonical_target:
            raise EditorError(
                f"Unsupported language '{canonical_query}'. "
                f"Supported languages are: {', '.join(SUPPORTED_LANGUAGES)}"
            )

        current = await self.get_current_language(target_page)
        if self.normalize_to_canonical(current).lower() == canonical_target.lower():
            logger.info(f"Language already set to '{current}' (matches target '{canonical_target}')")
            return current

        logger.info(f"Switching language from '{current}' to '{canonical_target}'")

        try:
            # 1. Click dropdown
            select_el = await target_page.wait_for_selector(self.select_selector, timeout=5000)
            if not select_el:
                raise EditorError(f"Language selector not found: {self.select_selector}")
            await select_el.click()
            await asyncio.sleep(0.5)

            # 2. Wait for overlay options
            await target_page.wait_for_selector(LANGUAGE_OPTION, timeout=5000)
            options = await target_page.query_selector_all(LANGUAGE_OPTION)
            if not options:
                raise EditorError("No language options found in dropdown overlay")

            option_map = {}
            for opt in options:
                raw_text = await opt.inner_text()
                clean_text = raw_text.strip()
                if clean_text:
                    option_map[clean_text] = opt

            available_texts = list(option_map.keys())
            matched_option_text = self.map_canonical_to_option(canonical_target, available_texts)

            if not matched_option_text or matched_option_text not in option_map:
                # Close dropdown before failing
                await target_page.keyboard.press("Escape")
                raise EditorError(
                    f"Target language '{canonical_target}' not found in Hive options. "
                    f"Available: {available_texts}"
                )

            # 3. Click matched option
            target_el = option_map[matched_option_text]
            await target_el.click()
            await asyncio.sleep(1.0)

            # 4. Verify selection
            verified = await self.verify_language(target_page, canonical_target)
            if not verified:
                actual = await self.get_current_language(target_page)
                raise EditorError(
                    f"Language switch failed: expected '{canonical_target}', but active language is '{actual}'"
                )

            logger.info(f"Successfully switched language to '{matched_option_text}'")
            return matched_option_text

        except Exception as e:
            if isinstance(e, EditorError):
                raise
            raise EditorError(f"Failed to select language '{canonical_target}': {e}") from e

    async def verify_language(self, page_or_canonical: Any, expected_canonical: Optional[str] = None) -> bool:
        """
        Verify that the active language in the dropdown matches the expected canonical language.

        Supports both:
        - `verify_language(page, "C++")`
        - `verify_language("C++")` (when page was passed to __init__)
        """
        if expected_canonical is None:
            canonical = page_or_canonical
            target_page = self.page
        else:
            target_page = page_or_canonical
            canonical = expected_canonical

        if not target_page:
            raise EditorError("No Playwright Page provided to verify_language")

        actual = await self.get_current_language(target_page)
        actual_canonical = self.normalize_to_canonical(actual)
        return actual_canonical.lower() == canonical.lower()
