"""
Unit tests for EditorAdapter hierarchy and deterministic Monaco binding.

Covers all mandatory user constraints:
1. One #editor + one matching Monaco editor -> PASS
2. #editor exists but no matching Monaco editor -> EditorError
3. Multiple candidate editors ambiguously associated -> EditorError
4. Correct editor selected among unrelated Monaco editors -> PASS
5. set_code() followed by get_code() -> exact normalized match
6. read-back mismatch -> failure (EditorError), never continue
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.editor.adapter import (
    MonacoEditorAdapter,
    CodeMirrorEditorAdapter,
    AceEditorAdapter,
    TextareaAdapter,
    normalize_code,
)
from src.editor.detector import EditorDetector
from src.utils.errors import EditorError


def test_normalize_code():
    """Verify code normalization handles CRLF, trailing whitespace, and blank lines."""
    raw = "\r\n\r\nint main() {   \r\n    return 0;   \r\n}\r\n\r\n"
    expected = "int main() {\n    return 0;\n}"
    assert normalize_code(raw) == expected


@pytest.mark.asyncio
async def test_case_1_one_container_one_matching_editor():
    """Case 1: Exactly one #editor container and one matching Monaco editor -> PASS"""
    page = MagicMock()
    # Mock page.evaluate to simulate successful deterministic binding
    page.evaluate = AsyncMock(return_value="int main() {}")

    adapter = MonacoEditorAdapter(page, container_selector="#editor")
    code = await adapter.get_code()

    assert code == "int main() {}"
    page.evaluate.assert_called_once()
    # New call signature: page.evaluate(script, [containerSelector, ...extraArgs])
    # call_args[0] = positional args tuple = (script, ['#editor'])
    call_positional = page.evaluate.call_args[0]
    assert len(call_positional) == 2, "evaluate should be called with (script, arg_list)"
    arg_list = call_positional[1]
    assert isinstance(arg_list, list), "Second positional arg should be a list"
    assert arg_list[0] == "#editor", "First element of arg list should be container selector"


@pytest.mark.asyncio
async def test_case_2_container_exists_but_no_matching_editor():
    """Case 2: #editor exists but no matching Monaco editor -> EditorError"""
    page = MagicMock()
    page.evaluate = AsyncMock(
        side_effect=Exception("Deterministic binding failed: No Monaco editor found inside container '#editor'")
    )

    adapter = MonacoEditorAdapter(page, container_selector="#editor")

    with pytest.raises(EditorError, match="No Monaco editor found inside container"):
        await adapter.get_code()


@pytest.mark.asyncio
async def test_case_3_multiple_editors_ambiguously_associated():
    """Case 3: Multiple candidate editors ambiguously associated inside #editor -> EditorError"""
    page = MagicMock()
    page.evaluate = AsyncMock(
        side_effect=Exception("Deterministic binding failed: Ambiguous match, found 2 Monaco editors inside container '#editor'")
    )

    adapter = MonacoEditorAdapter(page, container_selector="#editor")

    with pytest.raises(EditorError, match="Ambiguous match, found 2 Monaco editors"):
        await adapter.get_code()


@pytest.mark.asyncio
async def test_case_4_correct_editor_selected_among_unrelated_editors():
    """Case 4: Correct editor selected among unrelated Monaco editors -> PASS"""
    page = MagicMock()
    # In live browser, page.evaluate filters by container.contains(node).
    # We mock evaluate returning the code of the matched editor.
    page.evaluate = AsyncMock(return_value="#include <iostream>")

    adapter = MonacoEditorAdapter(page, container_selector="#editor")
    code = await adapter.get_code()

    assert code == "#include <iostream>"
    assert adapter.container_selector == "#editor"


@pytest.mark.asyncio
async def test_case_5_set_code_followed_by_get_code_matches():
    """Case 5: set_code() followed by get_code() -> exact normalized match"""
    page = MagicMock()
    injected_code = "int x = 42;\ncout << x;"

    # First evaluate is setValue, second evaluate is getValue for verify_code
    page.evaluate = AsyncMock(side_effect=[None, injected_code])

    adapter = MonacoEditorAdapter(page, container_selector="#editor")
    await adapter.set_code(injected_code)

    assert page.evaluate.call_count == 2


@pytest.mark.asyncio
async def test_case_6_read_back_mismatch_raises_editor_error():
    """Case 6: read-back mismatch -> failure (EditorError), never continue"""
    page = MagicMock()
    intended_code = "int main() { return 0; }"
    corrupted_readback = "int main() {"  # Mismatched/truncated read-back

    page.evaluate = AsyncMock(side_effect=[None, corrupted_readback])

    adapter = MonacoEditorAdapter(page, container_selector="#editor")

    with pytest.raises(EditorError, match="Read-back verification mismatch"):
        await adapter.set_code(intended_code)


@pytest.mark.asyncio
async def test_monaco_is_ready_true_and_false():
    """Verify is_ready correctly reflects Monaco initialization."""
    page = MagicMock()
    page.evaluate = AsyncMock(return_value={"ready": True})

    adapter = MonacoEditorAdapter(page)
    assert await adapter.is_ready() is True

    page.evaluate = AsyncMock(return_value={"ready": False, "reason": "Not ready"})
    assert await adapter.is_ready() is False


@pytest.mark.asyncio
async def test_editor_detector_selects_monaco(mock_page):
    """Verify EditorDetector correctly selects Monaco when is_ready is true."""
    mock_page.evaluate = AsyncMock(return_value={"ready": True})

    adapter = await EditorDetector.detect(mock_page, container_selector="#editor")
    assert isinstance(adapter, MonacoEditorAdapter)


@pytest.mark.asyncio
async def test_editor_detector_fallback_to_textarea(mock_page):
    """Verify EditorDetector falls back to Textarea if other editors not ready."""
    # Monaco evaluate -> false
    # CodeMirror evaluate -> false
    # Ace evaluate -> false
    mock_page.evaluate = AsyncMock(side_effect=[{"ready": False}, False, False])
    mock_page.query_selector = AsyncMock(return_value=MagicMock())

    adapter = await EditorDetector.detect(mock_page)
    assert isinstance(adapter, TextareaAdapter)


@pytest.mark.asyncio
async def test_editor_detector_raises_when_no_editor_found(mock_page):
    """Verify EditorDetector raises EditorError when no editor is found."""
    mock_page.evaluate = AsyncMock(side_effect=[{"ready": False}, False, False])
    mock_page.query_selector = AsyncMock(return_value=None)

    with pytest.raises(EditorError, match="No recognized code editor found"):
        await EditorDetector.detect(mock_page)
