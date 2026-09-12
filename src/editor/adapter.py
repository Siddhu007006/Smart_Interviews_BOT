"""
Editor Adapter Hierarchy for Hive Automation Bot.

Provides unified interface across different code editor implementations:
- EditorAdapter (Abstract Base Class)
- MonacoEditorAdapter (Angular ngx-monaco-editor)
- CodeMirrorEditorAdapter
- AceEditorAdapter
- TextareaAdapter

Enforces:
- Deterministic container-bound active instance resolution (fail-loud on ambiguity)
- Closed-loop read-back mutation verification (set_code -> get_code -> normalize -> compare)
"""

from abc import ABC, abstractmethod
import asyncio
from typing import Optional, Dict, Any
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.utils.errors import EditorError
from src.utils.logging_config import get_logger
from src.hive.ui_constants import EDITOR_CONTAINER

logger = get_logger(__name__)


def normalize_code(code: str) -> str:
    """
    Normalize code string for deterministic comparison.
    - Strips carriage returns (\\r\\n -> \\n)
    - Strips trailing whitespace per line
    - Strips leading and trailing blank lines
    """
    if not code:
        return ""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned_lines = [line.rstrip() for line in lines]
    # Strip leading empty lines
    while cleaned_lines and not cleaned_lines[0]:
        cleaned_lines.pop(0)
    # Strip trailing empty lines
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


class EditorAdapter(ABC):
    """
    Abstract base interface for code editors.
    """

    @abstractmethod
    async def get_code(self) -> str:
        """Retrieve current code from editor."""
        pass

    @abstractmethod
    async def set_code(self, code: str) -> None:
        """Inject code into editor and perform read-back verification."""
        pass

    @abstractmethod
    async def get_language(self) -> str:
        """Get currently configured language mode in editor."""
        pass

    @abstractmethod
    async def is_ready(self) -> bool:
        """Check if editor is initialized and ready for interaction."""
        pass

    async def verify_code(self, expected_code: str) -> bool:
        """
        Closed-loop verification: read back code from editor and compare with expected.

        Raises:
            EditorError: If normalized actual code does not match normalized expected code.
        """
        actual_code = await self.get_code()
        norm_expected = normalize_code(expected_code)
        norm_actual = normalize_code(actual_code)

        if norm_actual != norm_expected:
            raise EditorError(
                f"Read-back verification mismatch! "
                f"Expected {len(norm_expected)} chars, but editor contains {len(norm_actual)} chars. "
                f"Mutation did not cleanly reach the editor."
            )
        return True


class MonacoEditorAdapter(EditorAdapter):
    """
    Adapter for Monaco Editor (used in Hive via ngx-monaco-editor).

    Binds deterministically to the editor instance whose DOM node is contained
    inside the specified container (default: #editor).
    """

    def __init__(self, page: Page, container_selector: str = "#editor"):
        self.page = page
        self.container_selector = container_selector

    async def is_ready(self) -> bool:
        """
        Verify that Monaco is initialized and exactly one editor belongs to the container.
        """
        try:
            res = await self.page.evaluate('''(selector) => {
                const container = document.querySelector(selector);
                if (!container) return { ready: false, reason: `Container '${selector}' not found` };
                if (!window.monaco || !window.monaco.editor) {
                    return { ready: false, reason: "window.monaco.editor not available" };
                }
                const editors = window.monaco.editor.getEditors();
                const matching = editors.filter(ed => {
                    const node = ed.getDomNode();
                    return node && container.contains(node);
                });
                if (matching.length === 0) {
                    return { ready: false, reason: `No Monaco editor found inside '${selector}'` };
                }
                if (matching.length > 1) {
                    return { ready: false, reason: `Multiple (${matching.length}) Monaco editors found inside '${selector}'` };
                }
                return { ready: true };
            }''', self.container_selector)
            return res.get("ready", False)
        except Exception as e:
            logger.debug(f"Monaco ready check error: {e}")
            return False

    async def _execute_on_active_editor(self, script: str, *args) -> Any:
        """
        Helper to execute a JS snippet with the uniquely bound active editor instance.
        """
        # Playwright's page.evaluate(expr, arg) only accepts ONE arg after the expression.
        # Pack [containerSelector, ...extra_args] into a single list and destructure in JS.
        wrapped_script = f'''([containerSelector, ...fnArgs]) => {{
            const container = document.querySelector(containerSelector);
            if (!container) {{
                throw new Error(`Editor container '${{containerSelector}}' not found in DOM`);
            }}
            if (!window.monaco || !window.monaco.editor) {{
                throw new Error("Monaco API (window.monaco.editor) is not available");
            }}

            const editors = window.monaco.editor.getEditors();
            const matching = editors.filter(ed => {{
                const node = ed.getDomNode();
                return node && container.contains(node);
            }});

            if (matching.length === 0) {{
                throw new Error(`Deterministic binding failed: No Monaco editor found inside container '${{containerSelector}}'`);
            }}
            if (matching.length > 1) {{
                throw new Error(`Deterministic binding failed: Ambiguous match, found ${{matching.length}} Monaco editors inside container '${{containerSelector}}'`);
            }}

            const editor = matching[0];
            return ({script})(editor, ...fnArgs);
        }}'''
        try:
            return await self.page.evaluate(wrapped_script, [self.container_selector, *args])
        except Exception as e:
            raise EditorError(f"Monaco operation failed: {e}") from e

    async def get_code(self) -> str:
        """Retrieve code from the active Monaco editor."""
        return await self._execute_on_active_editor("(ed) => ed.getValue()")

    async def set_code(self, code: str) -> None:
        """
        Inject code into the active Monaco editor and perform read-back verification.

        Raises:
            EditorError: If injection fails or read-back verification fails.
        """
        logger.info(f"Injecting {len(code)} characters into Monaco editor")
        await self._execute_on_active_editor("(ed, newCode) => ed.setValue(newCode)", code)
        # Closed-loop verification
        await self.verify_code(code)
        logger.info("Monaco injection verified successfully")

    async def get_language(self) -> str:
        """Get the Monaco model's languageId."""
        return await self._execute_on_active_editor(
            "(ed) => ed.getModel() ? ed.getModel().getLanguageId() : ''"
        )


