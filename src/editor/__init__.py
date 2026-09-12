"""
Code editor integration module.

Exports:
- EditorAdapter: Base editor interface
- MonacoEditorAdapter: Monaco editor adapter with deterministic container binding
- CodeMirrorEditorAdapter: CodeMirror adapter
- AceEditorAdapter: Ace editor adapter
- TextareaAdapter: Plain textarea fallback adapter
- EditorDetector: Runtime editor type detection
- LanguageController: Language selection and verification controller
- normalize_code: Code normalization utility
"""

from .adapter import (
    EditorAdapter,
    MonacoEditorAdapter,
    CodeMirrorEditorAdapter,
    AceEditorAdapter,
    TextareaAdapter,
    normalize_code,
)
from .detector import EditorDetector
from .language_controller import LanguageController, SUPPORTED_LANGUAGES

__all__ = [
    "EditorAdapter",
    "MonacoEditorAdapter",
    "CodeMirrorEditorAdapter",
    "AceEditorAdapter",
    "TextareaAdapter",
    "EditorDetector",
    "LanguageController",
    "SUPPORTED_LANGUAGES",
    "normalize_code",
]
