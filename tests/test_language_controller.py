"""
Unit tests for LanguageController (Step 4).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.editor.language_controller import LanguageController, SUPPORTED_LANGUAGES
from src.utils.errors import EditorError


AVAILABLE_HIVE_OPTIONS = [
    "C\nSet as Default",
    "C++",
    "Java 11",
    "Javascript",
    "C#",
    "Python 2.7",
    "Python 3.6",
    "Go"
]


def test_canonical_mapping_hive_options():
    """Verify mapping canonical names to Hive's actual dropdown options."""
    assert LanguageController.map_canonical_to_option("C++", AVAILABLE_HIVE_OPTIONS) == "C++"
    assert LanguageController.map_canonical_to_option("C", AVAILABLE_HIVE_OPTIONS) == "C\nSet as Default"
    assert LanguageController.map_canonical_to_option("Java", AVAILABLE_HIVE_OPTIONS) == "Java 11"
    assert LanguageController.map_canonical_to_option("Python", AVAILABLE_HIVE_OPTIONS) == "Python 3.6"


def test_normalize_to_canonical():
    """Verify normalizing dropdown text to project canonical language names."""
    assert LanguageController.normalize_to_canonical("C\nSet as Default") == "C"
    assert LanguageController.normalize_to_canonical("C++") == "C++"
    assert LanguageController.normalize_to_canonical("Java 11") == "Java"
    assert LanguageController.normalize_to_canonical("Python 3.6") == "Python"
    assert LanguageController.normalize_to_canonical("Go") == "Go"


@pytest.mark.asyncio
async def test_get_current_language():
    """Verify reading the active language from the dropdown element."""
    page = MagicMock()
    select_mock = MagicMock()
    select_mock.inner_text = AsyncMock(return_value="Language\nC++")
    page.wait_for_selector = AsyncMock(return_value=select_mock)

    ctrl = LanguageController()
    lang = await ctrl.get_current_language(page)

    assert lang == "C++"


@pytest.mark.asyncio
async def test_select_language_already_selected():
    """Verify that if target language is already active, no dropdown interaction occurs."""
    page = MagicMock()
    select_mock = MagicMock()
    select_mock.inner_text = AsyncMock(return_value="Language\nC++")
    page.wait_for_selector = AsyncMock(return_value=select_mock)

    ctrl = LanguageController()
    result = await ctrl.select_language(page, "C++")

    assert result == "C++"
    # Dropdown click should not be invoked
    select_mock.click.assert_not_called()


@pytest.mark.asyncio
async def test_select_language_successful_flow():
    """Verify full selection flow: click dropdown -> map option -> click option -> verify."""
    page = MagicMock()

    # Dropdown select element
    select_mock = MagicMock()
    select_mock.click = AsyncMock()
    # Initially returns "C", then after switch returns "C++"
    select_mock.inner_text = AsyncMock(side_effect=["Language\nC", "Language\nC++"])
    page.wait_for_selector = AsyncMock(return_value=select_mock)

    # Options elements
    opt_cpp = MagicMock()
    opt_cpp.inner_text = AsyncMock(return_value="C++")
    opt_cpp.click = AsyncMock()
    opt_c = MagicMock()
    opt_c.inner_text = AsyncMock(return_value="C")
    opt_c.click = AsyncMock()

    page.query_selector_all = AsyncMock(return_value=[opt_c, opt_cpp])

    ctrl = LanguageController()
    selected = await ctrl.select_language(page, "C++")

    assert selected == "C++"
    select_mock.click.assert_called_once()
    opt_cpp.click.assert_called_once()


@pytest.mark.asyncio
async def test_select_language_unsupported_raises():
    """Verify selecting an unsupported language raises EditorError immediately."""
    page = MagicMock()
    ctrl = LanguageController()

    with pytest.raises(EditorError, match="Unsupported language 'Ruby'"):
        await ctrl.select_language(page, "Ruby")


@pytest.mark.asyncio
async def test_select_language_option_not_found_raises():
    """Verify error if mapped option is missing from the page's dropdown options."""
    page = MagicMock()

    select_mock = MagicMock()
    select_mock.click = AsyncMock()
    select_mock.inner_text = AsyncMock(return_value="Language\nC")
    page.wait_for_selector = AsyncMock(return_value=select_mock)

    # Only Go and Javascript in options, no Java
    opt_go = MagicMock()
    opt_go.inner_text = AsyncMock(return_value="Go")
    opt_go.click = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[opt_go])
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    ctrl = LanguageController()

    with pytest.raises(EditorError, match="Target language 'Java' not found in Hive options"):
        await ctrl.select_language(page, "Java")

    page.keyboard.press.assert_called_once_with("Escape")


@pytest.mark.asyncio
async def test_select_language_verification_failure_raises():
    """Verify error if language does not update after option is clicked."""
    page = MagicMock()

    select_mock = MagicMock()
    select_mock.click = AsyncMock()
    # Always returns "C" even after click
    select_mock.inner_text = AsyncMock(return_value="Language\nC")
    page.wait_for_selector = AsyncMock(return_value=select_mock)

    opt_py = MagicMock()
    opt_py.inner_text = AsyncMock(return_value="Python 3.6")
    opt_py.click = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[opt_py])

    ctrl = LanguageController()

    with pytest.raises(EditorError, match="Language switch failed"):
        await ctrl.select_language(page, "Python")