class CodeMirrorEditorAdapter(EditorAdapter):
    """
    Adapter for CodeMirror editor instances.
    """

    def __init__(self, page: Page, container_selector: str = ".CodeMirror"):
        self.page = page
        self.container_selector = container_selector

    async def is_ready(self) -> bool:
        try:
            res = await self.page.evaluate('''(selector) => {
                const el = document.querySelector(selector);
                return el && el.CodeMirror !== undefined;
            }''', self.container_selector)
            return bool(res)
        except Exception:
            return False

    async def get_code(self) -> str:
        res = await self.page.evaluate('''(selector) => {
            const el = document.querySelector(selector);
            if (!el || !el.CodeMirror) throw new Error("CodeMirror editor not found");
            return el.CodeMirror.getValue();
        }''', self.container_selector)
        return res

    async def set_code(self, code: str) -> None:
        await self.page.evaluate('''(selector, newCode) => {
            const el = document.querySelector(selector);
            if (!el || !el.CodeMirror) throw new Error("CodeMirror editor not found");
            el.CodeMirror.setValue(newCode);
        }''', self.container_selector, code)
        await self.verify_code(code)

    async def get_language(self) -> str:
        res = await self.page.evaluate('''(selector) => {
            const el = document.querySelector(selector);
            if (!el || !el.CodeMirror) return "";
            const mode = el.CodeMirror.getMode();
            return mode ? (mode.name || "") : "";
        }''', self.container_selector)
        return res


class AceEditorAdapter(EditorAdapter):
    """
    Adapter for Ace editor instances.
    """

    def __init__(self, page: Page, container_selector: str = ".ace_editor"):
        self.page = page
        self.container_selector = container_selector

    async def is_ready(self) -> bool:
        try:
            res = await self.page.evaluate('''(selector) => {
                if (!window.ace) return false;
                const el = document.querySelector(selector);
                return el !== null;
            }''', self.container_selector)
            return bool(res)
        except Exception:
            return False

    async def get_code(self) -> str:
        res = await self.page.evaluate('''(selector) => {
            if (!window.ace) throw new Error("Ace not found");
            const el = document.querySelector(selector);
            if (!el) throw new Error("Ace editor container not found");
            const editor = window.ace.edit(el);
            return editor.getValue();
        }''', self.container_selector)
        return res

    async def set_code(self, code: str) -> None:
        await self.page.evaluate('''(selector, newCode) => {
            if (!window.ace) throw new Error("Ace not found");
            const el = document.querySelector(selector);
            if (!el) throw new Error("Ace editor container not found");
            const editor = window.ace.edit(el);
            editor.setValue(newCode, -1);
        }''', self.container_selector, code)
        await self.verify_code(code)

    async def get_language(self) -> str:
        res = await self.page.evaluate('''(selector) => {
            if (!window.ace) return "";
            const el = document.querySelector(selector);
            if (!el) return "";
            const editor = window.ace.edit(el);
            const mode = editor.getSession().getMode();
            return mode ? (mode.$id || "") : "";
        }''', self.container_selector)
        return res


class TextareaAdapter(EditorAdapter):
    """
    Adapter for standard textarea code inputs.
    """

    def __init__(self, page: Page, selector: str = "textarea"):
        self.page = page
        self.selector = selector

    async def is_ready(self) -> bool:
        try:
            el = await self.page.query_selector(self.selector)
            return el is not None
        except Exception:
            return False

    async def get_code(self) -> str:
        el = await self.page.wait_for_selector(self.selector, timeout=5000)
        if not el:
            raise EditorError(f"Textarea '{self.selector}' not found")
        val = await el.input_value()
        return val

    async def set_code(self, code: str) -> None:
        el = await self.page.wait_for_selector(self.selector, timeout=5000)
        if not el:
            raise EditorError(f"Textarea '{self.selector}' not found")
        await el.fill(code)
        await self.verify_code(code)

    async def get_language(self) -> str:
        return "text"
